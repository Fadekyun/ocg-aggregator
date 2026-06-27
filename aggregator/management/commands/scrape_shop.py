from django.core.management.base import BaseCommand, CommandError

from aggregator.models import Shop
from aggregator.services.scraping import run_shop_scrape


class Command(BaseCommand):
    help = "Run one shop scraper now"

    def add_arguments(self, parser):
        parser.add_argument("slug")

    def handle(self, *args, **options):
        shop = Shop.objects.filter(slug=options["slug"]).first()
        if not shop:
            raise CommandError(f"Unknown shop: {options['slug']}")
        run = run_shop_scrape(shop)
        self.stdout.write(f"{shop.slug}: {run.status} seen={run.products_seen} updated={run.products_updated} errors={run.error_summary}")

