from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VerifiedMember:
    email: str


class VerifiedMemberStore:
    """Persists which email each Discord member verified with, so GHL tags can be rechecked later."""

    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path
        self._lock = asyncio.Lock()

    async def set_verified(self, guild_id: int, member_id: int, email: str) -> None:
        async with self._lock:
            data = await asyncio.to_thread(self._read)
            data.setdefault("guilds", {}).setdefault(str(guild_id), {})[str(member_id)] = {
                "email": email
            }
            await asyncio.to_thread(self._write, data)

    async def remove_verified(self, guild_id: int, member_id: int) -> None:
        async with self._lock:
            data = await asyncio.to_thread(self._read)
            guild_data = data.get("guilds", {}).get(str(guild_id), {})
            guild_data.pop(str(member_id), None)
            await asyncio.to_thread(self._write, data)

    async def get_all(self, guild_id: int) -> dict[int, VerifiedMember]:
        async with self._lock:
            data = await asyncio.to_thread(self._read)
            guild_data = data.get("guilds", {}).get(str(guild_id), {})
            return {
                int(member_id): VerifiedMember(email=entry["email"])
                for member_id, entry in guild_data.items()
                if entry.get("email")
            }

    def _read(self) -> dict[str, Any]:
        if not self._file_path.exists():
            return {"guilds": {}}

        with self._file_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _write(self, data: dict[str, Any]) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        with self._file_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, sort_keys=True)
            file.write("\n")
