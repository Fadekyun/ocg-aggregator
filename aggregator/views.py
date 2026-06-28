from django.conf import settings
from django.contrib import messages
from django.db import connection
from django.db.models import Count, Max, Min, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import CanonicalCard, CurrentOffer, OfferHistory, ScrapeRun, Shop
from .services.wanted import MODE_BALANCED, MODE_CHEAPEST, MODE_FEWEST_SHOPS, optimize_plan, parse_wanted_text


BUYABLE_OFFER_FILTER = Q(
    shopproduct__active=True,
    shopproduct__current_offer__stock_status=CurrentOffer.STOCK_AVAILABLE,
) & (
    Q(shopproduct__current_offer__stock_kind=CurrentOffer.KIND_BINARY)
    | Q(shopproduct__current_offer__stock_quantity__gt=0)
)


def shop_health(shop: Shop, now):
    if not shop.enabled:
        return "Disabled"
    if not shop.implemented:
        return "Placeholder"
    if not shop.last_success_at:
        return "Never succeeded"
    if (now - shop.last_success_at).total_seconds() > shop.stale_after_minutes * 60:
        return "Stale"
    return "Healthy"


def search(request):
    query = request.GET.get("q", "").strip()
    selected_set = request.GET.get("set", "").strip()
    selected_rarity = request.GET.get("rarity", "").strip()
    selected_shop = request.GET.get("shop", "").strip()
    buyable_only = request.GET.get("buyable") == "1"
    now = timezone.now()
    base_query = CanonicalCard.objects.filter(active=True)

    if query:
        cards = base_query.filter(
            Q(card_number_raw__icontains=query)
            | Q(name_jp__icontains=query)
            | Q(name_en__icontains=query)
            | Q(set_name__icontains=query)
            | Q(rarity__icontains=query)
        )
        limit = 50
    else:
        cards = base_query.order_by("-last_imported_at")
        limit = 20
    if selected_set:
        cards = cards.filter(set_code=selected_set)
    if selected_rarity:
        cards = cards.filter(rarity=selected_rarity)
    if selected_shop:
        cards = cards.filter(shopproduct__shop__slug=selected_shop)
    if buyable_only:
        cards = cards.filter(BUYABLE_OFFER_FILTER)

    cards = cards.annotate(
        cheapest_buyable_price=Min("shopproduct__current_offer__price_jpy", filter=BUYABLE_OFFER_FILTER),
        buyable_shop_count=Count("shopproduct__shop", filter=BUYABLE_OFFER_FILTER, distinct=True),
        known_stock=Sum("shopproduct__current_offer__stock_quantity", filter=BUYABLE_OFFER_FILTER),
        last_offer_at=Max("shopproduct__current_offer__scraped_at"),
    ).distinct()[:limit]

    enabled_shops = list(Shop.objects.filter(enabled=True, implemented=True).order_by("priority", "name"))
    stale_shops = [shop for shop in enabled_shops if shop_health(shop, now) == "Stale" or not shop.last_success_at]
    buyable_cards = CanonicalCard.objects.filter(active=True).filter(BUYABLE_OFFER_FILTER).distinct().count()
    context = {
        "query": query,
        "cards": cards,
        "selected_set": selected_set,
        "selected_rarity": selected_rarity,
        "selected_shop": selected_shop,
        "buyable_only": buyable_only,
        "sets": CanonicalCard.objects.filter(active=True).exclude(set_code="").order_by("set_code").values_list("set_code", "set_name").distinct(),
        "rarities": CanonicalCard.objects.filter(active=True).exclude(rarity="").order_by("rarity").values_list("rarity", flat=True).distinct(),
        "shops": enabled_shops,
        "stats": {
            "cards": CanonicalCard.objects.filter(active=True).count(),
            "buyable_cards": buyable_cards,
            "active_shops": len(enabled_shops),
            "stale_shops": len(stale_shops),
        },
    }
    return render(request, "aggregator/search.html", context)


def card_detail(request, card_id: int):
    card = get_object_or_404(CanonicalCard, id=card_id, active=True)
    offers = CurrentOffer.objects.select_related("shop_product__shop").filter(
        shop_product__canonical_card=card,
        shop_product__active=True,
    ).order_by("price_jpy")
    history = OfferHistory.objects.select_related("shop_product__shop").filter(
        shop_product__canonical_card=card,
    ).order_by("-observed_at")[:50]
    buyable_offers = [offer for offer in offers if offer.buyable]
    exact_stock = sum(offer.stock_quantity or 0 for offer in buyable_offers if offer.stock_kind == CurrentOffer.KIND_EXACT)
    market = {
        "cheapest": min((offer.price_jpy for offer in buyable_offers), default=None),
        "shops": len({offer.shop_product.shop_id for offer in buyable_offers}),
        "exact_stock": exact_stock,
        "last_checked": max((offer.scraped_at for offer in offers), default=None),
    }
    return render(
        request,
        "aggregator/card_detail.html",
        {"card": card, "offers": offers, "history": history, "market": market},
    )


def wanted_list(request):
    lines = []
    plan = None
    text = ""
    mode = request.POST.get("mode", MODE_CHEAPEST) if request.method == "POST" else MODE_CHEAPEST
    if request.method == "POST":
        text = request.POST.get("wanted_text", "")
        lines = parse_wanted_text(text)
        plan = optimize_plan(lines, mode)
    return render(
        request,
        "aggregator/wanted.html",
        {
            "text": text,
            "lines": lines,
            "plan": plan,
            "mode": mode,
            "modes": [
                (MODE_CHEAPEST, "Cheapest total"),
                (MODE_FEWEST_SHOPS, "Fewest shops"),
                (MODE_BALANCED, "Balanced"),
            ],
        },
    )


def status(request):
    now = timezone.now()
    shops = Shop.objects.annotate(
        product_count=Count("shopproduct", distinct=True),
        matched_count=Count("shopproduct", filter=Q(shopproduct__canonical_card__isnull=False), distinct=True),
        available_offer_count=Count(
            "shopproduct__current_offer",
            filter=Q(shopproduct__active=True, shopproduct__current_offer__stock_status=CurrentOffer.STOCK_AVAILABLE)
            & (
                Q(shopproduct__current_offer__stock_kind=CurrentOffer.KIND_BINARY)
                | Q(shopproduct__current_offer__stock_quantity__gt=0)
            ),
        ),
    )
    shop_rows = []
    for shop in shops:
        health = shop_health(shop, now)
        shop_rows.append({"shop": shop, "health": health})
    runs = ScrapeRun.objects.select_related("shop")[:30]
    return render(request, "aggregator/status.html", {"shop_rows": shop_rows, "runs": runs, "now": now})


def healthz(request):
    db_ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        db_ok = False
    enabled = Shop.objects.filter(enabled=True, implemented=True)
    stale = [shop.slug for shop in enabled if not shop.last_success_at]
    status_code = 200 if db_ok else 503
    return JsonResponse(
        {
            "ok": db_ok,
            "database": db_ok,
            "catalog_cards": CanonicalCard.objects.count(),
            "enabled_shops": list(enabled.values_list("slug", flat=True)),
            "shops_without_success": stale,
        },
        status=status_code,
    )


@csrf_exempt
def login_view(request):
    if request.method == "POST" and settings.ADMIN_PASSWORD:
        if request.POST.get("password") == settings.ADMIN_PASSWORD:
            request.session["admin_password_ok"] = True
            messages.success(request, "Logged in.")
            return redirect("search")
    return render(request, "aggregator/login.html")
