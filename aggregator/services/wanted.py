from dataclasses import dataclass
import re

from aggregator.models import CanonicalCard, CurrentOffer
from aggregator.services.normalization import normalize_card_number


@dataclass
class WantedLine:
    raw: str
    code: str
    quantity: int
    max_price: int | None
    card: CanonicalCard | None
    error: str = ""


def parse_wanted_text(text: str) -> list[WantedLine]:
    lines: list[WantedLine] = []
    for raw_line in text.splitlines():
        raw = raw_line.strip()
        if not raw:
            continue
        max_price = None
        max_match = re.search(r"\bmax\s+([0-9,]+)", raw, re.I)
        if max_match:
            max_price = int(max_match.group(1).replace(",", ""))
            raw = raw[: max_match.start()].strip()
        if "," in raw:
            parts = [p.strip() for p in raw.split(",")]
            code = parts[0]
            quantity = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            if len(parts) > 2 and parts[2].isdigit():
                max_price = int(parts[2])
        else:
            match = re.match(r"(.+?)\s*x\s*([0-9]+)$", raw, re.I)
            if match:
                code, quantity = match.group(1).strip(), int(match.group(2))
            else:
                code, quantity = raw, 1
        normalized = normalize_card_number(code)
        candidates = list(CanonicalCard.objects.filter(card_number_normalized=normalized, active=True)[:2])
        card = candidates[0] if len(candidates) == 1 else None
        error = ""
        if not candidates:
            error = "No matching card"
        elif len(candidates) > 1:
            error = "Ambiguous card code"
        lines.append(WantedLine(raw=raw_line.strip(), code=code, quantity=quantity, max_price=max_price, card=card, error=error))
    return merge_lines(lines)


def merge_lines(lines: list[WantedLine]) -> list[WantedLine]:
    merged: dict[tuple[int | None, str, int | None, str], WantedLine] = {}
    for line in lines:
        key = (line.card.id if line.card else None, line.code, line.max_price, line.error)
        if key in merged:
            merged[key].quantity += line.quantity
        else:
            merged[key] = line
    return list(merged.values())


def offers_for_card(card: CanonicalCard, max_price: int | None = None):
    qs = CurrentOffer.objects.select_related("shop_product__shop").filter(
        shop_product__canonical_card=card,
        stock_status=CurrentOffer.STOCK_AVAILABLE,
        shop_product__active=True,
    ).order_by("price_jpy")
    if max_price is not None:
        qs = qs.filter(price_jpy__lte=max_price)
    return list(qs)


def simple_plan(lines: list[WantedLine]) -> dict:
    groups: dict[str, dict] = {}
    unfulfilled: list[WantedLine] = []
    warnings: list[str] = []
    for line in lines:
        if not line.card:
            unfulfilled.append(line)
            continue
        remaining = line.quantity
        for offer in offers_for_card(line.card, line.max_price):
            if remaining <= 0:
                break
            if offer.stock_kind == CurrentOffer.KIND_EXACT:
                available = max(0, offer.stock_quantity or 0)
            else:
                available = remaining
                warnings.append(f"{line.card.card_number_raw} uses binary stock at {offer.shop_product.shop.name}")
            if offer.purchase_limit:
                available = min(available, offer.purchase_limit)
            take = min(remaining, available)
            if take <= 0:
                continue
            shop = offer.shop_product.shop
            group = groups.setdefault(shop.slug, {"shop": shop, "plan_items": [], "items_total": 0})
            group["plan_items"].append({"line": line, "offer": offer, "quantity": take})
            group["items_total"] += take * offer.price_jpy
            remaining -= take
        if remaining:
            unfulfilled.append(WantedLine(line.raw, line.code, remaining, line.max_price, line.card, "Insufficient stock"))
    grand_total = 0
    for group in groups.values():
        group["shipping"] = group["shop"].estimate_shipping(group["items_total"])
        group["store_total"] = group["items_total"] + group["shipping"]
        grand_total += group["store_total"]
    return {"groups": groups.values(), "unfulfilled": unfulfilled, "warnings": sorted(set(warnings)), "grand_total": grand_total}
