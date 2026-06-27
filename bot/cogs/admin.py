from __future__ import annotations

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
    async def status(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
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

        if self.bot.settings.course_roles:
            course_lines = []
            for name, rid in self.bot.settings.course_roles.items():
                r = interaction.guild.get_role(rid)
                role_mention = r.mention if r else f"Missing ({rid})"
                course_lines.append(f"**{name}** → {role_mention}")
            course_roles_text = "\n".join(course_lines)
        else:
            course_roles_text = "None configured (set COURSE_ROLES in .env)"

        embed = discord.Embed(
            title="Bot Status",
            color=discord.Color.green() if guild_state.bot_enabled else discord.Color.red(),
        )
        embed.add_field(name="Server", value=interaction.guild.name, inline=True)
        embed.add_field(name="Verification", value="Enabled ✅" if guild_state.bot_enabled else "Disabled ❌", inline=True)
        embed.add_field(name="Worksheet", value=self.bot.settings.google_worksheet_name, inline=True)
        embed.add_field(name="Verified Role (join-based)", value=role_text, inline=False)
        embed.add_field(name="Backlog Channel", value=backlog_channel_text, inline=True)
        embed.add_field(name="Course → Role Mapping", value=course_roles_text, inline=False)
        embed.add_field(name="Discord Latency", value=f"{latency_ms}ms", inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="toggle", description="Enable or disable the email verification system.")
    @app_commands.checks.has_permissions(administrator=True)
    async def toggle(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        guild_state = await self.bot.state_store.get_guild_state(interaction.guild.id)
        new_state = not guild_state.bot_enabled
        await self.bot.state_store.set_bot_enabled(interaction.guild.id, new_state)

        label = "enabled ✅" if new_state else "disabled ❌"
        await interaction.response.send_message(
            f"Email verification has been **{label}**.",
            ephemeral=True,
        )
        await self.bot.send_activity_log(
            interaction.guild,
            "Verification Toggled",
            f"{interaction.user.mention} {'enabled' if new_state else 'disabled'} the email verification system.",
            discord.Color.green() if new_state else discord.Color.red(),
        )

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

    @app_commands.command(name="test_member", description="Test the Google Sheet flow for a server member.")
    @app_commands.describe(member="Member to check in the Google Sheet.")
    @app_commands.checks.has_permissions(administrator=True)
    async def test_member(self, interaction: discord.Interaction, member: discord.Member) -> None:
        assert interaction.guild is not None
        await interaction.response.defer(ephemeral=True)

        current_status = await self.bot.member_store.get_member_status(member.id)
        role_text = "No role will be assigned because VERIFIED_ROLE_ID is not set."
        role_id = self.bot.settings.verified_role_id
        if role_id:
            role = interaction.guild.get_role(role_id)
            if role:
                role_text = f"If they join, the bot will assign {role.mention}."
            else:
                role_text = f"VERIFIED_ROLE_ID is set to {role_id}, but that role is missing in this server."

        embed = discord.Embed(
            title="Member Flow Test",
            color=discord.Color.green() if current_status is not None else discord.Color.orange(),
        )
        embed.add_field(name="Member", value=f"{member.mention} (`{member.id}`)", inline=False)

        if current_status is None:
            embed.add_field(name="Sheet Match", value="Not found", inline=True)
            embed.add_field(
                name="Runtime Result",
                value="Join/leave events will be ignored for this user because their Discord ID is not in the sheet.",
                inline=False,
            )
        else:
            embed.add_field(name="Sheet Match", value="Found", inline=True)
            embed.add_field(name="Current Sheet Status", value=current_status or "Blank", inline=True)
            embed.add_field(
                name="Runtime Result",
                value=(
                    "On join, the bot will write `Joined` to `Discord Status`. "
                    "On leave, it will write `Left`. "
                    f"{role_text}"
                ),
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_activity_log(
            interaction.guild,
            "Member Flow Tested",
            f"{interaction.user.mention} tested {member.mention} (`{member.id}`). "
            f"Sheet match: {'found' if current_status is not None else 'not found'}.",
            discord.Color.green() if current_status is not None else discord.Color.orange(),
        )

    @commands.command(name="sync")
    async def sync(self, ctx: commands.Context[MoreThanScalingBot]) -> None:
        """Owner-only prefix command: mts!sync."""
        if self.bot.settings.owner_ids and ctx.author.id not in self.bot.settings.owner_ids:
            return
        if not self.bot.settings.owner_ids and not await self.bot.is_owner(ctx.author):
            return

        synced = await self.bot.tree.sync()
        logger.info("Globally synced %s slash commands", len(synced))
        await ctx.reply(f"Synced {len(synced)} commands globally.", mention_author=False)
        if ctx.guild:
            await self.bot.send_activity_log(
                ctx.guild,
                "Slash Commands Synced",
                f"{ctx.author.mention} synced {len(synced)} slash commands.",
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

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: MoreThanScalingBot) -> None:
    await bot.add_cog(AdminCog(bot))
