from aggregator.models import CanonicalCard, ShopProduct
from aggregator.services.normalization import base_number


def match_shop_product(product: ShopProduct) -> ShopProduct:
    if hasattr(product, "cardmatchoverride"):
        product.canonical_card = product.cardmatchoverride.canonical_card
        product.match_status = ShopProduct.MATCH_MANUAL
        product.match_confidence = 1.0
        product.save(update_fields=["canonical_card", "match_status", "match_confidence"])
        return product

    normalized = product.card_code_normalized
    if normalized:
        exact = list(CanonicalCard.objects.filter(card_number_normalized=normalized, active=True)[:2])
        if len(exact) == 1:
            product.canonical_card = exact[0]
            product.match_status = ShopProduct.MATCH_AUTO
            product.match_confidence = 1.0
            product.save(update_fields=["canonical_card", "match_status", "match_confidence"])
            return product
        if len(exact) > 1:
            product.canonical_card = None
            product.match_status = ShopProduct.MATCH_AMBIGUOUS
            product.match_confidence = 0.0
            product.save(update_fields=["canonical_card", "match_status", "match_confidence"])
            return product

    rarity = ""
    if product.card_code_raw and "-" in product.card_code_raw:
        rarity = product.card_code_raw.rsplit("-", 1)[-1].upper()
    if normalized and rarity:
        base = base_number(product.card_code_raw)
        candidates = [c for c in CanonicalCard.objects.filter(card_number_normalized__startswith=base, rarity__iexact=rarity, active=True)[:2]]
        if len(candidates) == 1:
            product.canonical_card = candidates[0]
            product.match_status = ShopProduct.MATCH_AUTO
            product.match_confidence = 0.8
            product.save(update_fields=["canonical_card", "match_status", "match_confidence"])
            return product

    product.canonical_card = None
    product.match_status = ShopProduct.MATCH_UNMATCHED
    product.match_confidence = 0.0
    product.save(update_fields=["canonical_card", "match_status", "match_confidence"])
    return product

