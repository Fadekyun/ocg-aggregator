import time

from django.core.management.base import BaseCommand
from django.db import transaction

from aggregator.models import Shop
from aggregator.services.scraping import due_shops, run_shop_scrape


class Command(BaseCommand):
    help = "Run the built-in scrape scheduler loop"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--sleep", type=int, default=60)

    def handle(self, *args, **options):
        while True:
            for shop in due_shops():
                with transaction.atomic():
                    locked = Shop.objects.select_for_update(skip_locked=True).filter(pk=shop.pk).first()
                    if not locked:
                        continue
                    self.stdout.write(f"scraping {locked.slug}")
                    run = run_shop_scrape(locked)
                    self.stdout.write(f"{locked.slug}: {run.status}")
            if options["once"]:
                break
            time.sleep(options["sleep"])

