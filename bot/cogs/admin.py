from __future__ import annotations

import json
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.bot import MoreThanScalingBot


logger = logging.getLogger(__name__)


class AdminCog(commands.Cog):
    def __init__(self, bot: MoreThanScalingBot) -> None:
        self.bot = bot

    @app_commands.command(name="status", description="Show the bot status for this server.")
    @app_commands.checks.has_permissions(administrator=True)
    async def status(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        await interaction.response.defer(ephemeral=True)

        latency_ms = round(self.bot.latency * 1000)
        guild_state = await self.bot.state_store.get_guild_state(interaction.guild.id)

        role_text = "Not set"
        if self.bot.settings.verified_role_id:
            role = interaction.guild.get_role(self.bot.settings.verified_role_id)
            role_text = role.mention if role else f"Missing role ({self.bot.settings.verified_role_id})"

        backlog_channel_text = "Not set"
        if guild_state.backlog_channel_id:
            channel = interaction.guild.get_channel(guild_state.backlog_channel_id)
            backlog_channel_text = channel.mention if channel else f"Missing ({guild_state.backlog_channel_id})"

        if self.bot.settings.ghl_tag_roles:
            tag_lines = []
            for tag_name, rid in self.bot.settings.ghl_tag_roles.items():
                r = interaction.guild.get_role(rid)
                label = f"**{r.name}**" if r else f"**{tag_name}**"
                role_mention = r.mention if r else f"Missing ({rid})"
                tag_lines.append(f"{label} → {role_mention}")
            tag_roles_text = "\n".join(tag_lines)
        else:
            tag_roles_text = "None configured (set GHL_TAG_ROLES in .env)"

        embed = discord.Embed(
            title="Bot Status",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Server", value=interaction.guild.name, inline=True)
        embed.add_field(name="Additional Verified Role", value=role_text, inline=False)
        embed.add_field(name="Backlog Channel", value=backlog_channel_text, inline=True)
        embed.add_field(name="GHL Tag → Role Mapping", value=tag_roles_text, inline=False)
        embed.add_field(name="Discord Latency", value=f"{latency_ms}ms", inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="set_backlog_channel", description="Set the channel where verification attempts are logged.")
    @app_commands.describe(channel="Channel to receive verification attempt logs.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_backlog_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        assert interaction.guild is not None
        await self.bot.state_store.set_backlog_channel(interaction.guild.id, channel.id)

        await interaction.response.send_message(
            f"Verification backlog will be sent to {channel.mention}.",
            ephemeral=True,
        )
        await self.bot.send_activity_log(
            interaction.guild,
            "Backlog Channel Updated",
            f"{interaction.user.mention} set the verification backlog channel to {channel.mention}.",
            discord.Color.green(),
        )

    @app_commands.command(name="ghl_lookup", description="Fetch a contact's full GHL record by email (testing only).")
    @app_commands.describe(email="Email address to look up in GoHighLevel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def ghl_lookup(self, interaction: discord.Interaction, email: str) -> None:
        if not self.bot.settings.ghl_api_key or not self.bot.settings.ghl_location_id:
            await interaction.response.send_message(
                "⚠️ GHL_API_KEY or GHL_LOCATION_ID is not configured in .env.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            contact = await self.bot.ghl_client.get_contact_by_email(email)
        except Exception:
            logger.exception("GHL lookup failed for email %s", email)
            await interaction.followup.send(
                "⚠️ Failed to reach GoHighLevel. Check the token/scopes and try again.",
                ephemeral=True,
            )
            return

        if contact is None:
            await interaction.followup.send(f"❌ No GHL contact found for `{email}`.", ephemeral=True)
            return

        raw = json.dumps(contact, indent=2)
        if len(raw) > 950:
            raw = raw[:950] + "\n... (truncated)"

        tags = ", ".join(contact.get("tags", []) or []) or "None"
        embed = discord.Embed(title="GHL Contact Record", color=discord.Color.blurple())
        embed.add_field(name="Email", value=contact.get("email", "N/A"), inline=True)
        embed.add_field(name="Contact ID", value=contact.get("id", "N/A"), inline=True)
        embed.add_field(name="Tags", value=tags, inline=False)
        embed.add_field(name="Raw Record", value=f"```json\n{raw}\n```", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="sync", description="Admin-only: sync all slash commands globally.")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        synced = await self.bot.tree.sync()
        logger.info("Globally synced %s slash commands", len(synced))
        await interaction.followup.send(f"Synced {len(synced)} commands globally.", ephemeral=True)
        if interaction.guild:
            await self.bot.send_activity_log(
                interaction.guild,
                "Slash Commands Synced",
                f"{interaction.user.mention} synced {len(synced)} slash commands.",
                discord.Color.green(),
            )

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "You do not have permission to use this command."
        else:
            logger.exception("Slash command failed", exc_info=error)
            message = "Something went wrong while running this command."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            logger.warning("Could not deliver error response for interaction %s", interaction.id)


async def setup(bot: MoreThanScalingBot) -> None:
    await bot.add_cog(AdminCog(bot))
