from __future__ import annotations

import logging
from typing import Any

import aiohttp

from bot.config import Settings

logger = logging.getLogger(__name__)

BASE_URL = "https://services.leadconnectorhq.com"
API_VERSION = "2021-07-28"


class GHLClient:
    """Fetches contact records from GoHighLevel via the v2 API using a Private Integration Token."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.ghl_api_key}",
            "Version": API_VERSION,
            "Accept": "application/json",
        }

    async def get_contact_by_email(self, email: str) -> dict[str, Any] | None:
        """Returns the full GHL contact record (including tags) for the given email, or None if not found."""
        email = email.strip().lower()
        params = {"locationId": self._settings.ghl_location_id, "query": email}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BASE_URL}/contacts/",
                headers=self._headers(),
                params=params,
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    logger.warning(
                        "GHL contact search failed (status %s): %s", response.status, body
                    )
                    response.raise_for_status()

                data = await response.json()

        for contact in data.get("contacts", []):
            if (contact.get("email") or "").strip().lower() == email:
                return contact

        return None
