from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
STATE_FILE = BASE_DIR / "data" / "bot-state.json"
VERIFIED_MEMBERS_FILE = BASE_DIR / "data" / "verified-members.json"


@dataclass(frozen=True)
class Settings:
    discord_token: str
    command_prefix: str
    verified_role_id: int | None
    state_file: Path
    verified_members_file: Path
    ghl_api_key: str
    ghl_location_id: str
    ghl_tag_roles: dict[str, int]


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Create {ENV_FILE} from .env.example and fill this value."
        )
    return value


def _optional_int(name: str) -> int | None:
    value = os.getenv(name)
    if not value:
        return None
    return int(value)


def _parse_role_map(raw_value: str | None) -> dict[str, int]:
    """Parses 'Name:RoleID,Name2:RoleID2' into a dict. Used for the GHL tag-role mapping."""
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

    return Settings(
        discord_token=_required("DISCORD_TOKEN"),
        command_prefix=os.getenv("COMMAND_PREFIX", "mts!"),
        verified_role_id=_optional_int("VERIFIED_ROLE_ID"),
        state_file=STATE_FILE,
        verified_members_file=VERIFIED_MEMBERS_FILE,
        ghl_api_key=os.getenv("GHL_API_KEY", ""),
        ghl_location_id=os.getenv("GHL_LOCATION_ID", ""),
        ghl_tag_roles=_parse_role_map(os.getenv("GHL_TAG_ROLES")),
    )
