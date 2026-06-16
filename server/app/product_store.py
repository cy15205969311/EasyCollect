import json
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


BASE_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE_DIR / "static" / "cache_data"
DB_PATH = CACHE_DIR / "products.sqlite3"


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def connect() -> sqlite3.Connection:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_product_db() -> None:
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                title TEXT NOT NULL,
                base_price TEXT,
                cover_image TEXT,
                dedupe_key TEXT,
                data_json TEXT NOT NULL,
                raw_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_products_updated_at ON products(updated_at DESC)"
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(products)").fetchall()
        }
        if "dedupe_key" not in columns:
            connection.execute("ALTER TABLE products ADD COLUMN dedupe_key TEXT")
    backfill_dedupe_keys()
    with connect() as connection:
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_products_dedupe_key ON products(dedupe_key)"
        )


def normalize_platform_label(platform: str | None) -> str:
    if not platform:
        return "Unknown"

    lowered = platform.lower()
    if "shopee" in lowered:
        return "Shopee"
    if "1688" in lowered:
        return "1688"
    return platform


def product_title(product: dict[str, Any]) -> str:
    for key in ["title_optimized", "title", "source_title"]:
        value = product.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Untitled Product"


def product_cover(product: dict[str, Any]) -> str:
    images = product.get("main_images")
    if isinstance(images, list):
        for image in images:
            if isinstance(image, str) and image.strip():
                return image.strip()
    return ""


def normalize_product_url(url: str | None) -> str:
    if not url:
        return ""

    parsed = urlparse(url.strip())
    if not parsed.netloc:
        return url.strip()

    path = parsed.path.rstrip("/")
    shopee_match = re.search(r"(?:^|-)i\.(\d+)\.(\d+)(?:$|[/?#])", path)
    if shopee_match:
        return f"{parsed.netloc.lower()}/i.{shopee_match.group(1)}.{shopee_match.group(2)}"

    query = parse_qs(parsed.query)
    stable_query = []
    for key in ["itemid", "item_id", "shopid", "shop_id", "offerId", "offerid"]:
        value = query.get(key)
        if value:
            stable_query.append(f"{key}={value[0]}")

    return f"{parsed.netloc.lower()}{path}" + (
        f"?{'&'.join(stable_query)}" if stable_query else ""
    )


def build_dedupe_key(product: dict[str, Any], platform: str, source_url: str | None = None) -> str:
    platform_label = normalize_platform_label(platform).lower()
    source_url = source_url or str(product.get("source_url") or product.get("url") or "")
    normalized_url = normalize_product_url(source_url)
    if normalized_url:
        return f"{platform_label}:url:{normalized_url}"

    title = product_title(product).strip().lower()
    cover = product_cover(product).strip().lower()
    if title or cover:
        return f"{platform_label}:fingerprint:{title}|{cover}"

    return f"{platform_label}:unknown:{uuid.uuid4().hex}"


def backfill_dedupe_keys() -> None:
    with connect() as connection:
        rows = connection.execute("SELECT * FROM products ORDER BY updated_at DESC").fetchall()
        seen: set[str] = set()
        for row in rows:
            product = row_to_product(row)
            dedupe_key = row["dedupe_key"] or build_dedupe_key(
                product,
                row["platform"],
                product.get("source_url"),
            )
            if dedupe_key in seen:
                connection.execute("DELETE FROM products WHERE id = ?", (row["id"],))
                continue

            seen.add(dedupe_key)
            connection.execute(
                "UPDATE products SET dedupe_key = ? WHERE id = ?",
                (dedupe_key, row["id"]),
            )


def row_to_product(row: sqlite3.Row) -> dict[str, Any]:
    product = json.loads(row["data_json"])
    if not isinstance(product, dict):
        product = {}

    product["id"] = row["id"]
    product["platform"] = row["platform"]
    product["title"] = product.get("title") or row["title"]
    product["base_price"] = product.get("base_price") or row["base_price"] or ""
    product["created_at"] = row["created_at"]
    product["updated_at"] = row["updated_at"]
    return product


def save_product(
    product: dict[str, Any],
    raw: Any,
    platform: str,
    product_id: str | None = None,
    source_url: str | None = None,
) -> str:
    init_product_db()

    now = utc_now()
    platform_label = normalize_platform_label(platform)
    product_for_storage = dict(product)
    product_for_storage["platform"] = platform_label
    product_for_storage["source_url"] = source_url or product_for_storage.get("source_url") or ""
    dedupe_key = build_dedupe_key(product_for_storage, platform_label, source_url)

    with connect() as connection:
        existing = connection.execute(
            "SELECT id, created_at FROM products WHERE dedupe_key = ?",
            (dedupe_key,),
        ).fetchone()

    new_product_id = product_id or (existing["id"] if existing else f"prd_{uuid.uuid4().hex[:16]}")
    created_at = existing["created_at"] if existing else now
    product_for_storage["id"] = new_product_id
    product_for_storage["updated_at"] = now
    product_for_storage["created_at"] = product_for_storage.get("created_at") or created_at
    product_for_storage["dedupe_key"] = dedupe_key

    with connect() as connection:
        connection.execute(
            """
            INSERT INTO products (
                id, platform, title, base_price, cover_image, dedupe_key,
                data_json, raw_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dedupe_key) DO UPDATE SET
                platform = excluded.platform,
                title = excluded.title,
                base_price = excluded.base_price,
                cover_image = excluded.cover_image,
                data_json = excluded.data_json,
                raw_json = excluded.raw_json,
                updated_at = excluded.updated_at
            """,
            (
                new_product_id,
                platform_label,
                product_title(product_for_storage),
                str(product_for_storage.get("base_price") or ""),
                product_cover(product_for_storage),
                dedupe_key,
                json.dumps(product_for_storage, ensure_ascii=False, default=str),
                json.dumps(raw, ensure_ascii=False, default=str),
                created_at,
                now,
            ),
        )

    return new_product_id


def list_products(platform: str | None = None) -> list[dict[str, Any]]:
    init_product_db()

    platform_label = normalize_platform_label(platform) if platform else None
    with connect() as connection:
        if platform_label and platform_label != "Unknown":
            rows = connection.execute(
                "SELECT * FROM products WHERE platform = ? ORDER BY updated_at DESC",
                (platform_label,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM products ORDER BY updated_at DESC"
            ).fetchall()

    return [row_to_product(row) for row in rows]


def get_products(product_ids: list[str]) -> list[dict[str, Any]]:
    init_product_db()
    clean_ids = [product_id for product_id in product_ids if product_id]
    if not clean_ids:
        return []

    placeholders = ",".join("?" for _ in clean_ids)
    with connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM products WHERE id IN ({placeholders})",
            clean_ids,
        ).fetchall()

    by_id = {row["id"]: row_to_product(row) for row in rows}
    return [by_id[product_id] for product_id in clean_ids if product_id in by_id]


def delete_product(product_id: str) -> bool:
    init_product_db()

    with connect() as connection:
        cursor = connection.execute("DELETE FROM products WHERE id = ?", (product_id,))
        return cursor.rowcount > 0


def delete_products(product_ids: list[str]) -> int:
    init_product_db()
    clean_ids = [product_id for product_id in product_ids if product_id]
    if not clean_ids:
        return 0

    placeholders = ",".join("?" for _ in clean_ids)
    with connect() as connection:
        cursor = connection.execute(
            f"DELETE FROM products WHERE id IN ({placeholders})",
            clean_ids,
        )
        return cursor.rowcount


def clear_products() -> int:
    init_product_db()

    with connect() as connection:
        cursor = connection.execute("DELETE FROM products")
        return cursor.rowcount
