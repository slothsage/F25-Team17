import base64
import logging
from typing import Any, Dict, Optional, List

import requests
from django.conf import settings
from django.core.cache import cache

from .utils import get_points_per_usd

logger = logging.getLogger(__name__)


class EbayService:
    """Service for interacting with the eBay Browse API."""

    def __init__(self) -> None:
        self.client_id: str = getattr(settings, "EBAY_CLIENT_ID", "")
        self.client_secret: str = getattr(settings, "EBAY_CLIENT_SECRET", "")
        self.is_sandbox: bool = getattr(settings, "EBAY_SANDBOX", True)
        self.marketplace: str = getattr(settings, "EBAY_MARKETPLACE", "EBAY_US")

        self.base_url = (
            "https://api.sandbox.ebay.com" if self.is_sandbox else "https://api.ebay.com"
        )

        # Separate cache keys for sandbox vs prod so tokens never collide
        self._token_cache_key = (
            "ebay_access_token:sandbox" if self.is_sandbox else "ebay_access_token:prod"
        )

    # ------------------------- helpers -------------------------

    def _get_base64_auth(self) -> str:
        auth_string = f"{self.client_id}:{self.client_secret}"
        return base64.b64encode(auth_string.encode("utf-8")).decode("utf-8")

    def _bearer_headers(self, token: str) -> Dict[str, str]:
        # Marketplace header is REQUIRED for Browse API
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": self.marketplace,
        }

    # ------------------------- auth ----------------------------

    def get_access_token(self) -> str:
        """Get or refresh an OAuth app token; cached until ~5 min before expiry."""
        # Quick sanity checks to avoid opaque 400s
        if not self.client_id or not self.client_secret:
            raise Exception(
                "EBAY_CLIENT_ID / EBAY_CLIENT_SECRET are empty. "
                "Check your environment and settings."
            )

        cached = cache.get(self._token_cache_key)
        if cached:
            return cached

        logger.info(
            "Refreshing eBay access token (sandbox=%s, marketplace=%s)",
            self.is_sandbox, self.marketplace
        )
        url = f"{self.base_url}/identity/v1/oauth2/token"

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {self._get_base64_auth()}",
        }

        # IMPORTANT: Use the production scope string for BOTH prod & sandbox
        data = {
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        }

        try:
            resp = requests.post(url, headers=headers, data=data, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            access_token = payload["access_token"]
            expires_in = int(payload.get("expires_in", 7200))
            cache.set(self._token_cache_key, access_token, max(60, expires_in - 300))
            return access_token
        except requests.RequestException as e:
            logger.error(
                "Error getting eBay token (sandbox=%s): %s",
                self.is_sandbox, e, exc_info=True
            )
            raise Exception(f"Failed to authenticate with eBay: {e}")

    # ------------------------- sandbox demo --------------------

    @staticmethod
    def _demo_items() -> List[Dict[str, Any]]:
        """
        Small set of demo items used ONLY when:
        - running in sandbox, and
        - the Browse API returns total == 0

        These mimic Browse item_summary fields we use.
        """
        return [
            {
                "itemId": "DEMO-DRONE-001",
                "title": "Quadcopter Drone with 4K Camera",
                "price": {"value": "129.99", "currency": "USD"},
                "image": {"imageUrl": "https://via.placeholder.com/400?text=Drone"},
                "shortDescription": "Stabilized 4K video, 2 batteries, carry case.",
                "categories": [{"categoryName": "Drones"}],
                "condition": "New",
                "availableQuantity": 12,
                "itemWebUrl": "https://example.com/demo-drone",
            },
            {
                "itemId": "DEMO-LAPTOP-001",
                "title": "14\" Lightweight Laptop, 8GB/256GB",
                "price": {"value": "379.00", "currency": "USD"},
                "image": {"imageUrl": "https://via.placeholder.com/400?text=Laptop"},
                "shortDescription": "Portable everyday laptop with long battery life.",
                "categories": [{"categoryName": "Laptops"}],
                "condition": "Open box",
                "availableQuantity": 5,
                "itemWebUrl": "https://example.com/demo-laptop",
            },
            {
                "itemId": "DEMO-HEADPHONES-001",
                "title": "Wireless Noise-Cancelling Headphones",
                "price": {"value": "89.50", "currency": "USD"},
                "image": {"imageUrl": "https://via.placeholder.com/400?text=Headphones"},
                "shortDescription": "Over-ear, ANC, 30h battery, Bluetooth 5.0.",
                "categories": [{"categoryName": "Headphones"}],
                "condition": "New",
                "availableQuantity": 25,
                "itemWebUrl": "https://example.com/demo-headphones",
            },
        ]

    def _sandbox_demo_response(self, limit: int, offset: int) -> Dict[str, Any]:
        items = self._demo_items()
        limit = min(max(int(limit or 20), 1), 50)
        offset = max(int(offset or 0), 0)
        sliced = items[offset : offset + limit]
        return {
            "href": "sandbox-demo://browse",
            "total": len(items),
            "limit": limit,
            "offset": offset,
            "itemSummaries": sliced,
            # flag so the UI can show a small note if desired
            "_demo": True,
        }

    # ------------------------- browse --------------------------

    def search_products(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
        category_ids: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Call Browse API: GET /buy/browse/v1/item_summary/search
        Returns the raw JSON; caller formats it.
        """
        token = self.get_access_token()
        url = f"{self.base_url}/buy/browse/v1/item_summary/search"

        # Build category_ids
        cat_param = None
        if category_ids:
            if isinstance(category_ids, (list, tuple, set)):
                cats = [
                    str(c).strip()
                    for c in category_ids
                    if str(c).strip() and str(c).strip().lower() not in {"all", "0"}
                ]
                if cats:
                    cat_param = ",".join(cats)
            else:
                c = str(category_ids).strip()
                if c and c.lower() not in {"all", "0"}:
                    cat_param = c

        params = {
            "q": query,
            "limit": min(int(limit or 20), 200),
            "offset": max(int(offset or 0), 0),
        }
        if cat_param:
            params["category_ids"] = cat_param

        headers = self._bearer_headers(token)

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=20)
            # If sandbox Browse returns 404/400 for odd inputs, surface the error
            resp.raise_for_status()
            data = resp.json()

            # If sandbox returns 0 results, provide demo items so UI isn't blank
            if self.is_sandbox and int(data.get("total", 0)) == 0:
                logger.info("Sandbox Browse returned 0 results; serving demo items.")
                return self._sandbox_demo_response(limit=limit, offset=offset)

            # make sure keys exist
            if "itemSummaries" not in data:
                data.setdefault("itemSummaries", [])
                data.setdefault("total", 0)
            return data

        except requests.RequestException as e:
            logger.error("Error searching products: %s (params=%s)", e, params, exc_info=True)
            # As a last resort in sandbox, fall back to demo items instead of crashing
            if self.is_sandbox:
                return self._sandbox_demo_response(limit=limit, offset=offset)
            raise Exception(f"Failed to search eBay products: {e}")

    def get_product_details(self, item_id: str) -> Dict[str, Any]:
        """GET /buy/browse/v1/item/{item_id}"""
        token = self.get_access_token()
        url = f"{self.base_url}/buy/browse/v1/item/{item_id}"
        headers = self._bearer_headers(token)

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("Error getting product details: %s", e, exc_info=True)
            raise Exception(f"Failed to get product details: {e}")

    # ------------------------- formatting ----------------------

    def format_product(self, ebay_item: Dict[str, Any], points_per_usd: Optional[int] = None,) -> Dict[str, Any]:
        """
        Normalize Browse item_summary into fields our UI expects.
        """
        # price
        try:
            price_value = float(ebay_item.get("price", {}).get("value", 0))
        except (TypeError, ValueError):
            price_value = 0.0

        if points_per_usd is None:
            points_per_usd = get_points_per_usd()

        # image
        image_url = ""
        if ebay_item.get("image"):
            image_url = ebay_item["image"].get("imageUrl", "") or ""
        elif ebay_item.get("thumbnailImages"):
            thumbs = ebay_item["thumbnailImages"]
            if isinstance(thumbs, list) and thumbs:
                image_url = thumbs[0].get("imageUrl", "") or ""

        # category
        category_name = "Uncategorized"
        cats = ebay_item.get("categories")
        if isinstance(cats, list) and cats:
            category_name = cats[0].get("categoryName", category_name) or category_name

        return {
            "ebay_item_id": ebay_item.get("itemId", ""),
            "name": ebay_item.get("title", "Unknown Product"),
            "price_usd": price_value,
            "price_points": int(price_value * points_per_usd),
            "description": ebay_item.get("shortDescription", ebay_item.get("title", "")),
            "image_url": image_url,
            "category": category_name,
            "condition": ebay_item.get("condition", "Unknown"),
            "is_available": bool(ebay_item.get("availableQuantity", 0) > 0),
            "view_url": ebay_item.get("itemWebUrl", ""),
        }


ebay_service = EbayService()