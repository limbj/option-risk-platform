import time

from django.core.management.base import BaseCommand

from apps.valuations.worker import dispatch_pending, recover_work


class Command(BaseCommand):
    help = "Publish durable outbox events and recover abandoned work (run alongside workers)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=float, default=2.0)

    def handle(self, *args, **options):
        while True:
            recovered = recover_work()
            sent = dispatch_pending()
            if recovered or sent or options["once"]:
                self.stdout.write(f"Published {sent}; recovered {recovered}")
            if options["once"]:
                return
            time.sleep(max(0.1, options["interval"]))
