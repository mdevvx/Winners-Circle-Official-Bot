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

        leads_channel_text = "Not set"
        if guild_state.leads_channel_id:
            channel = interaction.guild.get_channel(guild_state.leads_channel_id)
            leads_channel_text = channel.mention if channel else f"Missing ({guild_state.leads_channel_id})"

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
        embed.add_field(name="Leads Channel", value=leads_channel_text, inline=True)
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

    @app_commands.command(name="set_leads_channel", description="Set the channel where verification form submissions (name/email/phone) are posted.")
    @app_commands.describe(channel="Channel to receive lead submissions.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_leads_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        assert interaction.guild is not None
        await self.bot.state_store.set_leads_channel(interaction.guild.id, channel.id)

        await interaction.response.send_message(
            f"Verification form submissions will be sent to {channel.mention}.",
            ephemeral=True,
        )
        await self.bot.send_activity_log(
            interaction.guild,
            "Leads Channel Updated",
            f"{interaction.user.mention} set the leads channel to {channel.mention}.",
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

        try:
            linked_discord_id = await self.bot.ghl_client.get_linked_discord_id(contact)
        except Exception:
            logger.exception("ghl_lookup: failed to read linked Discord ID for %s", email)
            linked_discord_id = None

        discord_id_text = f"`{linked_discord_id}` (<@{linked_discord_id}>)" if linked_discord_id else "Not linked"

        raw = json.dumps(contact, indent=2)
        if len(raw) > 950:
            raw = raw[:950] + "\n... (truncated)"

        tags = ", ".join(contact.get("tags", []) or []) or "None"
        embed = discord.Embed(title="GHL Contact Record", color=discord.Color.blurple())
        embed.add_field(name="Email", value=contact.get("email", "N/A"), inline=True)
        embed.add_field(name="Contact ID", value=contact.get("id", "N/A"), inline=True)
        embed.add_field(name="Linked Discord ID", value=discord_id_text, inline=True)
        embed.add_field(name="Tags", value=tags, inline=False)
        embed.add_field(name="Raw Record", value=f"```json\n{raw}\n```", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @commands.command(name="sync")
    @commands.has_permissions(administrator=True)
    async def sync(self, ctx: commands.Context) -> None:
        """Admin-only: sync slash commands to this server. Usage: $sync"""
        if ctx.guild is None:
            await ctx.send("This command can only be used inside a server.")
            return

        await self._safe_react(ctx.message, "⏳")

        try:
            self.bot.tree.copy_global_to(guild=ctx.guild)
            synced = await self.bot.tree.sync(guild=ctx.guild)
        except discord.HTTPException:
            logger.exception("Failed to sync slash commands to guild %s", ctx.guild.id)
            await self._safe_unreact(ctx.message, "⏳")
            await self._safe_react(ctx.message, "❌")
            await ctx.send("⚠️ Failed to sync commands. Please try again.")
            return

        logger.info("Synced %s slash commands to guild %s", len(synced), ctx.guild.id)
        await self._safe_unreact(ctx.message, "⏳")
        await self._safe_react(ctx.message, "✅")
        await ctx.send(f"Synced {len(synced)} commands to this server.")
        await self.bot.send_activity_log(
            ctx.guild,
            "Slash Commands Synced",
            f"{ctx.author.mention} synced {len(synced)} slash commands to this server.",
            discord.Color.green(),
        )

    async def _safe_react(self, message: discord.Message, emoji: str) -> None:
        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            logger.warning("Could not add reaction %s to message %s", emoji, message.id)

    async def _safe_unreact(self, message: discord.Message, emoji: str) -> None:
        try:
            await message.remove_reaction(emoji, self.bot.user)
        except discord.HTTPException:
            logger.warning("Could not remove reaction %s from message %s", emoji, message.id)

    async def cog_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You do not have permission to use this command.")
        else:
            logger.exception("Message command failed", exc_info=error)
            await ctx.send("Something went wrong while running this command.")

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
