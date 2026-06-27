from django.contrib import admin

from .models import CanonicalCard, CardMatchOverride, CurrentOffer, OfferHistory, ScrapeRun, Shop, ShopProduct


@admin.register(CanonicalCard)
class CanonicalCardAdmin(admin.ModelAdmin):
    list_display = ("card_number_raw", "name_jp", "set_code", "rarity", "active")
    search_fields = ("card_number_raw", "card_number_normalized", "name_jp", "set_name")
    list_filter = ("active", "set_code", "rarity")


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "enabled", "implemented", "last_success_at", "last_failure_at")
    list_filter = ("enabled", "implemented")


@admin.register(ShopProduct)
class ShopProductAdmin(admin.ModelAdmin):
    list_display = ("shop", "shop_product_key", "card_code_raw", "match_status", "canonical_card", "active")
    search_fields = ("shop_product_key", "title_raw", "card_code_raw", "card_code_normalized")
    list_filter = ("shop", "match_status", "active")


admin.site.register(CurrentOffer)
admin.site.register(OfferHistory)
admin.site.register(ScrapeRun)
admin.site.register(CardMatchOverride)

