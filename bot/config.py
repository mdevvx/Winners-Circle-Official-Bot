from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
STATE_FILE = BASE_DIR / "data" / "bot-state.json"


@dataclass(frozen=True)
class Settings:
    discord_token: str
    command_prefix: str
    google_service_account_file_wc: Path
    google_sheet_id: str
    google_worksheet_name: str
    verified_role_id: int | None
    state_file: Path
    owner_ids: set[int]
    course_roles: dict[str, int]


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Create {ENV_FILE} from .env.example and fill this value."
        )
    return value


def _owner_ids(raw_value: str | None) -> set[int]:
    if not raw_value:
        return set()

    owner_ids: set[int] = set()
    for item in raw_value.split(","):
        item = item.strip()
        if item:
            owner_ids.add(int(item))
    return owner_ids


def _optional_int(name: str) -> int | None:
    value = os.getenv(name)
    if not value:
        return None
    return int(value)


def _course_roles(raw_value: str | None) -> dict[str, int]:
    if not raw_value:
        return {}
    result: dict[str, int] = {}
    for item in raw_value.split(","):
        item = item.strip()
        if ":" not in item:
            continue
        name, _, role_id_str = item.rpartition(":")
        name = name.strip()
        role_id_str = role_id_str.strip()
        if name and role_id_str.isdigit():
            result[name] = int(role_id_str)
    return result


def load_settings() -> Settings:
    load_dotenv(ENV_FILE)

    service_account_file = Path(
        os.getenv(
            "GOOGLE_SERVICE_ACCOUNT_FILE_WC", "credentials/google-service-account.json"
        )
    )
    if not service_account_file.is_absolute():
        service_account_file = BASE_DIR / service_account_file

    return Settings(
        discord_token=_required("DISCORD_TOKEN"),
        command_prefix=os.getenv("COMMAND_PREFIX", "mts!"),
        google_service_account_file_wc=service_account_file,
        google_sheet_id=_required("GOOGLE_SHEET_ID"),
        google_worksheet_name=os.getenv("GOOGLE_WORKSHEET_NAME", "Discord Form"),
        verified_role_id=_optional_int("VERIFIED_ROLE_ID"),
        state_file=STATE_FILE,
        owner_ids=_owner_ids(os.getenv("OWNER_IDS")),
        course_roles=_course_roles(os.getenv("COURSE_ROLES")),
    )
