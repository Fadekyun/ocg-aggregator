from urllib.parse import urlparse
import os
import time

import psycopg
from psycopg import sql


def main():
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith(("postgres://", "postgresql://")):
        return

    parsed = urlparse(url)
    target_db = parsed.path.lstrip("/")
    if not target_db:
        return

    conninfo = {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": parsed.username,
        "password": parsed.password,
        "dbname": "postgres",
        "autocommit": True,
    }
    last_error = None
    for _ in range(60):
        try:
            with psycopg.connect(**conninfo) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
                    if cursor.fetchone():
                        return
                    cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
                    return
        except psycopg.OperationalError as exc:
            last_error = exc
            time.sleep(1)
    raise SystemExit(f"database not ready: {last_error}")


if __name__ == "__main__":
    main()
