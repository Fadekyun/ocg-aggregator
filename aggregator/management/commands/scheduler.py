import time

from django.core.management.base import BaseCommand

from aggregator.services.scraping import due_shops, run_shop_scrape


class Command(BaseCommand):
    help = "Run the built-in scrape scheduler loop"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--sleep", type=int, default=60)

    def handle(self, *args, **options):
        while True:
            for shop in due_shops():
                self.stdout.write(f"scraping {shop.slug}")
                run = run_shop_scrape(shop)
                self.stdout.write(f"{shop.slug}: {run.status}")
            if options["once"]:
                break
            time.sleep(options["sleep"])
