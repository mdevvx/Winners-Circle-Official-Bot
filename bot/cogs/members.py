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
        await self.bot.send_activity_log(
            member.guild,
            "Member Joined",
            f"{member.mention} (`{member.id}`) joined the server.",
            discord.Color.green(),
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await self.bot.send_activity_log(
            member.guild,
            "Member Left",
            f"{member.mention} (`{member.id}`) left the server.",
            discord.Color.red(),
        )


async def setup(bot: MoreThanScalingBot) -> None:
    await bot.add_cog(MembersCog(bot))
