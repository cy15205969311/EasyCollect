import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parents[2]
CACHE_DIR = BASE_DIR / "static" / "cache_data"
OPTIMIZED_PRODUCT_PATH = CACHE_DIR / "optimized_product.json"
PARSED_PRODUCT_PATH = CACHE_DIR / "parsed_product.json"

load_dotenv(BASE_DIR / ".env")

router = APIRouter()
logger = logging.getLogger("easycollect")

SHOPEE_API_PATH_ADD_ITEM = "/api/v2/product/add_item"
SHOPEE_TIMEOUT_SECONDS = 30.0


class ShopeePublishRequest(BaseModel):
    """Optional publish-time fields required by Shopee but absent from 1688 data.

    Attributes:
        category_id: Shopee category ID for the target site and shop.
        original_price: Optional listing price override. When omitted, the
            backend tries to infer a price from the product cache.
        normal_stock: Optional stock override. When omitted, SKU stock is summed.
        weight: Product package weight in kilograms.
        package_length: Package length in centimeters.
        package_width: Package width in centimeters.
        package_height: Package height in centimeters.
        condition: Shopee item condition. Most regions use ``NEW`` for new goods.
        item_status: Listing status. ``NORMAL`` publishes immediately when the
            shop and category validation pass.
        logistic_info: Optional Shopee logistic channel configuration. This is
            passed through as-is so each shop can supply its own enabled channel.
    """

    category_id: int | None = Field(default=None, gt=0)
    original_price: float | None = Field(default=None, gt=0)
    normal_stock: int | None = Field(default=None, ge=0)
    weight: float = Field(default=0.1, gt=0)
    package_length: int = Field(default=10, gt=0)
    package_width: int = Field(default=10, gt=0)
    package_height: int = Field(default=3, gt=0)
    condition: str = "NEW"
    item_status: str = "NORMAL"
    logistic_info: list[dict[str, Any]] = Field(default_factory=list)


class ShopeePublishResponse(BaseModel):
    """Normalized response returned by the EasyCollect Shopee publish endpoint."""

    status: str
    request_url: str
    payload: dict[str, Any]
    shopee_response: dict[str, Any]


def get_shopee_base_url() -> str:
    """Return the Shopee OpenAPI base URL for the configured environment.

    Returns:
        The live or test OpenAPI host.
    """

    env = os.getenv("SHOPEE_ENV", "test").strip().lower()
    if env == "live":
        return "https://partner.shopeemobile.com"

    return "https://partner.test-stable.shopeemobile.com"


def get_required_env(name: str) -> str:
    """Read a required environment variable or raise a friendly API error.

    Args:
        name: Environment variable name.

    Returns:
        Non-empty environment variable value.

    Raises:
        HTTPException: Raised when the variable is absent.
    """

    value = os.getenv(name)
    if not value:
        raise HTTPException(
            status_code=500,
            detail=f"Missing Shopee environment variable: {name}",
        )

    return value


def get_partner_id() -> int:
    """Read and validate ``SHOPEE_PARTNER_ID`` as an integer."""

    raw_value = get_required_env("SHOPEE_PARTNER_ID")
    try:
        return int(raw_value)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="SHOPEE_PARTNER_ID must be an integer.",
        ) from exc


def get_shop_id() -> int:
    """Read and validate ``SHOPEE_SHOP_ID`` as an integer."""

    raw_value = get_required_env("SHOPEE_SHOP_ID")
    try:
        return int(raw_value)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="SHOPEE_SHOP_ID must be an integer.",
        ) from exc


