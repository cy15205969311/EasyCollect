import asyncio
import csv
import json
import logging
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import product_store


BASE_DIR = Path(__file__).resolve().parents[2]
CACHE_DIR = BASE_DIR / "static" / "cache_data"
EXPORT_DIR = BASE_DIR / "static" / "exports"
PARSED_PRODUCT_PATH = CACHE_DIR / "parsed_product.json"
OPTIMIZED_PRODUCT_PATH = CACHE_DIR / "optimized_product.json"

MAIN_IMAGE_DIR_NAME = "01_\u4e3b\u56fe"
SKU_IMAGE_DIR_NAME = "02_\u53d8\u4f53\u56fe"
COPY_FILE_NAME = "03_\u5546\u54c1\u6587\u6848.txt"
SKU_CSV_FILE_NAME = "05_\u53d8\u4f53\u5e93\u5b58\u8868.csv"
SHOPEE_CSV_FILE_NAME = "04_Shopee\u6279\u91cf\u4e0a\u67b6\u8868.csv"
MAIN_IMAGE_PREFIX = "\u4e3b\u56fe"
CSV_HEADERS = ["\u89c4\u683c\u540d\u79f0", "\u4ef7\u683c", "\u5e93\u5b58", "\u5173\u8054\u56fe\u7247\u540d"]
SHOPEE_CSV_HEADERS = [
    "\u5546\u54c1\u5206\u7c7b (Category ID)",
    "\u5546\u54c1\u540d\u79f0 (Product Name)",
    "\u5546\u54c1\u63cf\u8ff0 (Product Description)",
    "\u4ef7\u683c (Price)",
    "\u5e93\u5b58 (Stock)",
    "\u4e3bSKU (Parent SKU)",
    "\u9009\u9879\u540d\u79f0 (Variation Name)",
    "\u9009\u9879\u56fe\u7247 (Variation Image)",
    "\u5546\u54c1\u4e3b\u56fe1 (Cover Image)",
    "\u5546\u54c1\u4e3b\u56fe2 (Image 2)",
    "\u5546\u54c1\u4e3b\u56fe3 (Image 3)",
    "\u5546\u54c1\u4e3b\u56fe4 (Image 4)",
    "\u5546\u54c1\u4e3b\u56fe5 (Image 5)",
    "\u5546\u54c1\u4e3b\u56fe6 (Image 6)",
    "\u5546\u54c1\u4e3b\u56fe7 (Image 7)",
    "\u5546\u54c1\u4e3b\u56fe8 (Image 8)",
    "\u5546\u54c1\u4e3b\u56fe9 (Image 9)",
]

router = APIRouter()
logger = logging.getLogger("easycollect")


@dataclass
class ExportPackage:
    """Describe a generated EasyCollect ZIP asset package."""

    zip_path: Path
    filename: str
    download_url: str


class BulkExportRequest(BaseModel):
    """Product ids selected in the dashboard for one ZIP export."""

    product_ids: list[str] = Field(default_factory=list)


def sanitize_filename(value: str, fallback: str = "product") -> str:
    """Convert arbitrary product text into a safe filesystem filename segment.

    Args:
        value: Raw product, SKU, or document title text.
        fallback: Name used when the sanitized value is empty.

    Returns:
        A safe filename segment with Windows-reserved characters removed.
    """

    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value or "").strip(" ._")
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:80] or fallback


def normalize_url(url: str) -> str:
    """Normalize protocol-relative 1688 image URLs.

    Args:
        url: Raw URL from parsed or optimized product JSON.

    Returns:
        A normalized absolute URL when possible.
    """

    normalized = (url or "").strip()

    if normalized.startswith("//"):
        normalized = f"https:{normalized}"

    return normalized


def image_extension(url: str, default: str = ".jpg") -> str:
    """Infer a local image file extension from a URL.

    Args:
        url: Image URL.
        default: Extension used when no known suffix is found.

    Returns:
        A lowercase image extension with leading dot.
    """

    suffix = Path(url.split("?", 1)[0]).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else default


