from django.db import models
from django.utils import timezone


class CanonicalCard(models.Model):
    source_expansion = models.CharField(max_length=64)
    source_catalog_id = models.CharField(max_length=160)
    card_number_raw = models.CharField(max_length=160)
    card_number_normalized = models.CharField(max_length=160, db_index=True)
    name_jp = models.CharField(max_length=255, blank=True)
    name_en = models.CharField(max_length=255, blank=True)
    rarity = models.CharField(max_length=64, blank=True)
    set_code = models.CharField(max_length=64, blank=True)
    set_name = models.CharField(max_length=255, blank=True)
    image_url = models.URLField(blank=True)
    catalog_payload_json = models.JSONField(default=dict)
    catalog_hash = models.CharField(max_length=64)
    active = models.BooleanField(default=True)
    last_imported_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source_expansion", "source_catalog_id"], name="uniq_catalog_source_card")
        ]
        indexes = [
            models.Index(fields=["card_number_normalized", "rarity"]),
            models.Index(fields=["set_code", "rarity"]),
        ]

    def __str__(self):
        return f"{self.card_number_raw} {self.name_jp}".strip()


class Shop(models.Model):
    SHIPPING_FLAT = "flat"
    SHIPPING_FREE_THRESHOLD = "free_threshold"
    SHIPPING_RULES = [(SHIPPING_FLAT, "Flat"), (SHIPPING_FREE_THRESHOLD, "Free threshold")]

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    base_domain = models.CharField(max_length=160)
    enabled = models.BooleanField(default=False)
    implemented = models.BooleanField(default=False)
    priority = models.PositiveIntegerField(default=100)
    supports_exact_stock = models.BooleanField(default=False)
    scrape_interval_minutes = models.PositiveIntegerField(default=360)
    schedule_offset_minutes = models.PositiveIntegerField(default=0)
    minimum_request_delay_ms = models.PositiveIntegerField(default=1500)
    shipping_rule_type = models.CharField(max_length=32, choices=SHIPPING_RULES, default=SHIPPING_FLAT)
    shipping_base_jpy = models.PositiveIntegerField(default=0)
    free_shipping_threshold_jpy = models.PositiveIntegerField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    stale_after_minutes = models.PositiveIntegerField(default=720)

    class Meta:
        ordering = ["priority", "name"]

    def __str__(self):
        return self.name

    def estimate_shipping(self, items_total: int) -> int:
        if self.shipping_rule_type == self.SHIPPING_FREE_THRESHOLD and self.free_shipping_threshold_jpy:
            if items_total >= self.free_shipping_threshold_jpy:
                return 0
        return self.shipping_base_jpy


class ShopProduct(models.Model):
    MATCH_UNMATCHED = "unmatched"
    MATCH_AUTO = "auto"
    MATCH_MANUAL = "manual"
    MATCH_AMBIGUOUS = "ambiguous"
    MATCH_STATUS = [
        (MATCH_UNMATCHED, "Unmatched"),
        (MATCH_AUTO, "Auto"),
        (MATCH_MANUAL, "Manual"),
        (MATCH_AMBIGUOUS, "Ambiguous"),
    ]

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE)
    shop_product_key = models.CharField(max_length=200)
    product_url = models.URLField()
    title_raw = models.TextField(blank=True)
    card_code_raw = models.CharField(max_length=160, blank=True)
    card_code_normalized = models.CharField(max_length=160, blank=True, db_index=True)
    condition_raw = models.CharField(max_length=160, blank=True)
    condition_normalized = models.CharField(max_length=80, blank=True)
    canonical_card = models.ForeignKey(CanonicalCard, null=True, blank=True, on_delete=models.SET_NULL)
    match_status = models.CharField(max_length=24, choices=MATCH_STATUS, default=MATCH_UNMATCHED)
    match_confidence = models.FloatField(default=0)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["shop", "shop_product_key"], name="uniq_shop_product")]
        indexes = [models.Index(fields=["shop", "active", "match_status"])]

    def __str__(self):
        return f"{self.shop.slug}:{self.shop_product_key}"


class CurrentOffer(models.Model):
    STOCK_AVAILABLE = "available"
    STOCK_SOLD_OUT = "sold_out"
    STOCK_UNKNOWN = "unknown"
    STOCK_STATUSES = [(STOCK_AVAILABLE, "Available"), (STOCK_SOLD_OUT, "Sold out"), (STOCK_UNKNOWN, "Unknown")]
    KIND_EXACT = "exact"
    KIND_BINARY = "binary"
    KIND_UNKNOWN = "unknown"
    STOCK_KINDS = [(KIND_EXACT, "Exact"), (KIND_BINARY, "Binary"), (KIND_UNKNOWN, "Unknown")]

    shop_product = models.OneToOneField(ShopProduct, on_delete=models.CASCADE, related_name="current_offer")
    price_jpy = models.PositiveIntegerField()
    stock_quantity = models.IntegerField(null=True, blank=True)
    stock_status = models.CharField(max_length=24, choices=STOCK_STATUSES)
    stock_kind = models.CharField(max_length=24, choices=STOCK_KINDS)
    purchase_limit = models.PositiveIntegerField(null=True, blank=True)
    scraped_at = models.DateTimeField(default=timezone.now)
    source_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["stock_status", "price_jpy"])]

    @property
    def buyable(self) -> bool:
        if self.stock_status != self.STOCK_AVAILABLE:
            return False
        if self.stock_kind == self.KIND_EXACT:
            return (self.stock_quantity or 0) > 0
        return True


class OfferHistory(models.Model):
    shop_product = models.ForeignKey(ShopProduct, on_delete=models.CASCADE)
    price_jpy = models.PositiveIntegerField()
    stock_quantity = models.IntegerField(null=True, blank=True)
    stock_status = models.CharField(max_length=24)
    stock_kind = models.CharField(max_length=24)
    observed_at = models.DateTimeField(default=timezone.now)
    scrape_run = models.ForeignKey("ScrapeRun", null=True, blank=True, on_delete=models.SET_NULL)


class ScrapeRun(models.Model):
    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"
    STATUSES = [(STATUS_RUNNING, "Running"), (STATUS_SUCCESS, "Success"), (STATUS_FAILED, "Failed"), (STATUS_SKIPPED, "Skipped")]

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE)
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=24, choices=STATUSES, default=STATUS_RUNNING)
    pages_requested = models.PositiveIntegerField(default=0)
    products_seen = models.PositiveIntegerField(default=0)
    products_updated = models.PositiveIntegerField(default=0)
    products_unmatched = models.PositiveIntegerField(default=0)
    parse_errors = models.PositiveIntegerField(default=0)
    http_errors = models.PositiveIntegerField(default=0)
    error_summary = models.TextField(blank=True)
    parser_version = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["-started_at"]


class CardMatchOverride(models.Model):
    shop_product = models.OneToOneField(ShopProduct, on_delete=models.CASCADE)
    canonical_card = models.ForeignKey(CanonicalCard, on_delete=models.CASCADE)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

