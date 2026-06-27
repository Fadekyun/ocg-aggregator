from django.core.management.base import BaseCommand

from aggregator.models import Shop
from aggregator.services.scraping import run_shop_scrape


class Command(BaseCommand):
    help = "Run all enabled implemented shop scrapers once"

    def handle(self, *args, **options):
        for shop in Shop.objects.filter(enabled=True, implemented=True).order_by("priority"):
            run = run_shop_scrape(shop)
            self.stdout.write(f"{shop.slug}: {run.status} seen={run.products_seen} updated={run.products_updated}")