def load_product_data() -> tuple[dict[str, Any], bool]:
    """Load optimized product data when present, otherwise parsed product data.

    Returns:
        A tuple containing the product dictionary and whether it came from the
        optimized Agent output.

    Raises:
        HTTPException: Raised when neither JSON cache exists or the selected file
            is invalid.
    """

    source_path = OPTIMIZED_PRODUCT_PATH if OPTIMIZED_PRODUCT_PATH.exists() else PARSED_PRODUCT_PATH
    is_optimized = source_path == OPTIMIZED_PRODUCT_PATH

    if not source_path.exists():
        raise HTTPException(
            status_code=404,
            detail="No product cache found. Run collection before export.",
        )

    try:
        with source_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"{source_path.name} is not valid JSON: {exc}",
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=500,
            detail=f"{source_path.name} must contain a JSON object.",
        )

    return data, is_optimized


def get_product_title(product: dict[str, Any]) -> str:
    """Read the best available product title from parsed or optimized data.

    Args:
        product: Product JSON loaded from local cache.

    Returns:
        Product title string for documents and ZIP naming.
    """

    for key in ["title_optimized", "title", "source_title"]:
        value = product.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return "EasyCollect_Product"


def get_main_images(product: dict[str, Any]) -> list[str]:
    """Read and de-duplicate main image URLs while preserving order.

    Args:
        product: Product JSON loaded from local cache.

    Returns:
        Ordered list of unique main image URLs.
    """

    images: list[str] = []
    seen: set[str] = set()

    for raw_url in product.get("main_images", []):
        if not isinstance(raw_url, str):
            continue

        url = normalize_url(raw_url)
        if not url or url in seen:
            continue

        seen.add(url)
        images.append(url)

    return images


def get_sku_list(product: dict[str, Any]) -> list[dict[str, Any]]:
    """Read product SKU rows from parsed or optimized data.

    Args:
        product: Product JSON loaded from local cache.

    Returns:
        List of SKU dictionaries.
    """

    return [sku for sku in product.get("sku_list", []) if isinstance(sku, dict)]


def get_base_price(product: dict[str, Any]) -> str:
    """Read a fallback product price from base price or the first priced SKU.

    Args:
        product: Product JSON loaded from local cache.

    Returns:
        Price string when available, otherwise an empty string.
    """

    base_price = normalize_csv_price(product.get("base_price"), allow_range=True)
    if base_price:
        return base_price

    for sku in get_sku_list(product):
        price = normalize_csv_price(sku.get("price"))
        if price:
            return price

    return ""


def parse_csv_price(value: Any) -> float | None:
    """Parse normalized or raw marketplace prices for CSV-safe output."""

    if value in (None, "", [], {}):
        return None

    if isinstance(value, (int, float)):
        number = float(value)
    else:
        cleaned = str(value).strip().lower()
        if cleaned in {"not found", "none", "null", "nan", "0", "0.0", "0.00"}:
            return None

        match = re.search(r"\d+(?:[.,]\d+)?", cleaned.replace(",", ""))
        if not match:
            return None

        try:
            number = float(match.group(0))
        except ValueError:
            return None

    if number <= 0:
        return None

    if number >= 100000:
        number = number / 100000

    return number


def normalize_csv_price(value: Any, allow_range: bool = False) -> str:
    """Format a price for Shopee CSV, correcting raw 100000x Shopee values."""

    if allow_range and isinstance(value, str) and "-" in value:
        prices = [parse_csv_price(part) for part in value.split("-", 1)]
        if prices[0] is not None and prices[1] is not None:
            if prices[0] == prices[1]:
                return f"{prices[0]:.2f}"
            return f"{prices[0]:.2f}-{prices[1]:.2f}"

    price = parse_csv_price(value)
    return "" if price is None else f"{price:.2f}"


def build_product_description(product: dict[str, Any]) -> str:
    """Build import-friendly product description for Shopee CSV rows.

    Args:
        product: Parsed or optimized product data.

    Returns:
        A compact description using AI copy when available, otherwise a safe
        fallback based on the product title.
    """

    title = get_product_title(product)
    marketing_copy = product.get("marketing_copy")
    bullet_points = product.get("bullet_points", [])
    lines: list[str] = []

    if isinstance(marketing_copy, str) and marketing_copy.strip():
        lines.append(marketing_copy.strip())
    else:
        lines.append(f"{title}\n\u5546\u54c1\u4fe1\u606f\u5df2\u7531 EasyCollect \u91c7\u96c6\u6e05\u6d17\uff0c\u8bf7\u5728\u4e0a\u67b6\u524d\u6838\u5bf9\u89c4\u683c\u3001\u4ef7\u683c\u548c\u5e93\u5b58\u3002")

    if isinstance(bullet_points, list):
        clean_points = [
            str(point).strip()
            for point in bullet_points
            if str(point).strip()
        ]
        if clean_points:
            lines.append("")
            lines.extend(f"- {point}" for point in clean_points)

    return "\n".join(lines).strip()


