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

    async def list_discord_linked_contacts(self) -> list[dict[str, Any]]:
        """Returns every GHL contact that has the 'Discord ID' custom field populated.

        GHL's plain-text `query` search (used by get_contact_by_email) does not search custom
        field values, so contacts can't be reverse-looked-up by Discord ID that way. Instead this
        pages through every contact in the location with no query filter (the same endpoint and
        auth already proven to work for email lookups) and filters for the field client-side.
        Used to recheck members who hold a tag-role but have no local record of the email they
        verified with (e.g. the role predates this bot, or the local record was lost).
        """
        field_id = await self._get_discord_id_field_id()
        if field_id is None:
            return []

        linked: list[dict[str, Any]] = []
        seen_contact_ids: set[str] = set()
        start_after_id: str | None = None
        start_after: str | None = None
        page_limit = 100
        max_pages = 50

        async with aiohttp.ClientSession() as session:
            for page_index in range(max_pages):
                params: dict[str, Any] = {
                    "locationId": self._settings.ghl_location_id,
                    "limit": page_limit,
                }
                if start_after_id and start_after:
                    params["startAfterId"] = start_after_id
                    params["startAfter"] = start_after

                try:
                    async with session.get(
                        f"{BASE_URL}/contacts/",
                        headers=self._headers(),
                        params=params,
                    ) as response:
                        if response.status != 200:
                            body = await response.text()
                            logger.warning(
                                "GHL contacts list failed (status %s): %s", response.status, body
                            )
                            response.raise_for_status()

                        data = await response.json()
                except Exception:
                    if page_index == 0:
                        raise
                    logger.exception(
                        "GHL contacts list: page %s failed, returning %s contact(s) found so far",
                        page_index,
                        len(linked),
                    )
                    break

                contacts = data.get("contacts", [])
                new_contacts = [c for c in contacts if c.get("id") not in seen_contact_ids]
                if not new_contacts:
                    break

                for contact in new_contacts:
                    seen_contact_ids.add(contact["id"])
                    for cf in contact.get("customFields") or []:
                        if cf.get("id") == field_id and cf.get("value"):
                            linked.append(contact)
                            break

                if len(contacts) < page_limit:
                    break

                last = new_contacts[-1]
                start_after_id = last.get("id")
                start_after = str(last.get("dateAdded") or "")
                if not start_after_id:
                    break

        return linked

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
