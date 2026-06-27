from django.db import transaction
from django.utils import timezone

from aggregator.adapters.shops import ADAPTERS
from aggregator.models import CurrentOffer, OfferHistory, ScrapeRun, Shop, ShopProduct
from aggregator.services.matching import match_shop_product


def run_shop_scrape(shop: Shop) -> ScrapeRun:
    run = ScrapeRun.objects.create(shop=shop, parser_version="unknown")
    adapter_cls = ADAPTERS.get(shop.slug)
    if not adapter_cls:
        run.status = ScrapeRun.STATUS_SKIPPED
        run.error_summary = "No adapter implemented for shop"
        run.completed_at = timezone.now()
        run.save()
        return run

    adapter = adapter_cls(shop)
    run.parser_version = adapter.parser_version
    try:
        result = adapter.discover_products()
        valid, reason = adapter.validate_run(result)
        run.pages_requested = result.pages_requested
        run.products_seen = len(result.offers)
        run.parse_errors = result.parse_errors
        run.http_errors = result.http_errors
        if not valid:
            run.status = ScrapeRun.STATUS_FAILED
            run.error_summary = reason or "; ".join(result.errors[:5])
            shop.last_failure_at = timezone.now()
            shop.save(update_fields=["last_failure_at"])
            return run

        with transaction.atomic():
            for offer in result.offers:
                product, _ = ShopProduct.objects.update_or_create(
                    shop=shop,
                    shop_product_key=offer.shop_product_key,
                    defaults={
                        "product_url": offer.product_url,
                        "title_raw": offer.title_raw,
                        "card_code_raw": offer.card_code_raw,
                        "card_code_normalized": offer.card_code_normalized,
                        "condition_raw": offer.condition_raw,
                        "condition_normalized": offer.condition_raw.lower(),
                        "last_seen_at": timezone.now(),
                        "active": True,
                        "notes": offer.notes,
                    },
                )
                match_shop_product(product)
                current, _ = CurrentOffer.objects.update_or_create(
                    shop_product=product,
                    defaults={
                        "price_jpy": offer.price_jpy,
                        "stock_quantity": offer.stock_quantity,
                        "stock_status": offer.stock_status,
                        "stock_kind": offer.stock_kind,
                        "purchase_limit": offer.purchase_limit,
                        "scraped_at": timezone.now(),
                    },
                )
                OfferHistory.objects.create(
                    shop_product=product,
                    price_jpy=current.price_jpy,
                    stock_quantity=current.stock_quantity,
                    stock_status=current.stock_status,
                    stock_kind=current.stock_kind,
                    scrape_run=run,
                )
                run.products_updated += 1
                if not product.canonical_card_id:
                    run.products_unmatched += 1

        run.status = ScrapeRun.STATUS_SUCCESS
        shop.last_success_at = timezone.now()
        shop.save(update_fields=["last_success_at"])
        return run
    except Exception as exc:
        run.status = ScrapeRun.STATUS_FAILED
        run.error_summary = str(exc)
        shop.last_failure_at = timezone.now()
        shop.save(update_fields=["last_failure_at"])
        return run
    finally:
        adapter.close()
        run.completed_at = timezone.now()
        run.save()


def due_shops(now=None):
    now = now or timezone.now()
    shops = Shop.objects.filter(enabled=True, implemented=True).order_by("priority")
    for shop in shops:
        last_attempt = shop.last_success_at or shop.last_failure_at
        if not last_attempt:
            yield shop
            continue
        elapsed = (now - last_attempt).total_seconds() / 60
        if elapsed >= shop.scrape_interval_minutes:
            yield shop