def build_parent_sku(title: str) -> str:
    """Create a stable-looking parent SKU prefix for Shopee import rows.

    Args:
        title: Product title.

    Returns:
        Parent SKU string.
    """

    safe_title = sanitize_filename(title, "product").upper()
    safe_title = re.sub(r"[^A-Z0-9_]+", "_", safe_title)
    return f"EC_{safe_title[:24]}_{uuid.uuid4().hex[:6].upper()}"


async def download_image(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    url: str,
    destination: Path,
) -> bool:
    """Download one image URL into a local file.

    Args:
        client: Shared async HTTP client.
        semaphore: Concurrency limiter.
        url: Image URL to download.
        destination: Local file path to write.

    Returns:
        ``True`` when the image was downloaded, otherwise ``False``.
    """

    async with semaphore:
        try:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            destination.write_bytes(response.content)
            return True
        except Exception as exc:
            logger.warning("Image download failed: %s (%s)", url, exc)
            return False


async def download_images(
    image_jobs: list[tuple[str, Path]],
    concurrency: int = 12,
) -> dict[str, str]:
    """Download a batch of images concurrently.

    Args:
        image_jobs: Tuples of image URL and destination path.
        concurrency: Maximum number of concurrent network requests.

    Returns:
        Mapping from source URL to downloaded file name for successful downloads.
    """

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "Referer": "https://detail.1688.com/",
    }
    timeout = httpx.Timeout(20.0, connect=8.0)
    semaphore = asyncio.Semaphore(concurrency)
    downloaded: dict[str, str] = {}

    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        tasks = [
            download_image(client, semaphore, url, destination)
            for url, destination in image_jobs
        ]
        results = await asyncio.gather(*tasks)

    for (url, destination), ok in zip(image_jobs, results, strict=False):
        if ok:
            downloaded[url] = destination.name

    return downloaded


def write_marketing_copy(product: dict[str, Any], output_path: Path, optimized: bool) -> None:
    """Write a human-readable product copy document.

    Args:
        product: Product JSON loaded from local cache.
        output_path: Destination text file path.
        optimized: Whether the source data came from optimized Agent output.
    """

    title = get_product_title(product)
    base_price = product.get("base_price", "")
    marketing_copy = product.get("marketing_copy", "")
    bullet_points = product.get("bullet_points", [])
    platform_tags = product.get("platform_tags", [])

    lines = [
        "EasyCollect \u5546\u54c1\u6587\u6848",
        "=" * 28,
        "",
        f"\u3010\u6570\u636e\u6765\u6e90\u3011: {'optimized_product.json' if optimized else 'parsed_product.json'}",
        f"\u3010\u8de8\u5883\u7206\u6b3e\u6807\u9898\u3011: {title}",
        f"\u3010\u57fa\u7840\u4ef7\u683c\u3011: {base_price}",
        "",
        "\u3010\u8425\u9500\u79cd\u8349\u6587\u6848\u3011:",
        marketing_copy
        or "\u6682\u65e0 AI \u4f18\u5316\u6587\u6848\uff0c\u5df2\u4fdd\u7559\u539f\u59cb\u6807\u9898\u4e0e\u6e05\u6d17\u6570\u636e\u3002",
        "",
        "\u3010\u6838\u5fc3\u5356\u70b9\u3011:",
    ]

    if bullet_points:
        lines.extend(f"- {item}" for item in bullet_points)
    else:
        lines.append("- \u6682\u65e0 AI \u5356\u70b9\uff0c\u8bf7\u5148\u914d\u7f6e LLM API Key \u6216\u91cd\u8bd5\u4f18\u5316\u6d41\u7a0b\u3002")

    lines.extend(["", "\u3010\u641c\u7d22\u6807\u7b7e\u3011:"])
    if platform_tags:
        lines.append(", ".join(str(tag) for tag in platform_tags))
    else:
        lines.append("\u6682\u65e0\u6807\u7b7e\u3002")

    output_path.write_text("\n".join(lines), encoding="utf-8")


