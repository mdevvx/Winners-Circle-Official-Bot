from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.bot import MoreThanScalingBot


logger = logging.getLogger(__name__)


class EmailModal(discord.ui.Modal, title="Verify Your Membership"):
    email_input = discord.ui.TextInput(
        label="Email Address",
        placeholder="Enter the email you registered with",
        min_length=5,
        max_length=254,
    )

    def __init__(self, bot: MoreThanScalingBot) -> None:
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "❌ Could not verify your membership. Please try again.",
                ephemeral=True,
            )
            return

        member = interaction.user
        email = self.email_input.value.strip().lower()

        await interaction.response.send_message(
            "🔍 Checking your membership, please wait...",
            ephemeral=True,
        )

        guild_state = await self.bot.state_store.get_guild_state(interaction.guild.id)
        if not guild_state.bot_enabled:
            await interaction.edit_original_response(
                content="❌ The verification system is currently disabled. Please contact an admin."
            )
            return

        try:
            record = await self.bot.member_store.lookup_by_email(email)
        except Exception:
            logger.exception("Failed to lookup email %s in Google Sheet", email)
            await interaction.edit_original_response(
                content="⚠️ Could not reach the membership database. Please try again in a moment or contact an admin."
            )
            return

        if record is None:
            await interaction.edit_original_response(
                content=(
                    "❌ **Email not found.**\n\n"
                    "We couldn't find your email in our system. "
                    "Please make sure you're using the email you registered with."
                )
            )
            await self._send_backlog(interaction, email, "Not found in sheet", success=False)
            return

        if not record.is_active:
            await interaction.edit_original_response(
                content=(
                    "❌ **Membership not active.**\n\n"
                    "Your payment has not been confirmed yet. "
                    "Please complete your payment to gain access.\n\n"
                    "If you believe this is a mistake, please contact support."
                )
            )
            await self._send_backlog(interaction, email, f"Unpaid — status: {record.status}", success=False)
            return

        course = record.course.strip()
        role_id: int | None = None
        for course_name, rid in self.bot.settings.course_roles.items():
            if course_name.lower() == course.lower():
                role_id = rid
                break

        if role_id is None:
            await interaction.edit_original_response(
                content=(
                    f"⚠️ Your course (**{course or 'unknown'}**) is not configured in this server. "
                    "Please contact an admin."
                )
            )
            await self._send_backlog(interaction, email, f"No role mapped for course: {course}", success=False)
            return

        role = interaction.guild.get_role(role_id)
        if role is None:
            await interaction.edit_original_response(
                content="⚠️ The role for your course could not be found. Please contact an admin."
            )
            await self._send_backlog(interaction, email, f"Role ID {role_id} missing in server", success=False)
            return

        if role in member.roles:
            await interaction.edit_original_response(
                content=f"✅ You already have the {role.mention} role!"
            )
            return

        roles_to_add = [role]
        verified_role = None
        if self.bot.settings.verified_role_id:
            verified_role = interaction.guild.get_role(self.bot.settings.verified_role_id)
            if verified_role and verified_role not in member.roles:
                roles_to_add.append(verified_role)

        try:
            await member.add_roles(*roles_to_add, reason=f"Email verified: {email}")
            await interaction.edit_original_response(
                content=f"✅ **Verification successful!**\n\nYou've been given the {role.mention} role. Welcome!"
            )
            await self._send_backlog(interaction, email, f"Success — assigned {role.name} ({course})", success=True)
            await self.bot.send_activity_log(
                interaction.guild,
                "Member Verified",
                f"{member.mention} verified with email `{email}` and was assigned {role.mention} (course: **{course}**).",
                discord.Color.green(),
            )
        except discord.Forbidden:
            await interaction.edit_original_response(
                content="⚠️ I don't have permission to assign roles. Please contact an admin."
            )
            await self._send_backlog(interaction, email, "No permission to assign role", success=False)
        except discord.HTTPException:
            logger.exception("Failed to assign role %s to %s", role_id, member.id)
            await interaction.edit_original_response(
                content="⚠️ An error occurred while assigning your role. Please try again or contact an admin."
            )

    async def _send_backlog(
        self,
        interaction: discord.Interaction,
        email: str,
        result: str,
        success: bool,
    ) -> None:
        assert interaction.guild is not None
        guild_state = await self.bot.state_store.get_guild_state(interaction.guild.id)
        if not guild_state.backlog_channel_id:
            return

        channel = interaction.guild.get_channel(guild_state.backlog_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return

        embed = discord.Embed(
            title="Verification Attempt",
            color=discord.Color.green() if success else discord.Color.red(),
        )
        embed.add_field(
            name="User",
            value=f"{interaction.user.mention} (`{interaction.user.id}`)",
            inline=False,
        )
        embed.add_field(name="Email", value=email, inline=True)
        embed.add_field(name="Result", value=result, inline=True)
        embed.timestamp = discord.utils.utcnow()

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.exception("Failed to send to backlog channel %s", guild_state.backlog_channel_id)


class VerifyView(discord.ui.View):
    def __init__(self, bot: MoreThanScalingBot) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Verify Access",
        style=discord.ButtonStyle.primary,
        emoji="✅",
        custom_id="winners_circle:verify",
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(EmailModal(self.bot))


class VerificationSetupModal(discord.ui.Modal, title="Verification Panel Setup"):
    embed_title = discord.ui.TextInput(
        label="Title",
        placeholder="🏆 Winners Circle — Member Verification",
        max_length=256,
    )
    embed_description = discord.ui.TextInput(
        label="Description",
        placeholder="Welcome! Click the button below to verify your membership.",
        style=discord.TextStyle.paragraph,
        max_length=4000,
    )
    embed_color = discord.ui.TextInput(
        label="Embed Color (hex code, e.g. FFD700)",
        placeholder="FFD700",
        max_length=7,
        required=False,
    )
    embed_image = discord.ui.TextInput(
        label="Image URL (optional)",
        placeholder="https://example.com/banner.png",
        max_length=500,
        required=False,
    )
    embed_footer = discord.ui.TextInput(
        label="Footer Text (optional)",
        placeholder="Winners Circle",
        max_length=2048,
        required=False,
    )

    def __init__(self, bot: MoreThanScalingBot, channel: discord.TextChannel) -> None:
        super().__init__()
        self.bot = bot
        self.channel = channel

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.exception("Verification setup modal failed", exc_info=error)
        msg = "Something went wrong while setting up the panel. Please try again."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None

        color = discord.Color.gold()
        raw_color = self.embed_color.value.strip().lstrip("#")
        if raw_color:
            try:
                color = discord.Color(int(raw_color, 16))
            except ValueError:
                await interaction.response.send_message(
                    f"Invalid hex color `{raw_color}`. Use a format like `FFD700` or `#FFD700`.",
                    ephemeral=True,
                )
                return

        embed = discord.Embed(
            title=self.embed_title.value.strip(),
            description=self.embed_description.value.strip(),
            color=color,
        )

        image_url = self.embed_image.value.strip()
        if image_url:
            embed.set_image(url=image_url)

        footer_text = self.embed_footer.value.strip() or interaction.guild.name
        embed.set_footer(text=footer_text)

        try:
            await self.channel.send(embed=embed, view=VerifyView(self.bot))
        except discord.Forbidden:
            await interaction.response.send_message(
                f"I don't have permission to send messages in {self.channel.mention}.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Verification panel posted in {self.channel.mention}.",
            ephemeral=True,
        )
        await self.bot.send_activity_log(
            interaction.guild,
            "Verification Panel Posted",
            f"{interaction.user.mention} posted the verification panel in {self.channel.mention}.",
            discord.Color.gold(),
        )


class VerificationCog(commands.Cog):
    def __init__(self, bot: MoreThanScalingBot) -> None:
        self.bot = bot

    @app_commands.command(
        name="setup_verification",
        description="Post the verification panel with a Verify button in a channel.",
    )
    @app_commands.describe(channel="Channel to post the verification panel in.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_verification(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        await interaction.response.send_modal(VerificationSetupModal(self.bot, channel))

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "You do not have permission to use this command."
        else:
            logger.exception("Verification command failed", exc_info=error)
            message = "Something went wrong while running this command."

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: MoreThanScalingBot) -> None:
    await bot.add_cog(VerificationCog(bot))
    bot.add_view(VerifyView(bot))
