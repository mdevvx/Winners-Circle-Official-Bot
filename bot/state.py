from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GuildState:
    guild_id: int
    backlog_channel_id: int | None = None
    bot_enabled: bool = True


class BotStateStore:
    """Stores lightweight bot settings without an external database."""

    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path
        self._lock = asyncio.Lock()

    async def get_guild_state(self, guild_id: int) -> GuildState:
        async with self._lock:
            data = await asyncio.to_thread(self._read)
            return self._parse_guild_state(guild_id, data)

    async def set_backlog_channel(self, guild_id: int, channel_id: int) -> GuildState:
        async with self._lock:
            data = await asyncio.to_thread(self._read)
            data.setdefault("guilds", {}).setdefault(str(guild_id), {})["backlog_channel_id"] = str(channel_id)
            await asyncio.to_thread(self._write, data)
            return self._parse_guild_state(guild_id, data)

    async def set_bot_enabled(self, guild_id: int, enabled: bool) -> GuildState:
        async with self._lock:
            data = await asyncio.to_thread(self._read)
            data.setdefault("guilds", {}).setdefault(str(guild_id), {})["bot_enabled"] = enabled
            await asyncio.to_thread(self._write, data)
            return self._parse_guild_state(guild_id, data)

    def _parse_guild_state(self, guild_id: int, data: dict[str, Any]) -> GuildState:
        guild_data = data.get("guilds", {}).get(str(guild_id), {})
        backlog_channel_id = guild_data.get("backlog_channel_id") or guild_data.get("log_channel_id")
        return GuildState(
            guild_id=guild_id,
            backlog_channel_id=int(backlog_channel_id) if backlog_channel_id else None,
            bot_enabled=guild_data.get("bot_enabled", True),
        )

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