def write_sku_csv(
    sku_list: list[dict[str, Any]],
    output_path: Path,
    sku_image_files: dict[str, str],
) -> None:
    """Write SKU rows to a CSV file for spreadsheet review.

    Args:
        sku_list: Product SKU rows.
        output_path: Destination CSV path.
        sku_image_files: Mapping from SKU image URL to downloaded image filename.
    """

    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_HEADERS)
        writer.writeheader()

        for sku in sku_list:
            sku_image = normalize_url(str(sku.get("sku_image") or ""))
            writer.writerow(
                {
                    CSV_HEADERS[0]: sku.get("spec_name", ""),
                    CSV_HEADERS[1]: normalize_csv_price(sku.get("price")),
                    CSV_HEADERS[2]: sku.get("stock", ""),
                    CSV_HEADERS[3]: sku_image_files.get(sku_image, ""),
                }
            )


def write_shopee_upload_csv(
    product: dict[str, Any],
    output_path: Path,
) -> None:
    """Write a Shopee bulk-upload CSV into the export package.

    The CSV keeps a fixed column layout even when variation images are missing
    or the product has fewer than nine main images. Rows are flattened from the
    SKU list so users can import or refine them in Shopee Seller Center.

    Args:
        product: Parsed or optimized product data.
        output_path: Destination CSV path.
    """

    title = get_product_title(product)
    description = build_product_description(product)
    base_price = get_base_price(product)
    parent_sku = build_parent_sku(title)
    main_images = get_main_images(product)[:9]
    main_image_columns = {
        SHOPEE_CSV_HEADERS[index + 8]: main_images[index] if index < len(main_images) else ""
        for index in range(9)
    }
    sku_list = get_sku_list(product) or [
        {
            "spec_name": "",
            "price": base_price,
            "stock": "1",
            "sku_image": "",
        }
    ]

    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=SHOPEE_CSV_HEADERS)
        writer.writeheader()

        for sku in sku_list:
            sku_price = normalize_csv_price(sku.get("price")) or base_price
            sku_stock = str(sku.get("stock") or "0").strip()
            sku_image = normalize_url(str(sku.get("sku_image") or ""))
            row = {
                SHOPEE_CSV_HEADERS[0]: "",
                SHOPEE_CSV_HEADERS[1]: title,
                SHOPEE_CSV_HEADERS[2]: description,
                SHOPEE_CSV_HEADERS[3]: sku_price,
                SHOPEE_CSV_HEADERS[4]: sku_stock,
                SHOPEE_CSV_HEADERS[5]: parent_sku,
                SHOPEE_CSV_HEADERS[6]: sku.get("spec_name", ""),
                SHOPEE_CSV_HEADERS[7]: sku_image,
                **main_image_columns,
            }
            writer.writerow(row)


