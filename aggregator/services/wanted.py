from dataclasses import dataclass
import re

from ortools.sat.python import cp_model

from aggregator.models import CanonicalCard, CurrentOffer
from aggregator.services.normalization import normalize_card_number


MODE_CHEAPEST = "cheapest"
MODE_FEWEST_SHOPS = "fewest_shops"
MODE_BALANCED = "balanced"
MODES = {MODE_CHEAPEST, MODE_FEWEST_SHOPS, MODE_BALANCED}
UNFULFILLED_UNIT_PENALTY = 1_000_000
FEWEST_SHOP_PENALTY = 100_000
BALANCED_SHOP_PENALTY = 250


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


def shop_penalty_for_mode(mode: str) -> int:
    if mode == MODE_FEWEST_SHOPS:
        return FEWEST_SHOP_PENALTY
    if mode == MODE_BALANCED:
        return BALANCED_SHOP_PENALTY
    return 0


def optimize_plan(lines: list[WantedLine], mode: str = MODE_CHEAPEST) -> dict:
    if mode not in MODES:
        mode = MODE_CHEAPEST

    model = cp_model.CpModel()
    demand_lines = [line for line in lines if line.card]
    invalid_lines = [line for line in lines if not line.card]
    offer_rows: list[dict] = []
    warnings: list[str] = []

    for line_index, line in enumerate(demand_lines):
        for offer in offers_for_card(line.card, line.max_price):
            if not offer.buyable:
                continue
            if offer.stock_kind == CurrentOffer.KIND_EXACT:
                capacity = max(0, offer.stock_quantity or 0)
            else:
                capacity = line.quantity
                warnings.append(f"{line.card.card_number_raw} uses binary stock at {offer.shop_product.shop.name}")
            if offer.purchase_limit:
                capacity = min(capacity, offer.purchase_limit)
            if capacity <= 0:
                continue
            offer_rows.append({"line_index": line_index, "line": line, "offer": offer, "capacity": capacity})

    for row_index, row in enumerate(offer_rows):
        line = row["line"]
        row["var"] = model.NewIntVar(0, min(line.quantity, row["capacity"]), f"x_{row_index}")

    unfilled_vars = []
    for line_index, line in enumerate(demand_lines):
        line_vars = [row["var"] for row in offer_rows if row["line_index"] == line_index]
        unfilled = model.NewIntVar(0, line.quantity, f"unfilled_{line_index}")
        unfilled_vars.append((line, unfilled))
        model.Add(sum(line_vars) + unfilled == line.quantity)

    offer_to_rows: dict[int, list[dict]] = {}
    shop_to_rows: dict[int, list[dict]] = {}
    for row in offer_rows:
        offer = row["offer"]
        offer_to_rows.setdefault(offer.id, []).append(row)
        shop_to_rows.setdefault(offer.shop_product.shop.id, []).append(row)

    for rows in offer_to_rows.values():
        offer = rows[0]["offer"]
        vars_for_offer = [row["var"] for row in rows]
        if offer.stock_kind == CurrentOffer.KIND_EXACT:
            model.Add(sum(vars_for_offer) <= max(0, offer.stock_quantity or 0))
        if offer.purchase_limit:
            model.Add(sum(vars_for_offer) <= offer.purchase_limit)

    objective_terms = []
    for shop_id, rows in shop_to_rows.items():
        shop = rows[0]["offer"].shop_product.shop
        active = model.NewBoolVar(f"shop_{shop_id}_active")
        for row in rows:
            model.Add(row["var"] <= 10_000 * active)

        item_total = model.NewIntVar(0, 10_000_000, f"shop_{shop_id}_items_total")
        model.Add(item_total == sum(row["offer"].price_jpy * row["var"] for row in rows))
        shipping = model.NewIntVar(0, max(shop.shipping_base_jpy, 0), f"shop_{shop_id}_shipping")

        if shop.shipping_rule_type == shop.SHIPPING_FREE_THRESHOLD and shop.free_shipping_threshold_jpy:
            free = model.NewBoolVar(f"shop_{shop_id}_free_shipping")
            model.Add(free <= active)
            model.Add(item_total >= shop.free_shipping_threshold_jpy).OnlyEnforceIf(free)
            model.Add(shipping == 0).OnlyEnforceIf(free)
            model.Add(shipping == shop.shipping_base_jpy).OnlyEnforceIf([active, free.Not()])
            model.Add(shipping == 0).OnlyEnforceIf(active.Not())
        else:
            model.Add(shipping == shop.shipping_base_jpy * active)

        objective_terms.extend([item_total, shipping])
        penalty = shop_penalty_for_mode(mode)
        if penalty:
            objective_terms.append(penalty * active)

    for _, unfilled in unfilled_vars:
        objective_terms.append(UNFULFILLED_UNIT_PENALTY * unfilled)

    model.Minimize(sum(objective_terms) if objective_terms else sum(unfilled for _, unfilled in unfilled_vars))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        unfulfilled = invalid_lines + [
            WantedLine(line.raw, line.code, line.quantity, line.max_price, line.card, "No feasible plan")
            for line in demand_lines
        ]
        return {"groups": [], "unfulfilled": unfulfilled, "warnings": sorted(set(warnings)), "grand_total": 0, "mode": mode}

    groups: dict[str, dict] = {}
    unfulfilled: list[WantedLine] = []
    unfulfilled.extend(invalid_lines)

    for row in offer_rows:
        take = solver.Value(row["var"])
        if take <= 0:
            continue
        offer = row["offer"]
        shop = offer.shop_product.shop
        group = groups.setdefault(shop.slug, {"shop": shop, "plan_items": [], "items_total": 0})
        group["plan_items"].append({"line": row["line"], "offer": offer, "quantity": take})
        group["items_total"] += take * offer.price_jpy

    for line, unfilled in unfilled_vars:
        missing = solver.Value(unfilled)
        if missing:
            unfulfilled.append(WantedLine(line.raw, line.code, missing, line.max_price, line.card, "Insufficient stock"))

    grand_total = 0
    for group in groups.values():
        group["shipping"] = group["shop"].estimate_shipping(group["items_total"])
        group["store_total"] = group["items_total"] + group["shipping"]
        grand_total += group["store_total"]
    sorted_groups = sorted(groups.values(), key=lambda group: (group["store_total"], group["shop"].name))
    return {"groups": sorted_groups, "unfulfilled": unfulfilled, "warnings": sorted(set(warnings)), "grand_total": grand_total, "mode": mode}


def simple_plan(lines: list[WantedLine]) -> dict:
    return optimize_plan(lines, MODE_CHEAPEST)
