import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from django.utils import timezone

from aggregator.models import CanonicalCard
from aggregator.services.normalization import normalize_card_number


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    duplicates: list[str] | None = None


def payload_hash(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def import_catalog(path: str | Path) -> ImportResult:
    catalog_path = Path(path)
    if not catalog_path.exists():
        raise FileNotFoundError(f"Catalogue file not found: {catalog_path}")
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Catalogue JSON must be an object keyed by expansion code")

    result = ImportResult(duplicates=[])
    seen_normalized: dict[str, str] = {}
    now = timezone.now()

    for expansion, cards in data.items():
        if not isinstance(cards, list):
            continue
        for card in cards:
            if not isinstance(card, dict):
                continue
            card_number = str(card.get("card_number", "")).strip()
            if not card_number:
                continue
            normalized = normalize_card_number(card_number)
            source_catalog_id = card_number
            digest = payload_hash(card)
            existing_seen = seen_normalized.get(normalized)
            if existing_seen and existing_seen != f"{expansion}:{source_catalog_id}":
                result.duplicates.append(normalized)
            seen_normalized[normalized] = f"{expansion}:{source_catalog_id}"

            defaults = {
                "card_number_raw": card_number,
                "card_number_normalized": normalized,
                "name_jp": str(card.get("name", "")),
                "name_en": str(card.get("name_en", "")),
                "rarity": str(card.get("rarity", "")),
                "set_code": str(expansion),
                "set_name": str(card.get("set", "")),
                "image_url": str(card.get("img_url", "")),
                "catalog_payload_json": card,
                "catalog_hash": digest,
                "active": True,
                "last_imported_at": now,
            }
            previous = CanonicalCard.objects.filter(source_expansion=str(expansion), source_catalog_id=source_catalog_id).first()
            obj, created = CanonicalCard.objects.update_or_create(source_expansion=str(expansion), source_catalog_id=source_catalog_id, defaults=defaults)
            if created:
                result.created += 1
            elif previous and previous.catalog_hash == digest:
                result.unchanged += 1
            else:
                result.updated += 1

    return result
