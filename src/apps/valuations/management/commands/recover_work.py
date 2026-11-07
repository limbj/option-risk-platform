from django.core.management.base import BaseCommand

from apps.valuations.worker import recover_work


class Command(BaseCommand):
    help = "Recover expired chunk leases and published messages missing from the queue."

    def handle(self, *args, **options):
        self.stdout.write(f"Recovered {recover_work()} chunks")
