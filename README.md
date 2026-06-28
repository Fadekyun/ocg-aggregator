# OCG Aggregator

Self-hosted price and stock aggregator for Love Live! OCG singles.

The app treats your official card JSON as the canonical catalogue and Japanese shop listings as temporary offers. It is designed for private use on a Pi, home server, VPS, or Tailscale-only host.

## Current MVP

- Django + HTMX UI.
- PostgreSQL database.
- Docker Compose deployment.
- Read-only `cards.json` import compatible with `ahuei123456/lltcg-prototype`.
- Scheduled scraper worker inside the app container, no host cron required.
- MVP shop adapters:
  - Dragon Star
  - Card Labo
  - Manzokuya
  - 193net
- Disabled placeholders for future adapters:
  - Hobby Station
  - Toreca Plaza 55
  - Cardshop Serra
  - REALiZE
  - TCG Republic

## Quick start

```bash
git clone https://github.com/Fadekyun/ocg-aggregator.git
cd ocg-aggregator
cp .env.example .env
mkdir -p catalog data logs
cp /path/to/cards.json catalog/cards.json
docker compose up --build -d
```

Open:

```text
http://127.0.0.1:8788
```

The default compose file binds only to localhost. Use an SSH tunnel, Tailscale, or a reverse proxy if you need remote access.

## LAN access

For LAN exposure, set `ADMIN_PASSWORD` in `.env`, add your host/IP to `DJANGO_ALLOWED_HOSTS`, then run:

```bash
docker compose -f compose.yaml -f compose.lan.yaml up -d
```

Do not expose this publicly without a real reverse proxy, HTTPS, and access controls.

## Catalogue JSON

The importer expects the JSON shape produced by `lltcg-prototype`:

```json
{
  "BP05": [
    {
      "card_number": "PL!N-bp5-007-N",
      "name": "...",
      "img_url": "...",
      "set": "...",
      "rarity": "N"
    }
  ]
}
```

Import manually:

```bash
docker compose exec app python manage.py import_catalog
```

The import is idempotent. Missing JSON does not delete existing cards.

## Scraping

The scheduler runs inside the app container:

```text
gunicorn                         web UI
python manage.py scheduler       scrape scheduler
```

Each enabled shop is checked roughly every six hours. The UI uses the latest successful scrape and does not trigger live shop requests when opened.

Manual commands:

```bash
docker compose exec app python manage.py scrape_shop dragon_star
docker compose exec app python manage.py scrape_all
```

The scraper publishes transactionally. Failed or suspicious runs keep the last successful offers and mark the shop stale.

## Wanted-list optimizer

The wanted-list page uses OR-Tools CP-SAT and supports three modes:

- Cheapest total: minimize item cost plus estimated shipping.
- Fewest shops: strongly prefer fewer stores while still fulfilling cards where possible.
- Balanced: include a modest per-shop penalty so a tiny item-price saving does not add a whole extra store too easily.

Exact stock and purchase limits are hard constraints. Binary stock can be selected, but the plan shows a warning because the exact quantity is unknown.

## Health

```bash
curl http://127.0.0.1:8788/healthz
```

The response includes database status, imported card count, enabled shops, and shops without successful scrapes.

## Security

- No secrets are committed.
- `.env.example` is a template only.
- Default bind address is `127.0.0.1`.
- LAN exposure requires an explicit compose override.
- Shop passwords and checkout automation are intentionally out of scope.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_shops
pytest
```