def generate_shopee_sign(api_path: str) -> str:
    """Generate a signed Shopee OpenAPI v2 request URL.

    Shopee v2 Shop API signatures are built from a strict base string:
    ``partner_id + api_path + timestamp + access_token + shop_id``.
    The resulting string is signed with HMAC-SHA256 using ``partner_key`` as
    the secret key. Any ordering change, missing token, or mismatched path will
    cause Shopee to reject the request.

    Args:
        api_path: API path, for example ``/api/v2/product/add_item``.

    Returns:
        Full request URL with Shopee public query parameters and ``sign``.
    """

    partner_id = get_partner_id()
    partner_key = get_required_env("SHOPEE_PARTNER_KEY")
    access_token = get_required_env("SHOPEE_ACCESS_TOKEN")
    shop_id = get_shop_id()
    timestamp = int(time.time())

    base_string = f"{partner_id}{api_path}{timestamp}{access_token}{shop_id}"
    sign = hmac.new(
        partner_key.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    query = {
        "partner_id": partner_id,
        "timestamp": timestamp,
        "access_token": access_token,
        "shop_id": shop_id,
        "sign": sign,
    }
    return f"{get_shopee_base_url()}{api_path}?{urlencode(query)}"


def load_product_cache() -> dict[str, Any]:
    """Load the latest optimized product cache, falling back to parsed data.

    Returns:
        Product dictionary used for Shopee payload mapping.

    Raises:
        HTTPException: Raised when no local product cache exists or JSON is
            malformed.
    """

    product_path = (
        OPTIMIZED_PRODUCT_PATH
        if OPTIMIZED_PRODUCT_PATH.exists()
        else PARSED_PRODUCT_PATH
    )
    if not product_path.exists():
        raise HTTPException(
            status_code=404,
            detail="No product cache found. Run collection and optimization first.",
        )

    try:
        with product_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"{product_path.name} is not valid JSON: {exc}",
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=500,
            detail=f"{product_path.name} must contain a JSON object.",
        )

    return data


def parse_price(value: Any) -> float | None:
    """Convert a product or SKU price-like value into a Shopee float price."""

    if isinstance(value, (int, float)) and value > 0:
        return float(value)

    if isinstance(value, str):
        cleaned = value.strip().replace("¥", "").replace("￥", "")
        cleaned = cleaned.split("-", 1)[0].strip()
        try:
            parsed = float(cleaned)
        except ValueError:
            return None

        return parsed if parsed > 0 else None

    return None


def parse_stock(value: Any) -> int:
    """Convert a product or SKU stock-like value into a non-negative integer."""

    if isinstance(value, bool):
        return 0

    if isinstance(value, int):
        return max(value, 0)

    if isinstance(value, float):
        return max(int(value), 0)

    if isinstance(value, str):
        try:
            return max(int(float(value.strip() or "0")), 0)
        except ValueError:
            return 0

    return 0


def get_product_title(product: dict[str, Any]) -> str:
    """Return the best available Shopee item title from EasyCollect data."""

    for key in ["title_optimized", "title", "source_title"]:
        value = product.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]

    return "EasyCollect Product"


def build_description(product: dict[str, Any]) -> str:
    """Build a Shopee description from marketing copy and bullet points."""

    lines: list[str] = []
    marketing_copy = product.get("marketing_copy")
    if isinstance(marketing_copy, str) and marketing_copy.strip():
        lines.extend([marketing_copy.strip(), ""])

    bullet_points = product.get("bullet_points", [])
    if isinstance(bullet_points, list) and bullet_points:
        lines.append("Highlights:")
        for point in bullet_points:
            if isinstance(point, str) and point.strip():
                lines.append(f"- {point.strip()}")

    tags = product.get("platform_tags", [])
    if isinstance(tags, list) and tags:
        tag_text = " ".join(f"#{tag}" for tag in tags if isinstance(tag, str))
        if tag_text:
            lines.extend(["", tag_text])

    description = "\n".join(lines).strip()
    return description[:3000] or "Product details are collected by EasyCollect."


def infer_original_price(
    product: dict[str, Any],
    override_price: float | None,
) -> float:
    """Resolve Shopee ``original_price`` from override, base price, or SKUs."""

    if override_price is not None:
        return round(override_price, 2)

    base_price = parse_price(product.get("base_price"))
    if base_price is not None:
        return round(base_price, 2)

    sku_prices = [
        parsed
        for sku in product.get("sku_list", [])
        if isinstance(sku, dict)
        for parsed in [parse_price(sku.get("price"))]
        if parsed is not None
    ]
    if sku_prices:
        return round(min(sku_prices), 2)

    raise HTTPException(
        status_code=400,
        detail=(
            "Cannot infer Shopee original_price from optimized_product.json. "
            "Pass original_price in the request body."
        ),
    )


