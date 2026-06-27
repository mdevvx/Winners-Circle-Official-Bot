from __future__ import annotations

from bot.bot import MoreThanScalingBot
from bot.config import load_settings
from bot.google_sheets import GoogleSheetMemberStore
from bot.logging_config import setup_logging
from bot.state import BotStateStore


def main() -> None:
    setup_logging()
    settings = load_settings()
    member_store = GoogleSheetMemberStore(settings)
    state_store = BotStateStore(settings.state_file)
    bot = MoreThanScalingBot(settings, member_store, state_store)
    bot.run(settings.discord_token)
