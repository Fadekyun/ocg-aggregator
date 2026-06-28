import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aggregator.adapters.base import (
    ParsedOffer,
    ShopAdapter,
    eccube_shelf_blocks,
    find_card_code,
    generic_product_blocks,
    parse_condition,
    parse_price,
    parse_purchase_limit,
)
from aggregator.models import CurrentOffer


class DragonStarAdapter(ShopAdapter):
    slug = "dragon_star"
    parser_version = "2"
    listing_urls = ["https://dorasuta.jp/llofficial-cardgame"]

    def parse_listing(self, html: str, source_url: str) -> list[ParsedOffer]:
        return generic_product_blocks(html, source_url, "https://dorasuta.jp")


class CardLaboAdapter(ShopAdapter):
    slug = "card_labo"
    parser_version = "2"
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
    parser_version = "2"
    listing_urls = ["https://shopmanzokuya.com/products/list?category_id=3184"]

    def parse_listing(self, html: str, source_url: str) -> list[ParsedOffer]:
        offers = eccube_shelf_blocks(html, source_url, "https://shopmanzokuya.com")
        return offers or generic_product_blocks(html, source_url, "https://shopmanzokuya.com")


class Net193Adapter(ShopAdapter):
    slug = "193net"
    parser_version = "2"
    listing_urls = ["https://193tcg.com/products/list?category_id=2415"]

    def parse_listing(self, html: str, source_url: str) -> list[ParsedOffer]:
        offers = eccube_shelf_blocks(html, source_url, "https://193tcg.com", default_binary_available=True)
        return offers or generic_product_blocks(html, source_url, "https://193tcg.com")


class CardonAdapter(ShopAdapter):
    slug = "cardon"
    parser_version = "1"
    listing_urls = [
        "https://cardon.jp/collections/all/%E3%83%A9%E3%83%96%E3%83%A9%E3%82%A4%E3%83%96-%E3%82%AA%E3%83%95%E3%82%A3%E3%82%B7%E3%83%A3%E3%83%AB%E3%82%AB%E3%83%BC%E3%83%89%E3%82%B2%E3%83%BC%E3%83%A0?filter.v.availability=1&sort_by=price-descending"
    ]

    def parse_listing(self, html: str, source_url: str) -> list[ParsedOffer]:
        soup = BeautifulSoup(html, "html.parser")
        offers: list[ParsedOffer] = []
        for index, block in enumerate(soup.select("li.grid__item")):
            text = " ".join(block.get_text(" ", strip=True).split())
            code = find_card_code(text)
            price = parse_price(text)
            if not code or price is None:
                continue
            link = block.find("a", href=True)
            url = urljoin("https://cardon.jp", link["href"]) if link else source_url
            key = url.split("/products/", 1)[-1].split("?", 1)[0] if "/products/" in url else f"row-{index}"
            offers.append(
                ParsedOffer(
                    shop_product_key=key,
                    product_url=url,
                    title_raw=text[:500],
                    card_code_raw=code,
                    price_jpy=price,
                    stock_status=CurrentOffer.STOCK_AVAILABLE,
                    stock_kind=CurrentOffer.KIND_BINARY,
                    stock_quantity=None,
                    condition_raw=parse_condition(text),
                    purchase_limit=parse_purchase_limit(text),
                )
            )
        return offers


class HobbyStationAdapter(ShopAdapter):
    slug = "hobby_station"
    parser_version = "1"
    top_url = "https://www.hobbystation-single.jp/LL/top"
    max_pages = 80

    def discover_products(self):
        response = self.client.get(self.top_url)
        urls = []
        if response.status_code < 400:
            soup = BeautifulSoup(response.text, "html.parser")
            for link in soup.find_all("a", href=True):
                href = urljoin("https://www.hobbystation-single.jp", link["href"])
                if "/LL/product/list" not in href or "(BANNER)" not in href:
                    continue
                text = " ".join(link.get_text(" ", strip=True).split())
                if "クリアポケット" in text:
                    continue
                if href not in urls:
                    urls.append(href)
        self.listing_urls = urls
        return super().discover_products()

    def parse_listing(self, html: str, source_url: str) -> list[ParsedOffer]:
        soup = BeautifulSoup(html, "html.parser")
        offers: list[ParsedOffer] = []
        for index, block in enumerate(soup.select("ul.searchRsultList > li")):
            text = " ".join(block.get_text(" ", strip=True).split())
            code = find_card_code(text)
            price = parse_price(text)
            if not code or price is None:
                continue
            link = block.find("a", href=re.compile(r"/LL/product/detail/"))
            url = urljoin("https://www.hobbystation-single.jp", link["href"]) if link else source_url
            key = re.sub(r"\D+", "", url.rsplit("/", 1)[-1]) or f"row-{index}"
            html_block = str(block)
            sold_out = "SOLD OUT" in html_block or "icon_soldout" in html_block
            offers.append(
                ParsedOffer(
                    shop_product_key=key,
                    product_url=url,
                    title_raw=text[:500],
                    card_code_raw=code,
                    price_jpy=price,
                    stock_status=CurrentOffer.STOCK_SOLD_OUT if sold_out else CurrentOffer.STOCK_AVAILABLE,
                    stock_kind=CurrentOffer.KIND_EXACT if sold_out else CurrentOffer.KIND_BINARY,
                    stock_quantity=0 if sold_out else None,
                    condition_raw=parse_condition(text),
                    purchase_limit=parse_purchase_limit(text),
                )
            )
        return offers


ADAPTERS = {
    DragonStarAdapter.slug: DragonStarAdapter,
    CardLaboAdapter.slug: CardLaboAdapter,
    ManzokuyaAdapter.slug: ManzokuyaAdapter,
    Net193Adapter.slug: Net193Adapter,
    CardonAdapter.slug: CardonAdapter,
    HobbyStationAdapter.slug: HobbyStationAdapter,
}
