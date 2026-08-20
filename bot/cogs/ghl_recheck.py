from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.bot import MoreThanScalingBot

logger = logging.getLogger(__name__)

RECHECK_INTERVAL_HOURS = 6


class GHLRecheckCog(commands.Cog):
    def __init__(self, bot: MoreThanScalingBot) -> None:
        self.bot = bot
        self.recheck_loop.start()

    @app_commands.command(
        name="ghl_recheck_now",
        description="Immediately recheck GHL tags and sync roles for all verified members (admin only).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def ghl_recheck_now(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.run_recheck()
        await interaction.followup.send("GHL recheck cycle complete. Check the logs for details.", ephemeral=True)

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "You do not have permission to use this command."
        else:
            logger.exception("GHL recheck command failed", exc_info=error)
            message = "Something went wrong while running this command."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            logger.warning("Could not deliver error response for interaction %s", interaction.id)

    def cog_unload(self) -> None:
        self.recheck_loop.cancel()

    @tasks.loop(hours=RECHECK_INTERVAL_HOURS)
    async def recheck_loop(self) -> None:
        await self.run_recheck()

    async def run_recheck(self) -> None:
        tag_roles = self.bot.settings.ghl_tag_roles
        if not tag_roles:
            logger.info("GHL recheck skipped: no GHL_TAG_ROLES configured")
            return

        checked = 0
        for guild in self.bot.guilds:
            verified = await self.bot.verified_member_store.get_all(guild.id)
            logger.info(
                "GHL recheck starting for guild %s: %s verified member(s) on record",
                guild.id,
                len(verified),
            )

            for member in guild.members:
                verified_entry = verified.get(member.id)
                if verified_entry is None:
                    continue

                checked += 1
                try:
                    await self._recheck_member(guild, member, verified_entry.email, tag_roles)
                except Exception:
                    logger.exception(
                        "GHL recheck failed unexpectedly for member %s (%s) in guild %s",
                        member.id,
                        verified_entry.email,
                        guild.id,
                    )

        logger.info("GHL recheck cycle finished: %s verified member(s) checked", checked)

    async def _recheck_member(
        self,
        guild: discord.Guild,
        member: discord.Member,
        email: str,
        tag_roles: dict[str, int],
    ) -> None:
        try:
            contact = await self.bot.ghl_client.get_contact_by_email(email)
        except Exception:
            logger.exception(
                "GHL recheck lookup failed for member %s (%s) in guild %s",
                member.id,
                email,
                guild.id,
            )
            return

        current_tags = {
            tag.strip().lower() for tag in ((contact.get("tags") if contact else None) or [])
        }

        roles_to_remove: list[discord.Role] = []
        roles_to_add: list[discord.Role] = []
        for tag_name, role_id in tag_roles.items():
            role = guild.get_role(role_id)
            if role is None:
                logger.warning(
                    "Role %s for tag '%s' is missing in guild %s", role_id, tag_name, guild.id
                )
                continue

            tag_matches = tag_name.strip().lower() in current_tags
            has_role = role in member.roles
            if tag_matches and not has_role:
                roles_to_add.append(role)
            elif not tag_matches and has_role:
                roles_to_remove.append(role)

        if roles_to_remove:
            try:
                await member.remove_roles(
                    *roles_to_remove, reason="GHL recheck: subscription tag no longer present"
                )
                logger.info(
                    "Removed roles %s from member %s in guild %s (current tags: %s)",
                    [role.id for role in roles_to_remove],
                    member.id,
                    guild.id,
                    current_tags,
                )
                await self.bot.send_activity_log(
                    guild,
                    "GHL Recheck — Role Removed",
                    f"{member.mention} no longer has a matching GHL subscription tag. "
                    f"Removed: {', '.join(role.mention for role in roles_to_remove)}.",
                    discord.Color.orange(),
                )
            except discord.Forbidden:
                logger.warning(
                    "Missing permission to remove roles from member %s in guild %s", member.id, guild.id
                )
            except discord.HTTPException:
                logger.exception("Failed to remove roles from member %s in guild %s", member.id, guild.id)

        if roles_to_add:
            try:
                await member.add_roles(
                    *roles_to_add, reason="GHL recheck: new subscription tag detected"
                )
                logger.info(
                    "Added roles %s to member %s in guild %s (current tags: %s)",
                    [role.id for role in roles_to_add],
                    member.id,
                    guild.id,
                    current_tags,
                )
                await self.bot.send_activity_log(
                    guild,
                    "GHL Recheck — Role Added",
                    f"{member.mention} has a new matching GHL subscription tag. "
                    f"Added: {', '.join(role.mention for role in roles_to_add)}.",
                    discord.Color.green(),
                )
            except discord.Forbidden:
                logger.warning(
                    "Missing permission to add roles to member %s in guild %s", member.id, guild.id
                )
            except discord.HTTPException:
                logger.exception("Failed to add roles to member %s in guild %s", member.id, guild.id)

    @recheck_loop.before_loop
    async def before_recheck_loop(self) -> None:
        await self.bot.wait_until_ready()

    @recheck_loop.error
    async def on_recheck_loop_error(self, error: BaseException) -> None:
        logger.exception("GHL recheck loop crashed; restarting it", exc_info=error)
        if not self.recheck_loop.is_running():
            self.recheck_loop.restart()


async def setup(bot: MoreThanScalingBot) -> None:
    await bot.add_cog(GHLRecheckCog(bot))
