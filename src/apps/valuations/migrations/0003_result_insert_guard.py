from django.db import migrations


def install_guard(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        CREATE FUNCTION option_risk_guard_result_insert() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE eligible boolean; parent_run uuid;
        BEGIN
            SELECT run_id INTO parent_run FROM valuations_runchunk WHERE id = NEW.chunk_id;
            PERFORM id FROM valuations_valuationrun WHERE id = parent_run FOR UPDATE;
            PERFORM id FROM valuations_runchunk WHERE id = NEW.chunk_id FOR UPDATE;
            SELECT (c.run_id = NEW.run_id AND c.scenario_index = NEW.scenario_index
                    AND c.status = 'RUNNING' AND r.status = 'RUNNING'
                    AND NEW.position_index >= 0
                    AND NEW.position_index < jsonb_array_length(i.payload->'positions'))
            INTO eligible
            FROM valuations_runchunk c
            JOIN valuations_valuationrun r ON r.id = c.run_id
            JOIN portfolios_inputversion i ON i.id = r.inputs_id
            WHERE c.id = NEW.chunk_id;
            IF eligible IS DISTINCT FROM TRUE THEN
                RAISE EXCEPTION 'Result requires an active matching parent and eligible position';
            END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER valid_result_parent BEFORE INSERT ON valuations_valuationresult
        FOR EACH ROW EXECUTE FUNCTION option_risk_guard_result_insert();
        CREATE FUNCTION option_risk_guard_chunk_insert() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE eligible boolean;
        BEGIN
            PERFORM id FROM valuations_valuationrun WHERE id = NEW.run_id FOR UPDATE;
            SELECT (r.status = 'QUEUED' AND NEW.scenario_index >= 0
                    AND NEW.scenario_index < jsonb_array_length(
                        r.provenance->'execution_scenarios'))
            INTO eligible FROM valuations_valuationrun r WHERE r.id = NEW.run_id;
            IF eligible IS DISTINCT FROM TRUE THEN
                RAISE EXCEPTION 'New chunks require a queued run and eligible scenario';
            END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER valid_chunk_parent BEFORE INSERT ON valuations_runchunk
        FOR EACH ROW EXECUTE FUNCTION option_risk_guard_chunk_insert();
    """)


def remove_guard(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS valid_result_parent ON valuations_valuationresult"
    )
    schema_editor.execute("DROP FUNCTION IF EXISTS option_risk_guard_result_insert()")
    schema_editor.execute("DROP TRIGGER IF EXISTS valid_chunk_parent ON valuations_runchunk")
    schema_editor.execute("DROP FUNCTION IF EXISTS option_risk_guard_chunk_insert()")


class Migration(migrations.Migration):
    dependencies = [("valuations", "0002_immutability_guards")]
    operations = [migrations.RunPython(install_guard, remove_guard)]
