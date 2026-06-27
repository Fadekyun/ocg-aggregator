from django.conf import settings
from django.core.management.base import BaseCommand

from aggregator.services.catalog import import_catalog


class Command(BaseCommand):
    help = "Import canonical cards from the read-only Love Live JSON catalogue"

    def add_arguments(self, parser):
        parser.add_argument("--path", default=settings.CARD_CATALOG_PATH)

    def handle(self, *args, **options):
        result = import_catalog(options["path"])
        self.stdout.write(
            self.style.SUCCESS(
                f"created={result.created} updated={result.updated} unchanged={result.unchanged} duplicates={len(result.duplicates or [])}"
            )
        )
        for duplicate in result.duplicates or []:
            self.stdout.write(self.style.WARNING(f"duplicate normalized card number: {duplicate}"))

