from django.core.management.base import BaseCommand

from aggregator.models import Shop


SHOPS = [
    {"slug": "dragon_star", "name": "Dragon Star", "base_domain": "dorasuta.jp", "enabled": True, "implemented": True, "priority": 10, "supports_exact_stock": True, "schedule_offset_minutes": 15, "shipping_base_jpy": 300},
    {"slug": "card_labo", "name": "Card Labo", "base_domain": "www.c-labo-online.jp", "enabled": True, "implemented": True, "priority": 20, "supports_exact_stock": True, "schedule_offset_minutes": 60, "shipping_base_jpy": 300},
    {"slug": "manzokuya", "name": "Manzokuya", "base_domain": "shopmanzokuya.com", "enabled": True, "implemented": True, "priority": 30, "schedule_offset_minutes": 105, "shipping_base_jpy": 250},
    {"slug": "193net", "name": "193net", "base_domain": "193tcg.com", "enabled": True, "implemented": True, "priority": 40, "schedule_offset_minutes": 150, "shipping_rule_type": Shop.SHIPPING_FREE_THRESHOLD, "shipping_base_jpy": 250, "free_shipping_threshold_jpy": 4000},
    {"slug": "hobby_station", "name": "Hobby Station", "base_domain": "www.hobbystation-single.jp", "enabled": False, "implemented": False, "priority": 100},
    {"slug": "toreca_plaza_55", "name": "Toreca Plaza 55", "base_domain": "torecaplaza55.com", "enabled": False, "implemented": False, "priority": 110},
    {"slug": "cardshop_serra", "name": "Cardshop Serra", "base_domain": "cardshop-serra.com", "enabled": False, "implemented": False, "priority": 120},
    {"slug": "realize", "name": "REALiZE", "base_domain": "realize-tcg.com", "enabled": False, "implemented": False, "priority": 130},
    {"slug": "tcg_republic", "name": "TCG Republic", "base_domain": "tcgrepublic.com", "enabled": False, "implemented": False, "priority": 140},
]


class Command(BaseCommand):
    help = "Seed default shop registry"

    def handle(self, *args, **options):
        for data in SHOPS:
            Shop.objects.update_or_create(slug=data["slug"], defaults=data)
        self.stdout.write(self.style.SUCCESS(f"seeded {len(SHOPS)} shops"))

