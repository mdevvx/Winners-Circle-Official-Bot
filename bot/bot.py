from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import Settings
from bot.ghl_client import GHLClient
from bot.state import BotStateStore
from bot.verified_members import VerifiedMemberStore


logger = logging.getLogger(__name__)


MAX_SEEN_INTERACTIONS = 1000


class MoreThanScalingCommandTree(app_commands.CommandTree):
    """Keeps slash commands scoped to Discord servers and ignores duplicate interaction delivery."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._seen_interaction_ids: set[int] = set()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.id in self._seen_interaction_ids:
            logger.warning("Ignoring duplicate delivery of interaction %s", interaction.id)
            return False

        self._seen_interaction_ids.add(interaction.id)
        if len(self._seen_interaction_ids) > MAX_SEEN_INTERACTIONS:
            self._seen_interaction_ids.clear()

        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used inside a server.",
                ephemeral=True,
            )
            return False

        return True


class MoreThanScalingBot(commands.Bot):
    def __init__(
        self,
        settings: Settings,
        state_store: BotStateStore,
    ) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.message_content = True

        super().__init__(
            command_prefix=settings.command_prefix,
            intents=intents,
            help_command=None,
            tree_cls=MoreThanScalingCommandTree,
        )
        self.settings = settings
        self.state_store = state_store
        self.ghl_client = GHLClient(settings)
        self.verified_member_store = VerifiedMemberStore(settings.verified_members_file)

    async def send_activity_log(
        self,
        guild: discord.Guild,
        title: str,
        description: str,
        color: discord.Color = discord.Color.blurple(),
    ) -> None:
        guild_state = await self.state_store.get_guild_state(guild.id)
        if not guild_state.backlog_channel_id:
            return

        channel = guild.get_channel(guild_state.backlog_channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(guild_state.backlog_channel_id)
            except discord.HTTPException:
                logger.warning(
                    "Backlog channel %s was not found in guild %s",
                    guild_state.backlog_channel_id,
                    guild.id,
                )
                return

        if not isinstance(channel, discord.abc.Messageable):
            logger.warning("Configured backlog channel %s is not messageable", guild_state.backlog_channel_id)
            return

        embed = discord.Embed(title=title, description=description, color=color)
        embed.set_footer(text=f"Guild ID: {guild.id}")
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            logger.warning("Missing permission to send logs in channel %s", guild_state.log_channel_id)
        except discord.HTTPException:
            logger.exception("Failed to send activity log to channel %s", guild_state.log_channel_id)

    async def setup_hook(self) -> None:
        await self.load_extension("bot.cogs.admin")
        await self.load_extension("bot.cogs.members")
        await self.load_extension("bot.cogs.verification")
        await self.load_extension("bot.cogs.ghl_recheck")
        logger.info("Loaded bot extensions")

        synced = await self.tree.sync()
        logger.info("Auto-synced %s slash commands on startup", len(synced))

    async def on_ready(self) -> None:
        if self.user:
            logger.info("Logged in as %s (%s)", self.user, self.user.id)
