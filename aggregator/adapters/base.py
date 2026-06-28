from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urljoin, urldefrag
import re
import time

import httpx
from bs4 import BeautifulSoup, Comment
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
    follow_pagination = True
    max_pages = 60

    def __init__(self, shop):
        self.shop = shop
        self.client = httpx.Client(
            headers={"User-Agent": settings.SCRAPER_USER_AGENT},
            follow_redirects=True,
            timeout=30,
        )

    def close(self):
        self.client.close()

    def fetch_html(self, url: str) -> tuple[int, str, str | None]:
        response = self.client.get(url)
        retry_after = response.headers.get("Retry-After")
        return response.status_code, response.text, retry_after

    def pagination_urls(self, html: str, source_url: str) -> list[str]:
        if not self.follow_pagination:
            return []
        soup = BeautifulSoup(html, "html.parser")
        urls = []
        for link in soup.find_all("a", href=True):
            href = urljoin(source_url, link["href"])
            href, _fragment = urldefrag(href)
            if href == source_url:
                continue
            if "pageno=" not in href and "page=" not in href:
                continue
            urls.append(href)
        return sorted(set(urls))

    def discover_products(self) -> AdapterRunResult:
        result = AdapterRunResult()
        queue = list(self.listing_urls)
        seen_urls: set[str] = set()
        while queue and len(seen_urls) < self.max_pages:
            url = queue.pop(0)
            if url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                status_code, html, retry_after = self.fetch_html(url)
                result.pages_requested += 1
                if status_code >= 400:
                    result.http_errors += 1
                    result.errors.append(f"{url} returned {status_code}")
                    if status_code == 429 and retry_after and retry_after.isdigit():
                        time.sleep(min(int(retry_after), 60))
                    continue
                result.offers.extend(self.parse_listing(html, url))
                for next_url in self.pagination_urls(html, url):
                    if next_url not in seen_urls and next_url not in queue:
                        queue.append(next_url)
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
CARD_CODE_RE = re.compile(
    r"(?:(?:LL[-ー])?PL[!！]?|LL[-ー])[A-Za-z0-9_\-＋+ ]{3,80}",
    re.I,
)
STRICT_CARD_CODE_RE = re.compile(
    r"(?:(?:LL[-ー])?PL[!！]?|LL[-ー])[A-Za-z0-9_\-＋+ ]*"
    r"(?:SECE|SECL|SECS|SEC|SRE|LLE|PE[+＋]?|P[+＋]?|RM|R[+＋]?|PR|SD|CL|L[+＋]?|N)"
    r"(?=$|[^A-Za-z0-9＋+])",
    re.I,
)
BRACKET_CODE_RE = re.compile(r"[【\[]\s*([^【】\[\]]*PL[!！]?[A-Za-z0-9_\-＋+ ]+)\s*[】\]]", re.I)
JP_INT_TABLE = str.maketrans("０１２３４５６７８９", "0123456789")
PURCHASE_LIMIT_RE = re.compile(r"(?:お一人様|購入制限|購入上限|制限|上限)[:：]?\s*([0-9０-９]+)\s*(?:枚|点|個)?")
CONDITION_RE = re.compile(r"(?:状態\s*[A-ZＡ-Ｚ]|美品|プレイ用|中古|NM)", re.I)


def parse_price(text: str) -> int | None:
    match = PRICE_RE.search(text)
    if not match:
        return None
    value = next(group for group in match.groups() if group)
    return int(value.translate(str.maketrans("０１２３４５６７８９，", "0123456789,")).replace(",", ""))


def find_card_code(text: str) -> str:
    bracket_match = BRACKET_CODE_RE.search(text)
    if bracket_match:
        inner = bracket_match.group(1).strip()
        strict_inner = STRICT_CARD_CODE_RE.search(inner)
        if strict_inner:
            return strict_inner.group(0).strip()
        if CARD_CODE_RE.search(inner):
            return inner
    match = STRICT_CARD_CODE_RE.search(text) or CARD_CODE_RE.search(text)
    if not match:
        return ""
    value = match.group(0).strip()
    if " " in value:
        value = value.split()[0]
    value = re.sub(r"\s+[0-9０-９,，]+$", "", value).strip()
    return re.sub(r"^LL[-ー](PL[!！]?)", r"\1", value, flags=re.I)


def parse_purchase_limit(text: str) -> int | None:
    match = PURCHASE_LIMIT_RE.search(text)
    if not match:
        return None
    return int(match.group(1).translate(JP_INT_TABLE))


def parse_condition(text: str) -> str:
    match = CONDITION_RE.search(text)
    return match.group(0).strip() if match else ""


def text_stock(text: str) -> tuple[str, str, int | None]:
    if re.search(r"SOLD\s*OUT|売り切れ|品切れ|在庫なし", text, re.I):
        return CurrentOffer.STOCK_SOLD_OUT, CurrentOffer.KIND_EXACT, 0
    qty_match = re.search(
        r"(?:在庫(?:数)?|残り|残数)[:：]?\s*([0-9０-９]+)\s*(?:個|枚|点)?",
        text,
    )
    if qty_match:
        raw = qty_match.group(1)
        qty = int(raw.translate(JP_INT_TABLE))
        return (CurrentOffer.STOCK_AVAILABLE if qty > 0 else CurrentOffer.STOCK_SOLD_OUT), CurrentOffer.KIND_EXACT, qty
    if "◯" in text or "○" in text or re.search(r"カートに入れる|在庫あり|購入", text):
        return CurrentOffer.STOCK_AVAILABLE, CurrentOffer.KIND_BINARY, None
    return CurrentOffer.STOCK_UNKNOWN, CurrentOffer.KIND_UNKNOWN, None


def generic_product_blocks(html: str, source_url: str, base_url: str) -> list[ParsedOffer]:
    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.select("[data-product-id], .ec-shelfGrid__item, .product-card-wrapper, .product, .item, li, article")
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
        purchase_limit = parse_purchase_limit(text)
        condition_raw = parse_condition(text)
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
                condition_raw=condition_raw,
                purchase_limit=purchase_limit,
            )
        )
    return offers


def eccube_shelf_blocks(html: str, source_url: str, base_url: str, default_binary_available: bool = False) -> list[ParsedOffer]:
    soup = BeautifulSoup(html, "html.parser")
    offers: list[ParsedOffer] = []
    for index, block in enumerate(soup.select(".ec-shelfGrid__item")):
        visible_text = " ".join(block.get_text(" ", strip=True).split())
        comments_text = " ".join(str(c) for c in block.find_all(string=lambda x: isinstance(x, Comment)))
        text = " ".join((visible_text, comments_text)).strip()
        code = find_card_code(text)
        price = parse_price(text)
        if not code or price is None:
            continue
        link = block.find("a", href=True)
        url = urljoin(base_url or source_url, link["href"]) if link else source_url
        key = re.sub(r"\D+", "", url.rsplit("/", 1)[-1]) or url.rsplit("/", 1)[-1] or f"row-{index}"
        status, kind, qty = text_stock(text)
        if default_binary_available and status == CurrentOffer.STOCK_UNKNOWN:
            status, kind, qty = CurrentOffer.STOCK_AVAILABLE, CurrentOffer.KIND_BINARY, None
        offers.append(
            ParsedOffer(
                shop_product_key=str(key),
                product_url=url,
                title_raw=visible_text[:500],
                card_code_raw=code,
                price_jpy=price,
                stock_status=status,
                stock_kind=kind,
                stock_quantity=qty,
                condition_raw=parse_condition(text),
                purchase_limit=parse_purchase_limit(text),
            )
        )
    return offers
