import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


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
) -> str:
    init_product_db()

    now = utc_now()
    new_product_id = product_id or f"prd_{uuid.uuid4().hex[:16]}"
    platform_label = normalize_platform_label(platform)
    product_for_storage = dict(product)
    product_for_storage["id"] = new_product_id
    product_for_storage["platform"] = platform_label
    product_for_storage["updated_at"] = now
    product_for_storage.setdefault("created_at", now)

    with connect() as connection:
        connection.execute(
            """
            INSERT INTO products (
                id, platform, title, base_price, cover_image,
                data_json, raw_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_product_id,
                platform_label,
                product_title(product_for_storage),
                str(product_for_storage.get("base_price") or ""),
                product_cover(product_for_storage),
                json.dumps(product_for_storage, ensure_ascii=False, default=str),
                json.dumps(raw, ensure_ascii=False, default=str),
                now,
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
