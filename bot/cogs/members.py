from __future__ import annotations

import logging

import discord
from discord.ext import commands

from bot.bot import MoreThanScalingBot


logger = logging.getLogger(__name__)


class MembersCog(commands.Cog):
    def __init__(self, bot: MoreThanScalingBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        found = await self.bot.member_store.set_member_status(member.id, "Joined")
        if not found:
            await self.bot.send_activity_log(
                member.guild,
                "Member Joined",
                f"{member.mention} (`{member.id}`) joined, but their Discord ID was not found in the Google Sheet.",
                discord.Color.orange(),
            )
            return

        role_id = self.bot.settings.verified_role_id
        if not role_id:
            logger.info("No verified role is configured for guild %s", member.guild.id)
            await self.bot.send_activity_log(
                member.guild,
                "Member Joined",
                f"{member.mention} (`{member.id}`) was found in the Google Sheet. "
                "`Discord Status` was updated to `Joined`. No verified role is configured.",
                discord.Color.green(),
            )
            return

        role = member.guild.get_role(role_id)
        if not role:
            logger.warning("Configured role %s was not found in guild %s", role_id, member.guild.id)
            await self.bot.send_activity_log(
                member.guild,
                "Member Joined",
                f"{member.mention} (`{member.id}`) was found in the Google Sheet and status was updated, "
                f"but configured role `{role_id}` was not found.",
                discord.Color.orange(),
            )
            return

        try:
            await member.add_roles(role, reason="Member found in Google Sheet")
            logger.info("Assigned role %s to member %s in guild %s", role.id, member.id, member.guild.id)
            await self.bot.send_activity_log(
                member.guild,
                "Member Joined",
                f"{member.mention} (`{member.id}`) was found in the Google Sheet. "
                f"`Discord Status` was updated to `Joined` and {role.mention} was assigned.",
                discord.Color.green(),
            )
        except discord.Forbidden:
            logger.warning("Missing permission to assign role %s in guild %s", role.id, member.guild.id)
            await self.bot.send_activity_log(
                member.guild,
                "Role Assignment Failed",
                f"{member.mention} (`{member.id}`) was found in the Google Sheet, but I do not have permission "
                f"to assign {role.mention}.",
                discord.Color.red(),
            )
        except discord.HTTPException:
            logger.exception("Failed to assign role %s to member %s", role.id, member.id)
            await self.bot.send_activity_log(
                member.guild,
                "Role Assignment Failed",
                f"{member.mention} (`{member.id}`) was found in the Google Sheet, but assigning {role.mention} failed.",
                discord.Color.red(),
            )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        found = await self.bot.member_store.set_member_status(member.id, "Left")
        if found:
            await self.bot.send_activity_log(
                member.guild,
                "Member Left",
                f"{member.mention} (`{member.id}`) left. `Discord Status` was updated to `Left`.",
                discord.Color.blue(),
            )
        else:
            await self.bot.send_activity_log(
                member.guild,
                "Member Left",
                f"{member.mention} (`{member.id}`) left, but their Discord ID was not found in the Google Sheet.",
                discord.Color.orange(),
            )


async def setup(bot: MoreThanScalingBot) -> None:
    await bot.add_cog(MembersCog(bot))
