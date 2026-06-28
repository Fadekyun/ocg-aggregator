import json
from pathlib import Path

import pytest

from aggregator.adapters.base import AdapterRunResult, generic_product_blocks, parse_purchase_limit
from aggregator.adapters.shops import CardLaboAdapter, DragonStarAdapter, ManzokuyaAdapter, Net193Adapter
from aggregator.models import CanonicalCard, CurrentOffer, OfferHistory, Shop, ShopProduct
from aggregator.services.catalog import import_catalog
from aggregator.services.normalization import normalize_card_number
from aggregator.services.scraping import due_shops
from aggregator.services.wanted import MODE_FEWEST_SHOPS, optimize_plan, parse_wanted_text, simple_plan
from django.utils import timezone


FIXTURES = Path(__file__).parent / "fixtures" / "shops"


@pytest.mark.django_db
def test_catalog_import_idempotent(tmp_path):
    path = tmp_path / "cards.json"
    payload = {
        "BP05": [
            {
                "card_number": "PL!N-bp5-007-N",
                "name": "テスト",
                "img_url": "https://example.com/card.png",
                "set": "Anniversary 2026",
                "rarity": "N",
            }
        ]
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    first = import_catalog(path)
    second = import_catalog(path)

    assert first.created == 1
    assert second.created == 0
    assert second.unchanged == 1


def test_card_number_normalization():
    assert normalize_card_number("PL！HS-bp5-019-L") == "PLHSBP5019L"
    assert normalize_card_number("PL!HS-bp5-019-L") == "PLHSBP5019L"
    assert normalize_card_number("PLHSBP5019L") == "PLHSBP5019L"


def test_generic_parser_exact_stock():
    html = """
    <div class="product" data-product-id="abc">
      <a href="/p/abc">PL!N-bp5-007-N テスト</a>
      <span>￥120</span><span>在庫: 5</span>
    </div>
    """
    offers = generic_product_blocks(html, "https://shop.example/list", "https://shop.example")
    assert len(offers) == 1
    assert offers[0].price_jpy == 120
    assert offers[0].stock_kind == CurrentOffer.KIND_EXACT
    assert offers[0].stock_quantity == 5


def test_generic_parser_binary_stock():
    html = """
    <li><a href="/p/1">PL!S-bp4-012-R</a> ￥80 在庫: ◯ カートに入れる</li>
    """
    offers = generic_product_blocks(html, "https://shop.example/list", "https://shop.example")
    assert offers[0].stock_kind == CurrentOffer.KIND_BINARY
    assert offers[0].stock_quantity is None


def test_purchase_limit_parses_without_becoming_stock():
    html = (FIXTURES / "card_labo_exact_limit.html").read_text(encoding="utf-8")
    offers = generic_product_blocks(
        html,
        "https://www.c-labo-online.jp/product-list/2995/0/photo",
        "https://www.c-labo-online.jp",
    )

    assert len(offers) == 1
    assert offers[0].stock_kind == CurrentOffer.KIND_EXACT
    assert offers[0].stock_quantity == 17
    assert offers[0].purchase_limit == 4
    assert parse_purchase_limit("購入制限：４枚") == 4


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("adapter_cls", "shop_slug", "fixture_name", "source_url", "expected"),
    [
        (
            DragonStarAdapter,
            "dragon_star",
            "dragon_star_exact.html",
            "https://dorasuta.jp/llofficial-cardgame",
            {
                "code": "PL！HS-bp5-019-L",
                "normalized": "PLHSBP5019L",
                "price": 1200,
                "status": CurrentOffer.STOCK_AVAILABLE,
                "kind": CurrentOffer.KIND_EXACT,
                "quantity": 5,
                "condition": "状態A",
                "limit": None,
            },
        ),
        (
            CardLaboAdapter,
            "card_labo",
            "card_labo_exact_limit.html",
            "https://www.c-labo-online.jp/product-list/2995/0/photo",
            {
                "code": "PL!N-sd1-008-RM",
                "normalized": "PLNSD1008RM",
                "price": 280,
                "status": CurrentOffer.STOCK_AVAILABLE,
                "kind": CurrentOffer.KIND_EXACT,
                "quantity": 17,
                "condition": "",
                "limit": 4,
            },
        ),
        (
            ManzokuyaAdapter,
            "manzokuya",
            "manzokuya_binary.html",
            "https://shopmanzokuya.com/products/list?category_id=3184",
            {
                "code": "PL!S-bp4-012-R",
                "normalized": "PLSBP4012R",
                "price": 80,
                "status": CurrentOffer.STOCK_AVAILABLE,
                "kind": CurrentOffer.KIND_BINARY,
                "quantity": None,
                "condition": "",
                "limit": None,
            },
        ),
        (
            Net193Adapter,
            "193net",
            "net193_soldout.html",
            "https://193tcg.com/products/list?category_id=2415",
            {
                "code": "LL-bp1-001-R＋",
                "normalized": "LLBP1001R+",
                "price": 480,
                "status": CurrentOffer.STOCK_SOLD_OUT,
                "kind": CurrentOffer.KIND_EXACT,
                "quantity": 0,
                "condition": "",
                "limit": None,
            },
        ),
    ],
)
def test_shop_adapters_parse_fixture_offers(adapter_cls, shop_slug, fixture_name, source_url, expected):
    shop = Shop.objects.create(slug=shop_slug, name=shop_slug, base_domain="example.com")
    adapter = adapter_cls(shop)
    try:
        html = (FIXTURES / fixture_name).read_text(encoding="utf-8")
        offers = adapter.parse_listing(html, source_url)
    finally:
        adapter.close()

    assert len(offers) == 1
    offer = offers[0]
    assert offer.card_code_raw == expected["code"]
    assert offer.card_code_normalized == expected["normalized"]
    assert offer.price_jpy == expected["price"]
    assert offer.stock_status == expected["status"]
    assert offer.stock_kind == expected["kind"]
    assert offer.stock_quantity == expected["quantity"]
    assert offer.condition_raw == expected["condition"]
    assert offer.purchase_limit == expected["limit"]
    assert offer.product_url.startswith("https://")


