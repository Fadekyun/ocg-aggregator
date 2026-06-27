from aggregator.adapters.base import ParsedOffer, ShopAdapter, generic_product_blocks


class DragonStarAdapter(ShopAdapter):
    slug = "dragon_star"
    listing_urls = ["https://dorasuta.jp/llofficial-cardgame"]

    def parse_listing(self, html: str, source_url: str) -> list[ParsedOffer]:
        return generic_product_blocks(html, source_url, "https://dorasuta.jp")


class CardLaboAdapter(ShopAdapter):
    slug = "card_labo"
    listing_urls = [
        "https://www.c-labo-online.jp/product-list/2995/0/photo?num=120&available=1",
        "https://www.c-labo-online.jp/product-list/3108/0/photo?num=120&available=1",
        "https://www.c-labo-online.jp/product-list/3161/0/photo?num=120&available=1",
        "https://www.c-labo-online.jp/product-list/3236/0/photo?num=120&available=1",
        "https://www.c-labo-online.jp/product-list/3319/0/photo?num=120&available=1",
        "https://www.c-labo-online.jp/product-list/3391/0/photo?num=120&available=1",
        "https://www.c-labo-online.jp/product-list/3075/0/photo?num=120&available=1",
        "https://www.c-labo-online.jp/product-list/3104/0/photo?num=120&available=1",
        "https://www.c-labo-online.jp/product-list/3184/0/photo?num=120&available=1",
        "https://www.c-labo-online.jp/product-list/3263/0/photo?num=120&available=1",
        "https://www.c-labo-online.jp/product-list/3385/0/photo?num=120&available=1",
        "https://www.c-labo-online.jp/product-list/3420/0/photo?num=120&available=1",
        "https://www.c-labo-online.jp/product-list/3037/?num=120&available=1",
    ]

    def parse_listing(self, html: str, source_url: str) -> list[ParsedOffer]:
        return generic_product_blocks(html, source_url, "https://www.c-labo-online.jp")


class ManzokuyaAdapter(ShopAdapter):
    slug = "manzokuya"
    listing_urls = ["https://shopmanzokuya.com/products/list?category_id=3184"]

    def parse_listing(self, html: str, source_url: str) -> list[ParsedOffer]:
        return generic_product_blocks(html, source_url, "https://shopmanzokuya.com")


class Net193Adapter(ShopAdapter):
    slug = "193net"
    listing_urls = ["https://193tcg.com/products/list?category_id=2415"]

    def parse_listing(self, html: str, source_url: str) -> list[ParsedOffer]:
        return generic_product_blocks(html, source_url, "https://193tcg.com")


ADAPTERS = {
    DragonStarAdapter.slug: DragonStarAdapter,
    CardLaboAdapter.slug: CardLaboAdapter,
    ManzokuyaAdapter.slug: ManzokuyaAdapter,
    Net193Adapter.slug: Net193Adapter,
}
