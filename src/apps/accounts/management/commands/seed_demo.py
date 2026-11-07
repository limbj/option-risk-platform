import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.portfolios.models import InputVersion
from apps.valuations.services import create_inputs


class Command(BaseCommand):
    help = "Create a demo account and synthetic inputs; password comes only from DEMO_PASSWORD."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="demo")

    @transaction.atomic
    def handle(self, *args, **options):
        password = os.environ.get("DEMO_PASSWORD", "")
        if len(password) < 12:
            raise CommandError("Set DEMO_PASSWORD to a secret with at least 12 characters")
        user, created = get_user_model().objects.get_or_create(username=options["username"])
        if created:
            user.set_password(password)
            user.save(update_fields=["password"])
        if not InputVersion.objects.filter(owner=user).exists():
            payload = json.loads(
                (settings.BASE_DIR / "examples" / "stage1_inputs.json").read_text()
            )
            create_inputs(user, "Synthetic European options demo", payload)
        self.stdout.write("Demo account and synthetic input version are available.")