@pytest.mark.django_db
def test_adapter_validation_rejects_all_sold_out_collapse():
    shop = Shop.objects.create(slug="193net", name="193net", base_domain="193tcg.com")
    adapter = Net193Adapter(shop)
    try:
        html = (FIXTURES / "net193_soldout.html").read_text(encoding="utf-8")
        offer = adapter.parse_listing(html, "https://193tcg.com/products/list?category_id=2415")[0]
        valid, reason = adapter.validate_run(AdapterRunResult(offers=[offer] * 20))
    finally:
        adapter.close()

    assert not valid
    assert reason == "Every parsed product is sold out"


@pytest.mark.django_db
def test_wanted_list_parses_and_merges(tmp_path):
    path = tmp_path / "cards.json"
    path.write_text(json.dumps({"BP05": [{"card_number": "PL!N-bp5-007-N", "name": "テスト", "rarity": "N"}]}), encoding="utf-8")
    import_catalog(path)

    lines = parse_wanted_text("PL!N-bp5-007-N x2\nPL!N-bp5-007-N,3,200")

    assert len(lines) == 2
    assert sum(line.quantity for line in lines) == 5
    assert all(line.card for line in lines)


@pytest.mark.django_db
def test_simple_plan_uses_exact_stock(tmp_path):
    path = tmp_path / "cards.json"
    path.write_text(json.dumps({"BP05": [{"card_number": "PL!N-bp5-007-N", "name": "テスト", "rarity": "N"}]}), encoding="utf-8")
    import_catalog(path)
    card = CanonicalCard.objects.get()
    shop = Shop.objects.create(slug="shop", name="Shop", base_domain="example.com", shipping_base_jpy=250)
    product = ShopProduct.objects.create(
        shop=shop,
        shop_product_key="1",
        product_url="https://example.com/1",
        card_code_raw=card.card_number_raw,
        card_code_normalized=card.card_number_normalized,
        canonical_card=card,
        match_status="auto",
    )
    CurrentOffer.objects.create(
        shop_product=product,
        price_jpy=100,
        stock_status=CurrentOffer.STOCK_AVAILABLE,
        stock_kind=CurrentOffer.KIND_EXACT,
        stock_quantity=2,
    )

    lines = parse_wanted_text("PL!N-bp5-007-N x3")
    plan = simple_plan(lines)

    assert plan["grand_total"] == 450
    assert plan["unfulfilled"][0].quantity == 1


def create_offer(card, shop, key, price, stock=10):
    product = ShopProduct.objects.create(
        shop=shop,
        shop_product_key=key,
        product_url=f"https://example.com/{key}",
        card_code_raw=card.card_number_raw,
        card_code_normalized=card.card_number_normalized,
        canonical_card=card,
        match_status="auto",
    )
    return CurrentOffer.objects.create(
        shop_product=product,
        price_jpy=price,
        stock_status=CurrentOffer.STOCK_AVAILABLE,
        stock_kind=CurrentOffer.KIND_EXACT,
        stock_quantity=stock,
    )


