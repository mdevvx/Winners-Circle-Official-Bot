from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

import gspread

from bot.config import Settings

logger = logging.getLogger(__name__)

DISCORD_ID_HEADERS = {
    "discord id",
    "discordid",
    "discord_id",
    "please provide your discord id (optional)",
}
STATUS_HEADER = "Discord Status"

EMAIL_HEADERS = {
    "email",
    "email address",
    "e-mail",
    "your email",
    "email id",
}
MEMBER_STATUS_HEADERS = {
    "status",
    "membership status",
    "member status",
    "payment status",
}
COURSE_HEADERS = {
    "course",
    "course name",
    "program",
    "program name",
    "product",
    "which course",
}
ACTIVE_STATUSES = {"paid"}


@dataclass
class MemberRecord:
    email: str
    status: str
    course: str

    @property
    def is_active(self) -> bool:
        return bool(self.status) and self.status.strip().lower() in ACTIVE_STATUSES


class GoogleSheetMemberStore:
    """Reads and updates Discord member status in the configured Google Sheet."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def get_member_status(self, discord_id: int) -> str | None:
        return await asyncio.to_thread(self._get_member_status_sync, str(discord_id))

    async def set_member_status(self, discord_id: int, status: str) -> bool:
        return await asyncio.to_thread(
            self._set_member_status_sync, str(discord_id), status
        )

    async def lookup_by_email(self, email: str) -> MemberRecord | None:
        return await asyncio.to_thread(
            self._lookup_by_email_sync, email.strip().lower()
        )

    def _worksheet(self) -> gspread.Worksheet:
        raw = str(self._settings.google_service_account_file_wc)
        if raw.strip().startswith("{"):
            client = gspread.service_account_from_dict(json.loads(raw))
        else:
            client = gspread.service_account(filename=raw)
        spreadsheet = client.open_by_key(self._settings.google_sheet_id)
        return spreadsheet.worksheet(self._settings.google_worksheet_name)

    def _lookup_by_email_sync(self, email: str) -> MemberRecord | None:
        worksheet = self._worksheet()
        headers = worksheet.row_values(1)

        email_col = self._find_column_by_headers(headers, EMAIL_HEADERS)
        if email_col is None:
            logger.warning("Google Sheet is missing an email column")
            return None

        status_col = self._find_column_by_headers(headers, MEMBER_STATUS_HEADERS)
        course_col = self._find_column_by_headers(headers, COURSE_HEADERS)

        email_values = worksheet.col_values(email_col)
        for row_number, value in enumerate(email_values, start=1):
            if row_number == 1:
                continue
            if value.strip().lower() == email:
                row_values = worksheet.row_values(row_number)
                status = (
                    row_values[status_col - 1]
                    if status_col and len(row_values) >= status_col
                    else ""
                )
                course = (
                    row_values[course_col - 1]
                    if course_col and len(row_values) >= course_col
                    else ""
                )
                return MemberRecord(email=email, status=status, course=course)

        return None

    def _find_column_by_headers(
        self, headers: list[str], valid_headers: set[str]
    ) -> int | None:
        for index, header in enumerate(headers, start=1):
            if header.strip().lower() in valid_headers:
                return index
        return None

    def _get_member_status_sync(self, discord_id: str) -> str | None:
        worksheet = self._worksheet()
        headers = worksheet.row_values(1)

        discord_col = self._find_discord_id_column(headers)
        if discord_col is None:
            logger.warning("Google Sheet is missing a Discord ID column")
            return None

        status_col = self._find_status_column(headers)
        row_number = self._find_member_row(worksheet, discord_col, discord_id)
        if row_number is None:
            logger.info("Discord ID %s was not found in Google Sheet", discord_id)
            return None

        if status_col is None:
            return ""

        return worksheet.cell(row_number, status_col).value or ""

    def _set_member_status_sync(self, discord_id: str, status: str) -> bool:
        worksheet = self._worksheet()
        headers = worksheet.row_values(1)

        discord_col = self._find_discord_id_column(headers)
        if discord_col is None:
            logger.warning("Google Sheet is missing a Discord ID column")
            return False

        status_col = self._find_or_create_status_column(worksheet, headers)
        row_number = self._find_member_row(worksheet, discord_col, discord_id)
        if row_number is None:
            logger.info("Discord ID %s was not found in Google Sheet", discord_id)
            return False

        worksheet.update_cell(row_number, status_col, status)
        logger.info("Updated Discord ID %s status to %s", discord_id, status)
        return True

    def _find_discord_id_column(self, headers: list[str]) -> int | None:
        for index, header in enumerate(headers, start=1):
            if header.strip().lower() in DISCORD_ID_HEADERS:
                return index
        return None

    def _find_or_create_status_column(
        self,
        worksheet: gspread.Worksheet,
        headers: list[str],
    ) -> int:
        existing_column = self._find_status_column(headers)
        if existing_column is not None:
            return existing_column

        new_column = len(headers) + 1
        worksheet.update_cell(1, new_column, STATUS_HEADER)
        logger.info("Created Google Sheet column: %s", STATUS_HEADER)
        return new_column

    def _find_status_column(self, headers: list[str]) -> int | None:
        for index, header in enumerate(headers, start=1):
            if header.strip().lower() == STATUS_HEADER.lower():
                return index
        return None

    def _find_member_row(
        self,
        worksheet: gspread.Worksheet,
        discord_col: int,
        discord_id: str,
    ) -> int | None:
        values = worksheet.col_values(discord_col)
        for row_number, value in enumerate(values, start=1):
            if row_number == 1:
                continue
            if value.strip() == discord_id:
                return row_number
        return None