def write_bulk_shopee_upload_csv(
    products: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Write one Shopee upload CSV containing multiple selected products."""

    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=SHOPEE_CSV_HEADERS)
        writer.writeheader()

        for product in products:
            title = get_product_title(product)
            description = build_product_description(product)
            base_price = get_base_price(product)
            parent_sku = build_parent_sku(title)
            main_images = get_main_images(product)[:9]
            main_image_columns = {
                SHOPEE_CSV_HEADERS[index + 8]: main_images[index] if index < len(main_images) else ""
                for index in range(9)
            }
            sku_list = get_sku_list(product) or [
                {
                    "spec_name": "",
                    "price": base_price,
                    "stock": "1",
                    "sku_image": "",
                }
            ]

            for sku in sku_list:
                writer.writerow(
                    {
                        SHOPEE_CSV_HEADERS[0]: "",
                        SHOPEE_CSV_HEADERS[1]: title,
                        SHOPEE_CSV_HEADERS[2]: description,
                        SHOPEE_CSV_HEADERS[3]: normalize_csv_price(sku.get("price")) or base_price,
                        SHOPEE_CSV_HEADERS[4]: str(sku.get("stock") or "0").strip(),
                        SHOPEE_CSV_HEADERS[5]: parent_sku,
                        SHOPEE_CSV_HEADERS[6]: sku.get("spec_name", ""),
                        SHOPEE_CSV_HEADERS[7]: normalize_url(str(sku.get("sku_image") or "")),
                        **main_image_columns,
                    }
                )


def make_zip(source_dir: Path, zip_path: Path) -> Path:
    """Create a ZIP archive from an export directory.

    Args:
        source_dir: Directory to archive.
        zip_path: Final ZIP file path.

    Returns:
        The ZIP file path.
    """

    archive_base = zip_path.with_suffix("")
    shutil.make_archive(str(archive_base), "zip", root_dir=source_dir)
    return zip_path


def cleanup_export(paths: list[Path]) -> None:
    """Delete temporary export files.

    Args:
        paths: Files or directories to delete.
    """

    for path in paths:
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink()
        except Exception as exc:
            logger.warning("Export cleanup failed for %s: %s", path, exc)


def cleanup_export_later(paths: list[Path], delay_seconds: int = 600) -> None:
    """Delete export files after a delay so Chrome can fetch the ZIP URL.

    Args:
        paths: Files or directories to delete.
        delay_seconds: Delay before cleanup starts.
    """

    time.sleep(delay_seconds)
    cleanup_export(paths)


def public_download_url(zip_path: Path, base_url: str = "http://localhost:8000") -> str:
    """Build a browser-accessible URL for an export ZIP under ``/static``.

    Args:
        zip_path: Generated ZIP path under ``server/static/exports``.
        base_url: Public FastAPI base URL.

    Returns:
        Absolute URL that Chrome can download.
    """

    return f"{base_url.rstrip('/')}/static/exports/{quote(zip_path.name)}"


async def build_export_package(product: dict[str, Any], optimized: bool = False) -> ExportPackage:
    """Build an EasyCollect ZIP package and keep the ZIP on disk.

    Args:
        product: Parsed or optimized product data.
        optimized: Whether the product came from Agent optimized output.

    Returns:
        Metadata for the generated ZIP package.
    """

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    title = get_product_title(product)
    export_id = uuid.uuid4().hex[:10]
    safe_title = sanitize_filename(title, "EasyCollect_Product")
    work_dir = EXPORT_DIR / f"temp_{export_id}"
    main_image_dir = work_dir / MAIN_IMAGE_DIR_NAME
    sku_image_dir = work_dir / SKU_IMAGE_DIR_NAME
    zip_path = EXPORT_DIR / f"EasyCollect_{safe_title}_{export_id}.zip"

    main_image_dir.mkdir(parents=True, exist_ok=True)
    sku_image_dir.mkdir(parents=True, exist_ok=True)

    main_images = get_main_images(product)
    sku_list = get_sku_list(product)
    main_jobs = [
        (
            url,
            main_image_dir / f"{MAIN_IMAGE_PREFIX}_{index}{image_extension(url)}",
        )
        for index, url in enumerate(main_images, start=1)
    ]

    sku_jobs: list[tuple[str, Path]] = []
    seen_sku_images: set[str] = set()
    for sku in sku_list:
        raw_url = sku.get("sku_image")
        if not isinstance(raw_url, str):
            continue

        url = normalize_url(raw_url)
        if not url or url in seen_sku_images:
            continue

        seen_sku_images.add(url)
        spec_name = sanitize_filename(str(sku.get("spec_name") or "sku_image"), "sku_image")
        sku_jobs.append((url, sku_image_dir / f"{spec_name}{image_extension(url)}"))

    main_image_files = await download_images(main_jobs)
    sku_image_files = await download_images(sku_jobs)

    write_marketing_copy(product, work_dir / COPY_FILE_NAME, optimized)
    write_sku_csv(sku_list, work_dir / SKU_CSV_FILE_NAME, sku_image_files)
    write_shopee_upload_csv(product, work_dir / SHOPEE_CSV_FILE_NAME)
    make_zip(work_dir, zip_path)
    cleanup_export([work_dir])

    logger.info(
        "Export package generated: %s (main_images=%s/%s, sku_images=%s/%s)",
        zip_path,
        len(main_image_files),
        len(main_jobs),
        len(sku_image_files),
        len(sku_jobs),
    )

    return ExportPackage(
        zip_path=zip_path,
        filename=zip_path.name,
        download_url=public_download_url(zip_path),
    )


async def build_bulk_export_package(products: list[dict[str, Any]]) -> ExportPackage:
    """Build one ZIP package for multiple selected product-library rows."""

    if not products:
        raise HTTPException(status_code=400, detail="No products selected for export.")

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    export_id = uuid.uuid4().hex[:10]
    work_dir = EXPORT_DIR / f"bulk_temp_{export_id}"
    zip_path = EXPORT_DIR / f"EasyCollect_Bulk_{export_id}.zip"
    work_dir.mkdir(parents=True, exist_ok=True)

    image_jobs: list[tuple[str, Path]] = []
    seen_destinations: set[Path] = set()

    for product_index, product in enumerate(products, start=1):
        title = get_product_title(product)
        product_dir = work_dir / f"{product_index:02d}_{sanitize_filename(title)}"
        main_image_dir = product_dir / MAIN_IMAGE_DIR_NAME
        sku_image_dir = product_dir / SKU_IMAGE_DIR_NAME
        main_image_dir.mkdir(parents=True, exist_ok=True)
        sku_image_dir.mkdir(parents=True, exist_ok=True)

        for image_index, url in enumerate(get_main_images(product), start=1):
            destination = main_image_dir / f"{MAIN_IMAGE_PREFIX}_{image_index}{image_extension(url)}"
            if destination not in seen_destinations:
                seen_destinations.add(destination)
                image_jobs.append((url, destination))

        seen_sku_images: set[str] = set()
        for sku in get_sku_list(product):
            raw_url = sku.get("sku_image")
            if not isinstance(raw_url, str):
                continue

            url = normalize_url(raw_url)
            if not url or url in seen_sku_images:
                continue

            seen_sku_images.add(url)
            spec_name = sanitize_filename(str(sku.get("spec_name") or "sku_image"), "sku_image")
            destination = sku_image_dir / f"{spec_name}{image_extension(url)}"
            if destination not in seen_destinations:
                seen_destinations.add(destination)
                image_jobs.append((url, destination))

        write_marketing_copy(product, product_dir / COPY_FILE_NAME, bool(product.get("title_optimized")))
        write_sku_csv(get_sku_list(product), product_dir / SKU_CSV_FILE_NAME, {})

    await download_images(image_jobs)
    write_bulk_shopee_upload_csv(products, work_dir / SHOPEE_CSV_FILE_NAME)
    make_zip(work_dir, zip_path)
    cleanup_export([work_dir])

    logger.info(
        "Bulk export package generated: %s (products=%s, image_jobs=%s)",
        zip_path,
        len(products),
        len(image_jobs),
    )

    return ExportPackage(
        zip_path=zip_path,
        filename=zip_path.name,
        download_url=public_download_url(zip_path),
    )


@router.get("/api/export/download")
async def download_export_package(background_tasks: BackgroundTasks) -> FileResponse:
    """Build and return a ZIP package with images, copy, and SKU inventory CSV.

    Args:
        background_tasks: FastAPI background task manager used to remove temp
            export files after the download response is sent.

    Returns:
        A ``FileResponse`` streaming the generated ZIP package.
    """

    product, optimized = load_product_data()
    package = await build_export_package(product, optimized)
    background_tasks.add_task(cleanup_export, [package.zip_path])

    return FileResponse(
        path=package.zip_path,
        media_type="application/zip",
        filename=package.filename,
    )


@router.post("/api/export/bulk")
async def export_bulk_products(
    payload: BulkExportRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    """Build a ZIP package for selected product-library items."""

    product_ids = [product_id for product_id in payload.product_ids if product_id]
    if not product_ids:
        raise HTTPException(status_code=400, detail="Please select at least one product.")

    products = product_store.get_products(product_ids)
    if not products:
        raise HTTPException(status_code=404, detail="Selected products were not found.")

    platforms = {
        str(product.get("platform") or "Unknown").strip().lower()
        for product in products
    }
    platforms.discard("")
    if len(platforms) > 1:
        raise HTTPException(status_code=400, detail="跨平台数据无法合并导出")

    package = await build_bulk_export_package(products)
    background_tasks.add_task(cleanup_export_later, [package.zip_path])

    return {
        "status": "success",
        "download_url": package.download_url,
        "filename": package.filename,
    }