@pytest.mark.django_db
def test_optimizer_includes_shipping_when_selecting_shop(tmp_path):
    path = tmp_path / "cards.json"
    path.write_text(
        json.dumps(
            {
                "BP05": [
                    {"card_number": "PL!N-bp5-001-N", "name": "Card 1", "rarity": "N"},
                    {"card_number": "PL!N-bp5-002-N", "name": "Card 2", "rarity": "N"},
                ]
            }
        ),
        encoding="utf-8",
    )
    import_catalog(path)
    card1 = CanonicalCard.objects.get(card_number_raw="PL!N-bp5-001-N")
    card2 = CanonicalCard.objects.get(card_number_raw="PL!N-bp5-002-N")
    shop_a = Shop.objects.create(slug="a", name="A", base_domain="a.example", shipping_base_jpy=250)
    shop_b = Shop.objects.create(slug="b", name="B", base_domain="b.example", shipping_base_jpy=250)
    create_offer(card1, shop_a, "a-1", 80)
    create_offer(card1, shop_b, "b-1", 100)
    create_offer(card2, shop_b, "b-2", 100)

    plan = optimize_plan(parse_wanted_text("PL!N-bp5-001-N x1\nPL!N-bp5-002-N x1"))

    assert plan["grand_total"] == 450
    assert [group["shop"].slug for group in plan["groups"]] == ["b"]


@pytest.mark.django_db
def test_fewest_shops_mode_can_prefer_one_store(tmp_path):
    path = tmp_path / "cards.json"
    path.write_text(
        json.dumps(
            {
                "BP05": [
                    {"card_number": "PL!N-bp5-001-N", "name": "Card 1", "rarity": "N"},
                    {"card_number": "PL!N-bp5-002-N", "name": "Card 2", "rarity": "N"},
                ]
            }
        ),
        encoding="utf-8",
    )
    import_catalog(path)
    card1 = CanonicalCard.objects.get(card_number_raw="PL!N-bp5-001-N")
    card2 = CanonicalCard.objects.get(card_number_raw="PL!N-bp5-002-N")
    shop_a = Shop.objects.create(slug="a", name="A", base_domain="a.example")
    shop_b = Shop.objects.create(slug="b", name="B", base_domain="b.example")
    create_offer(card1, shop_a, "a-1", 50)
    create_offer(card1, shop_b, "b-1", 100)
    create_offer(card2, shop_b, "b-2", 100)
    lines = parse_wanted_text("PL!N-bp5-001-N x1\nPL!N-bp5-002-N x1")

    cheapest = optimize_plan(lines)
    fewest = optimize_plan(lines, MODE_FEWEST_SHOPS)

    assert cheapest["grand_total"] == 150
    assert {group["shop"].slug for group in cheapest["groups"]} == {"a", "b"}
    assert fewest["grand_total"] == 200
    assert [group["shop"].slug for group in fewest["groups"]] == ["b"]


@pytest.mark.django_db
def test_search_shows_current_buyable_offer_summary(client, tmp_path):
    path = tmp_path / "cards.json"
    path.write_text(
        json.dumps({"BP05": [{"card_number": "PL!N-bp5-007-N", "name": "テスト", "rarity": "N"}]}),
        encoding="utf-8",
    )
    import_catalog(path)
    card = CanonicalCard.objects.get()
    shop = Shop.objects.create(slug="shop", name="Shop", base_domain="example.com")
    create_offer(card, shop, "shop-1", 120, stock=3)

    response = client.get("/", {"q": "bp5-007"})

    assert response.status_code == 200
    assert "from ¥120 at 1 shop" in response.content.decode()


@pytest.mark.django_db
def test_card_detail_shows_offer_history(client, tmp_path):
    path = tmp_path / "cards.json"
    path.write_text(
        json.dumps({"BP05": [{"card_number": "PL!N-bp5-007-N", "name": "テスト", "rarity": "N"}]}),
        encoding="utf-8",
    )
    import_catalog(path)
    card = CanonicalCard.objects.get()
    shop = Shop.objects.create(slug="shop", name="Shop", base_domain="example.com")
    offer = create_offer(card, shop, "shop-1", 120, stock=3)
    OfferHistory.objects.create(
        shop_product=offer.shop_product,
        price_jpy=120,
        stock_quantity=3,
        stock_status=CurrentOffer.STOCK_AVAILABLE,
        stock_kind=CurrentOffer.KIND_EXACT,
    )

    response = client.get(f"/cards/{card.id}/")

    assert response.status_code == 200
    body = response.content.decode()
    assert "Recent price history" in body
    assert "¥120" in body


@pytest.mark.django_db
def test_due_shops_respects_recent_failure_backoff():
    shop = Shop.objects.create(
        slug="blocked",
        name="Blocked",
        base_domain="example.com",
        enabled=True,
        implemented=True,
        scrape_interval_minutes=360,
        last_failure_at=timezone.now(),
    )

    assert shop not in list(due_shops())
