from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.bot import MoreThanScalingBot

logger = logging.getLogger(__name__)

SUBSCRIBE_URL = "https://pajamabillionaire.com/"


def _outcome_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=discord.Color.gold())
    embed.set_footer(text="Winners Circle & Team")
    return embed


class SubscribeView(discord.ui.View):
    def __init__(self, label: str = "Join Winners Circle") -> None:
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.link,
                url=SUBSCRIBE_URL,
                emoji="🏆",
            )
        )


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

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            contact = await self.bot.ghl_client.get_contact_by_email(email)
        except Exception:
            logger.exception("Failed to lookup email %s in GHL", email)
            await interaction.edit_original_response(
                embed=_outcome_embed(
                    "⚠️ Something Went Wrong",
                    "We couldn't reach the membership database right now. Please try again in a moment or contact an admin.",
                )
            )
            return

        if contact is None:
            await interaction.edit_original_response(
                embed=_outcome_embed(
                    "🔒 We Couldn't Find Your Membership",
                    f"No account is linked to `{email}` in our system.\n\n"
                    "**Winners Circle members get:**\n"
                    "• Live access to the Trading Room\n"
                    "• The full Business in a Box toolkit\n"
                    "• Inner Circle strategy & community\n\n"
                    "Already a member? Double-check you entered the exact email you signed up with and try again. "
                    "Otherwise, tap below to join and unlock full access in minutes.",
                ),
                view=SubscribeView(label="Join Winners Circle"),
            )
            await self._send_backlog(
                interaction, email, "Not found in GHL", success=False
            )
            return

        tags = {tag.strip().lower() for tag in (contact.get("tags") or [])}
        matched_roles: list[tuple[str, int]] = [
            (tag_name, role_id)
            for tag_name, role_id in self.bot.settings.ghl_tag_roles.items()
            if tag_name.strip().lower() in tags
        ]

        if not matched_roles:
            await interaction.edit_original_response(
                embed=_outcome_embed(
                    "⏳ Your Membership Has Lapsed",
                    f"We found your account (`{email}`), but your subscription isn't active right now — "
                    "it may have expired or been cancelled.\n\n"
                    "Renew today so you don't miss the next call in the Trading Room, Business in a Box, or Inner Circle. "
                    "Tap below to pick back up right where you left off.",
                ),
                view=SubscribeView(label="Renew Membership"),
            )
            await self._send_backlog(
                interaction,
                email,
                f"No matching tag — tags: {', '.join(tags) or 'none'}",
                success=False,
            )
            return

        try:
            linked_discord_id = await self.bot.ghl_client.get_linked_discord_id(contact)
        except Exception:
            logger.exception(
                "Failed to check linked Discord ID for GHL contact %s",
                contact.get("id"),
            )
            linked_discord_id = None

        if linked_discord_id is not None and linked_discord_id != member.id:
            await interaction.edit_original_response(
                embed=_outcome_embed(
                    "❌ Email Already Linked",
                    f"The email `{email}` is already linked to another Discord account.\n\n"
                    "If you believe this is a mistake, please contact an admin.",
                )
            )
            await self._send_backlog(
                interaction,
                email,
                f"Email already linked to Discord ID {linked_discord_id}",
                success=False,
            )
            return

        roles_to_add: list[discord.Role] = []
        role_mentions: list[str] = []
        for tag_name, role_id in matched_roles:
            role = interaction.guild.get_role(role_id)
            if role is None:
                logger.warning(
                    "Role %s for tag '%s' is missing in guild %s",
                    role_id,
                    tag_name,
                    interaction.guild.id,
                )
                continue
            role_mentions.append(role.mention)
            if role not in member.roles:
                roles_to_add.append(role)

        if self.bot.settings.verified_role_id:
            verified_role = interaction.guild.get_role(
                self.bot.settings.verified_role_id
            )
            if verified_role and verified_role not in member.roles:
                roles_to_add.append(verified_role)

        await self.bot.verified_member_store.set_verified(
            interaction.guild.id, member.id, email
        )

        if linked_discord_id != member.id:
            try:
                await self.bot.ghl_client.set_contact_discord_id(
                    contact["id"], member.id
                )
            except Exception:
                logger.exception(
                    "Failed to link Discord ID to GHL contact %s", contact.get("id")
                )

        if not roles_to_add:
            await interaction.edit_original_response(
                embed=_outcome_embed(
                    "✅ Already Verified",
                    f"You already have the {', '.join(role_mentions) or 'matching'} role(s). You're all set!",
                )
            )
            return

        try:
            await member.add_roles(*roles_to_add, reason=f"GHL email verified: {email}")
            await interaction.edit_original_response(
                embed=_outcome_embed(
                    "✅ Verification Successful",
                    f"Welcome! You've been given the {', '.join(role_mentions)} role(s).",
                )
            )
            await self._send_backlog(
                interaction,
                email,
                f"Success — assigned {', '.join(role_mentions)}",
                success=True,
            )
            await self.bot.send_activity_log(
                interaction.guild,
                "Member Verified",
                f"{member.mention} verified with email `{email}` and was assigned {', '.join(role_mentions)}.",
                discord.Color.green(),
            )
        except discord.Forbidden:
            await interaction.edit_original_response(
                embed=_outcome_embed(
                    "⚠️ Missing Permissions",
                    "I don't have permission to assign your role(s). Please contact an admin.",
                )
            )
            await self._send_backlog(
                interaction, email, "No permission to assign role", success=False
            )
        except discord.HTTPException:
            logger.exception("Failed to assign roles to %s", member.id)
            await interaction.edit_original_response(
                embed=_outcome_embed(
                    "⚠️ Role Assignment Failed",
                    "An error occurred while assigning your role. Please try again or contact an admin.",
                )
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
            logger.exception(
                "Failed to send to backlog channel %s", guild_state.backlog_channel_id
            )


class VerifyButton(discord.ui.Button):
    def __init__(self, bot: MoreThanScalingBot) -> None:
        super().__init__(
            label="Get Full Access",
            style=discord.ButtonStyle.primary,
            emoji="🔑",
            custom_id="winners_circle:verify",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(EmailModal(self.bot))


class VerifyLayout(discord.ui.LayoutView):
    """Components V2 container-based verification panel."""

    def __init__(
        self,
        bot: MoreThanScalingBot,
        title: str = "🏆 Winners Circle — Membership Verification!",
        description: str = "Welcome! Click the button below to verify your membership.",
        color: discord.Color = discord.Color.gold(),
        image_url: str | None = None,
        footer_text: str | None = None,
    ) -> None:
        super().__init__(timeout=None)

        container_children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(f"## {title}\n\n{description}")
        ]
        if image_url:
            container_children.append(
                discord.ui.MediaGallery(discord.MediaGalleryItem(media=image_url))
            )
        if footer_text:
            container_children.append(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
            container_children.append(discord.ui.TextDisplay(f"-# {footer_text}"))

        self.add_item(discord.ui.Container(*container_children, accent_colour=color))
        self.add_item(discord.ui.ActionRow(VerifyButton(bot)))


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

    async def on_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
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

        layout = VerifyLayout(
            self.bot,
            title=self.embed_title.value.strip(),
            description=self.embed_description.value.strip(),
            color=color,
            image_url=self.embed_image.value.strip() or None,
            footer_text=self.embed_footer.value.strip() or interaction.guild.name,
        )

        try:
            await self.channel.send(view=layout)
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

        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            logger.warning(
                "Could not deliver error response for interaction %s", interaction.id
            )


async def setup(bot: MoreThanScalingBot) -> None:
    await bot.add_cog(VerificationCog(bot))
    bot.add_view(VerifyLayout(bot))
