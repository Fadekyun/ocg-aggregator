#!/bin/sh
set -eu

mkdir -p /app/logs /app/data
python /app/scripts/ensure_database.py
python manage.py migrate --noinput
python manage.py seed_shops
if [ -f "${CARD_CATALOG_PATH:-/catalog/cards.json}" ]; then
  python manage.py import_catalog --path "${CARD_CATALOG_PATH:-/catalog/cards.json}" || true
fi
python manage.py collectstatic --noinput >/dev/null
exec "$@"
