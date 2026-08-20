from __future__ import annotations

import logging
from typing import Any

import aiohttp

from bot.config import Settings

logger = logging.getLogger(__name__)

BASE_URL = "https://services.leadconnectorhq.com"
API_VERSION = "2021-07-28"


class GHLClient:
    """Fetches and updates contact records in GoHighLevel via the v2 API using a Private Integration Token."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._discord_id_field_id: str | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.ghl_api_key}",
            "Version": API_VERSION,
            "Accept": "application/json",
        }

    async def _get_discord_id_field_id(self) -> str | None:
        """Resolves and caches the field ID of the 'Discord ID' custom field on Contacts."""
        if self._discord_id_field_id is not None:
            return self._discord_id_field_id

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BASE_URL}/locations/{self._settings.ghl_location_id}/customFields",
                headers=self._headers(),
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    logger.warning(
                        "GHL custom fields lookup failed (status %s): %s", response.status, body
                    )
                    response.raise_for_status()

                data = await response.json()

        for field in data.get("customFields", []):
            name = (field.get("name") or "").strip().lower()
            key = (field.get("fieldKey") or field.get("key") or "").strip().lower()
            if name == "discord id" or key.endswith("discord_id"):
                self._discord_id_field_id = field.get("id")
                return self._discord_id_field_id

        logger.warning(
            "Could not find a 'Discord ID' custom field in GHL location %s",
            self._settings.ghl_location_id,
        )
        return None

    async def get_linked_discord_id(self, contact: dict[str, Any]) -> int | None:
        """Returns the Discord ID already linked to this contact via the custom field, if any."""
        field_id = await self._get_discord_id_field_id()
        if field_id is None:
            return None

        for field in contact.get("customFields") or []:
            if field.get("id") == field_id:
                value = field.get("value")
                if value:
                    try:
                        return int(value)
                    except ValueError:
                        return None
        return None

    async def set_contact_discord_id(self, contact_id: str, discord_id: int) -> None:
        """Writes the verifying Discord ID back into the contact's 'Discord ID' custom field."""
        field_id = await self._get_discord_id_field_id()
        if field_id is None:
            raise RuntimeError("GHL 'Discord ID' custom field is not configured")

        payload = {"customFields": [{"id": field_id, "value": str(discord_id)}]}

        async with aiohttp.ClientSession() as session:
            async with session.put(
                f"{BASE_URL}/contacts/{contact_id}",
                headers=self._headers(),
                json=payload,
            ) as response:
                if response.status not in (200, 201):
                    body = await response.text()
                    logger.warning(
                        "Failed to update GHL contact %s discord id (status %s): %s",
                        contact_id,
                        response.status,
                        body,
                    )
                    response.raise_for_status()

    async def get_contact_by_discord_id(self, discord_id: int) -> dict[str, Any] | None:
        """Returns the full GHL contact record whose 'Discord ID' custom field matches, or None.

        GHL's plain-text `query` search (used by get_contact_by_email) does not search custom
        field values, so this uses the advanced search endpoint with an exact-match filter on the
        custom field instead. Used to recheck members who hold a tag-role but have no local
        record of the email they verified with (e.g. the role predates this bot's tracking, or
        the local record was lost).
        """
        field_id = await self._get_discord_id_field_id()
        if field_id is None:
            return None

        payload = {
            "locationId": self._settings.ghl_location_id,
            "pageLimit": 1,
            "filters": [
                {"field": f"customFields.{field_id}", "operator": "eq", "value": str(discord_id)}
            ],
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BASE_URL}/contacts/search",
                headers=self._headers(),
                json=payload,
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    logger.warning(
                        "GHL contact search by Discord ID failed (status %s): %s", response.status, body
                    )
                    response.raise_for_status()

                data = await response.json()

        contacts = data.get("contacts", [])
        return contacts[0] if contacts else None

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
