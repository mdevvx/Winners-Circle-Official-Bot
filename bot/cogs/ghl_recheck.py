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

        for guild in self.bot.guilds:
            verified = await self.bot.verified_member_store.get_all(guild.id)

            for member in guild.members:
                verified_entry = verified.get(member.id)
                if verified_entry is None:
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


async def setup(bot: MoreThanScalingBot) -> None:
    await bot.add_cog(GHLRecheckCog(bot))
