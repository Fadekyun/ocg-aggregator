from django.conf import settings
from django.contrib import messages
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import CanonicalCard, CurrentOffer, ScrapeRun, Shop
from .services.wanted import parse_wanted_text, simple_plan


def search(request):
    query = request.GET.get("q", "").strip()
    cards = CanonicalCard.objects.none()
    if query:
        cards = CanonicalCard.objects.filter(active=True).filter(
            card_number_raw__icontains=query
        ) | CanonicalCard.objects.filter(active=True, name_jp__icontains=query) | CanonicalCard.objects.filter(active=True, set_name__icontains=query)
        cards = cards.distinct()[:50]
    else:
        cards = CanonicalCard.objects.filter(active=True).order_by("-last_imported_at")[:20]
    return render(request, "aggregator/search.html", {"query": query, "cards": cards})


def card_detail(request, card_id: int):
    card = get_object_or_404(CanonicalCard, id=card_id, active=True)
    offers = CurrentOffer.objects.select_related("shop_product__shop").filter(
        shop_product__canonical_card=card,
        shop_product__active=True,
    ).order_by("price_jpy")
    return render(request, "aggregator/card_detail.html", {"card": card, "offers": offers})


def wanted_list(request):
    lines = []
    plan = None
    text = ""
    if request.method == "POST":
        text = request.POST.get("wanted_text", "")
        lines = parse_wanted_text(text)
        plan = simple_plan(lines)
    return render(request, "aggregator/wanted.html", {"text": text, "lines": lines, "plan": plan})


def status(request):
    shops = Shop.objects.all()
    runs = ScrapeRun.objects.select_related("shop")[:30]
    return render(request, "aggregator/status.html", {"shops": shops, "runs": runs, "now": timezone.now()})


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