def infer_normal_stock(
    product: dict[str, Any],
    override_stock: int | None,
) -> int:
    """Resolve Shopee ``normal_stock`` from override or summed SKU stock."""

    if override_stock is not None:
        return override_stock

    sku_list = product.get("sku_list", [])
    stock_total = sum(
        parse_stock(sku.get("stock"))
        for sku in sku_list
        if isinstance(sku, dict)
    )
    return stock_total if stock_total > 0 else 1


def build_shopee_payload(
    product: dict[str, Any],
    request: ShopeePublishRequest,
) -> dict[str, Any]:
    """Map EasyCollect optimized data into Shopee ``add_item`` payload.

    Args:
        product: Local EasyCollect product cache.
        request: Publish-time Shopee fields supplied by caller.

    Returns:
        Payload dictionary for ``v2.product.add_item``.
    """

    category_id = request.category_id or parse_stock(os.getenv("SHOPEE_CATEGORY_ID"))
    if category_id <= 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "Shopee category_id is required. Pass category_id in request body "
                "or configure SHOPEE_CATEGORY_ID in server/.env."
            ),
        )

    payload: dict[str, Any] = {
        "category_id": category_id,
        "item_name": get_product_title(product),
        "description": build_description(product),
        "original_price": infer_original_price(product, request.original_price),
        "normal_stock": infer_normal_stock(product, request.normal_stock),
        "weight": request.weight,
        "dimension": {
            "package_length": request.package_length,
            "package_width": request.package_width,
            "package_height": request.package_height,
        },
        "condition": request.condition,
        "item_status": request.item_status,
    }

    if request.logistic_info:
        payload["logistic_info"] = request.logistic_info

    return payload


def normalize_shopee_error(response_data: dict[str, Any]) -> str:
    """Extract a readable error message from a Shopee API response."""

    for key in ["message", "msg", "error_msg", "warning"]:
        value = response_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    error = response_data.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()

    return "Shopee API returned an unknown business error."


@router.post("/api/publish/shopee", response_model=ShopeePublishResponse)
async def publish_to_shopee(
    request: ShopeePublishRequest,
) -> ShopeePublishResponse:
    """Publish the latest optimized EasyCollect product to Shopee.

    This MVP endpoint sends a single base item through ``v2.product.add_item``.
    Complex tier variations, image upload, attributes, and site-specific
    logistics can be layered on after the basic signed request is verified.

    Args:
        request: Optional Shopee category, price, stock, package, and logistics
            overrides supplied by the caller.

    Returns:
        Normalized publish response containing the request payload and Shopee
        response body.
    """

    product = load_product_cache()
    payload = build_shopee_payload(product, request)
    request_url = generate_shopee_sign(SHOPEE_API_PATH_ADD_ITEM)

    try:
        async with httpx.AsyncClient(timeout=SHOPEE_TIMEOUT_SECONDS) as client:
            response = await client.post(request_url, json=payload)
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="Shopee API request timed out. Please retry later.",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Shopee API network error: {exc}",
        ) from exc

    try:
        response_data = response.json() if response.content else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Shopee API returned a non-JSON response: {response.text[:500]}",
        ) from exc

    if not isinstance(response_data, dict):
        raise HTTPException(
            status_code=502,
            detail="Shopee API returned a non-JSON response.",
        )

    if response.status_code >= 400 or response_data.get("error"):
        raise HTTPException(
            status_code=400,
            detail={
                "message": normalize_shopee_error(response_data),
                "shopee_response": response_data,
                "payload": payload,
            },
        )

    logger.info("Shopee publish request accepted: %s", response_data)
    return ShopeePublishResponse(
        status="success",
        request_url=request_url,
        payload=payload,
        shopee_response=response_data,
    )
