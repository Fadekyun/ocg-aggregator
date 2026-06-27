from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urljoin
import re
import time

import httpx
from bs4 import BeautifulSoup
from django.conf import settings

from aggregator.models import CurrentOffer
from aggregator.services.normalization import normalize_card_number


@dataclass
class DiscoveredProduct:
    key: str
    url: str
    title: str = ""
    raw: str = ""


@dataclass
class ParsedOffer:
    shop_product_key: str
    product_url: str
    title_raw: str
    card_code_raw: str
    price_jpy: int
    stock_status: str
    stock_kind: str
    stock_quantity: int | None = None
    condition_raw: str = ""
    purchase_limit: int | None = None
    notes: str = ""

    @property
    def card_code_normalized(self) -> str:
        return normalize_card_number(self.card_code_raw)


@dataclass
class AdapterRunResult:
    offers: list[ParsedOffer] = field(default_factory=list)
    pages_requested: int = 0
    parse_errors: int = 0
    http_errors: int = 0
    errors: list[str] = field(default_factory=list)


class ShopAdapter:
    slug = ""
    parser_version = "1"
    listing_urls: list[str] = []

    def __init__(self, shop):
        self.shop = shop
        self.client = httpx.Client(
            headers={"User-Agent": settings.SCRAPER_USER_AGENT},
            follow_redirects=True,
            timeout=30,
        )

    def close(self):
        self.client.close()

    def discover_products(self) -> AdapterRunResult:
        result = AdapterRunResult()
        for url in self.listing_urls:
            try:
                response = self.client.get(url)
                result.pages_requested += 1
                if response.status_code >= 400:
                    result.http_errors += 1
                    result.errors.append(f"{url} returned {response.status_code}")
                    retry_after = response.headers.get("Retry-After")
                    if response.status_code == 429 and retry_after and retry_after.isdigit():
                        time.sleep(min(int(retry_after), 60))
                    continue
                result.offers.extend(self.parse_listing(response.text, url))
            except httpx.HTTPError as exc:
                result.http_errors += 1
                result.errors.append(str(exc))
            finally:
                time.sleep(self.shop.minimum_request_delay_ms / 1000)
        return result

    def parse_listing(self, html: str, source_url: str) -> Iterable[ParsedOffer]:
        raise NotImplementedError

    def validate_run(self, result: AdapterRunResult) -> tuple[bool, str]:
        if result.http_errors and not result.offers:
            return False, "All listing requests failed"
        if result.parse_errors > max(5, len(result.offers) // 5):
            return False, "Too many parse errors"
        if not result.offers:
            return False, "No products parsed"
        sold_out = [o for o in result.offers if o.stock_status == CurrentOffer.STOCK_SOLD_OUT]
        if len(result.offers) >= 20 and len(sold_out) == len(result.offers):
            return False, "Every parsed product is sold out"
        return True, ""


PRICE_RE = re.compile(r"([0-9０-９,，]+)\s*円|[￥¥]\s*([0-9０-９,，]+)")
CARD_CODE_RE = re.compile(r"(?:PL|LL)[!！\sA-Za-z0-9_\-＋+]+(?:SEC|SECE|SECL|LLE|PE\+|PE|P\+|RM|R\+|PR|SD|L\+|L|R|N)")


def parse_price(text: str) -> int | None:
    match = PRICE_RE.search(text)
    if not match:
        return None
    value = next(group for group in match.groups() if group)
    return int(value.translate(str.maketrans("０１２３４５６７８９，", "0123456789,")).replace(",", ""))


def find_card_code(text: str) -> str:
    match = CARD_CODE_RE.search(text)
    return match.group(0).strip() if match else ""


def text_stock(text: str) -> tuple[str, str, int | None]:
    if re.search(r"SOLD\s*OUT|売り切れ|品切れ|在庫なし", text, re.I):
        return CurrentOffer.STOCK_SOLD_OUT, CurrentOffer.KIND_EXACT, 0
    qty_match = re.search(r"在庫[:：]?\s*([0-9０-９]+)|([0-9０-９]+)\s*(?:個|枚)", text)
    if qty_match:
        raw = next(group for group in qty_match.groups() if group)
        qty = int(raw.translate(str.maketrans("０１２３４５６７８９", "0123456789")))
        return (CurrentOffer.STOCK_AVAILABLE if qty > 0 else CurrentOffer.STOCK_SOLD_OUT), CurrentOffer.KIND_EXACT, qty
    if "◯" in text or "○" in text or re.search(r"カートに入れる|在庫あり|購入", text):
        return CurrentOffer.STOCK_AVAILABLE, CurrentOffer.KIND_BINARY, None
    return CurrentOffer.STOCK_UNKNOWN, CurrentOffer.KIND_UNKNOWN, None


def generic_product_blocks(html: str, source_url: str, base_url: str) -> list[ParsedOffer]:
    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.select("[data-product-id], .product, .item, li, article")
    offers: list[ParsedOffer] = []
    for index, block in enumerate(blocks):
        text = " ".join(block.get_text(" ", strip=True).split())
        code = find_card_code(text)
        price = parse_price(text)
        if not code or price is None:
            continue
        link = block.find("a", href=True)
        url = urljoin(base_url or source_url, link["href"]) if link else source_url
        key = block.get("data-product-id") or url.rsplit("/", 1)[-1] or f"row-{index}"
        status, kind, qty = text_stock(text)
        offers.append(
            ParsedOffer(
                shop_product_key=str(key),
                product_url=url,
                title_raw=text[:500],
                card_code_raw=code,
                price_jpy=price,
                stock_status=status,
                stock_kind=kind,
                stock_quantity=qty,
            )
        )
    return offers
