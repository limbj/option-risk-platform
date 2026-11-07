"""PostgreSQL guards also cover raw SQL and ORM paths bypassing model.save()."""

from django.db import migrations

IMMUTABLE_TABLES = (
    "portfolios_portfolioversion",
    "portfolios_inputversion",
    "marketdata_marketsnapshot",
    "marketdata_scenariosetversion",
    "model_registry_modelversion",
    "model_registry_modelartifact",
    "valuations_valuationresult",
)


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        CREATE FUNCTION option_risk_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Published records are immutable'; END; $$;
    """)
    for table in IMMUTABLE_TABLES:
        schema_editor.execute(f"""
            CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION option_risk_reject_mutation();
        """)
    schema_editor.execute("""
        CREATE FUNCTION option_risk_guard_run() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Runs cannot be deleted'; END IF;
            IF OLD.status IN ('COMPLETED', 'PARTIAL_ERROR', 'FAILED') THEN
                RAISE EXCEPTION 'Completed runs are immutable';
            END IF;
            IF (to_jsonb(OLD) - ARRAY['status','started_at','completed_at']) IS DISTINCT FROM
               (to_jsonb(NEW) - ARRAY['status','started_at','completed_at']) THEN
                RAISE EXCEPTION 'Run inputs and provenance are immutable';
            END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER immutable_run_inputs BEFORE UPDATE OR DELETE ON valuations_valuationrun
        FOR EACH ROW EXECUTE FUNCTION option_risk_guard_run();
    """)
    schema_editor.execute("""
        CREATE FUNCTION option_risk_guard_chunk() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Chunks cannot be deleted'; END IF;
            IF OLD.status IN ('COMPLETED','FAILED') THEN
                RAISE EXCEPTION 'Completed chunks are immutable';
            END IF;
            IF OLD.run_id IS DISTINCT FROM NEW.run_id OR
               OLD.scenario_index IS DISTINCT FROM NEW.scenario_index OR
               OLD.id IS DISTINCT FROM NEW.id THEN
                RAISE EXCEPTION 'Chunk identity is immutable';
            END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER immutable_chunk_identity BEFORE UPDATE OR DELETE ON valuations_runchunk
        FOR EACH ROW EXECUTE FUNCTION option_risk_guard_chunk();
    """)


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in IMMUTABLE_TABLES:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS immutable_record ON {table}")
    schema_editor.execute("DROP TRIGGER IF EXISTS immutable_run_inputs ON valuations_valuationrun")
    schema_editor.execute("DROP TRIGGER IF EXISTS immutable_chunk_identity ON valuations_runchunk")
    schema_editor.execute("DROP FUNCTION IF EXISTS option_risk_reject_mutation()")
    schema_editor.execute("DROP FUNCTION IF EXISTS option_risk_guard_run()")
    schema_editor.execute("DROP FUNCTION IF EXISTS option_risk_guard_chunk()")


class Migration(migrations.Migration):
    dependencies = [("valuations", "0001_initial")]
    operations = [migrations.RunPython(install_guards, remove_guards)]
