from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from bot.bot import MoreThanScalingBot

logger = logging.getLogger(__name__)

RECHECK_INTERVAL_HOURS = 6


class GHLRecheckCog(commands.Cog):
    def __init__(self, bot: MoreThanScalingBot) -> None:
        self.bot = bot
        self.recheck_loop.start()

    def cog_unload(self) -> None:
        self.recheck_loop.cancel()

    @tasks.loop(hours=RECHECK_INTERVAL_HOURS)
    async def recheck_loop(self) -> None:
        tag_roles = self.bot.settings.ghl_tag_roles
        if not tag_roles:
            return

        managed_role_ids = set(tag_roles.values())

        for guild in self.bot.guilds:
            verified = await self.bot.verified_member_store.get_all(guild.id)

            for member in guild.members:
                held_managed_roles = [role for role in member.roles if role.id in managed_role_ids]
                if not held_managed_roles:
                    continue

                verified_entry = verified.get(member.id)
                if verified_entry is None:
                    logger.info(
                        "Member %s in guild %s holds a managed role but has no stored verification email; skipping recheck",
                        member.id,
                        guild.id,
                    )
                    continue

                try:
                    contact = await self.bot.ghl_client.get_contact_by_email(verified_entry.email)
                except Exception:
                    logger.exception(
                        "GHL recheck failed for member %s (%s) in guild %s",
                        member.id,
                        verified_entry.email,
                        guild.id,
                    )
                    continue

                current_tags = {
                    tag.strip().lower() for tag in ((contact.get("tags") if contact else None) or [])
                }

                roles_to_remove = [
                    role
                    for role in held_managed_roles
                    if not self._role_matches_a_tag(role.id, tag_roles, current_tags)
                ]

                if not roles_to_remove:
                    continue

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

    @staticmethod
    def _role_matches_a_tag(role_id: int, tag_roles: dict[str, int], current_tags: set[str]) -> bool:
        for tag_name, mapped_role_id in tag_roles.items():
            if mapped_role_id == role_id and tag_name.strip().lower() in current_tags:
                return True
        return False

    @recheck_loop.before_loop
    async def before_recheck_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: MoreThanScalingBot) -> None:
    await bot.add_cog(GHLRecheckCog(bot))
