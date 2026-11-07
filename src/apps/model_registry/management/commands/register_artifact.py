import hashlib
import json
import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.model_registry.models import ModelArtifact


class Command(BaseCommand):
    help = "Validate and register a local operator-managed ML artifact under ARTIFACT_ROOT."

    def add_arguments(self, parser):
        parser.add_argument("--directory", required=True)
        parser.add_argument("--name", default="Heston MLP pricing surrogate")

    def handle(self, *args, **options):
        from ml.inference import load_artifact

        root = Path(settings.ARTIFACT_ROOT).resolve()
        path = Path(options["directory"]).resolve()
        if not path.is_relative_to(root):
            raise CommandError("Artifact directory must be inside ARTIFACT_ROOT")
        try:
            artifact = load_artifact(path)
            raw = (path / "manifest.json").read_bytes()
            manifest = json.loads(raw)
            if artifact.manifest != manifest:
                raise ValueError("Loaded manifest differs from disk")
        except Exception as exc:
            raise CommandError(f"Artifact validation failed: {exc}") from exc
        manifest_hash = hashlib.sha256(raw).hexdigest()
        # Preserve published bytes even when an offline training job reuses its output folder.
        archive_root = root / "registered"
        archive_root.mkdir(parents=True, exist_ok=True)
        archived = archive_root / manifest_hash
        staging = archive_root / f".register-{uuid.uuid4()}"
        try:
            if not archived.exists():
                staging.mkdir()
                (staging / "manifest.json").write_bytes(raw)
                for filename in ("model.pt", "validation_report.json"):
                    shutil.copyfile(path / filename, staging / filename)
                load_artifact(staging)
                try:
                    staging.rename(archived)
                except OSError:
                    if not archived.is_dir():
                        raise
            if (
                hashlib.sha256((archived / "manifest.json").read_bytes()).hexdigest()
                != manifest_hash
            ):
                raise ValueError("Existing archived manifest has been modified")
            load_artifact(archived)
        except Exception as exc:
            raise CommandError(f"Artifact archive validation failed: {exc}") from exc
        finally:
            if staging.exists() and staging.resolve().is_relative_to(archive_root.resolve()):
                shutil.rmtree(staging)
        relative_path = archived.relative_to(root).as_posix()
        existing = ModelArtifact.objects.filter(
            manifest_hash=manifest_hash, relative_path=relative_path
        ).first()
        record = existing or ModelArtifact.objects.create(
            name=options["name"],
            manifest=manifest,
            manifest_hash=manifest_hash,
            relative_path=relative_path,
        )
        self.stdout.write(f"Registered artifact {record.pk}, manifest SHA256 {manifest_hash}")
