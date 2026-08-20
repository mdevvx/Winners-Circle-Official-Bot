from __future__ import annotations

from dataclasses import dataclass, field
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.bot import MoreThanScalingBot

logger = logging.getLogger(__name__)

RECHECK_INTERVAL_HOURS = 4
MAX_LISTED_MEMBERS = 15


@dataclass
class MemberOutcome:
    member: discord.Member
    added: list[discord.Role] = field(default_factory=list)
    removed: list[discord.Role] = field(default_factory=list)
    skipped_reason: str | None = None


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
        assert interaction.guild is not None
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not self.bot.settings.ghl_tag_roles:
            await interaction.followup.send(
                "⚠️ No GHL_TAG_ROLES configured — nothing to recheck.", ephemeral=True
            )
            return

        results = await self.run_recheck()
        outcomes = results.get(interaction.guild.id, [])
        embed = self._build_summary_embed(interaction.guild, outcomes)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="ghl_link_member",
        description="Link a Discord member to a GHL contact by email and sync their roles now (admin only).",
    )
    @app_commands.describe(
        member="The Discord member to link.",
        email="The email of their GHL contact.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def ghl_link_member(
        self, interaction: discord.Interaction, member: discord.Member, email: str
    ) -> None:
        assert interaction.guild is not None
        await interaction.response.defer(ephemeral=True, thinking=True)

        email = email.strip().lower()
        try:
            contact = await self.bot.ghl_client.get_contact_by_email(email)
        except Exception:
            logger.exception("ghl_link_member: GHL lookup failed for %s", email)
            await interaction.followup.send(
                "⚠️ Failed to reach GoHighLevel. Check the token/scopes and try again.", ephemeral=True
            )
            return

        if contact is None:
            await interaction.followup.send(f"❌ No GHL contact found for `{email}`.", ephemeral=True)
            return

        try:
            existing_link = await self.bot.ghl_client.get_linked_discord_id(contact)
        except Exception:
            logger.exception("ghl_link_member: failed to read existing Discord ID link for %s", email)
            existing_link = None

        if existing_link is not None and existing_link != member.id:
            await interaction.followup.send(
                f"❌ `{email}` is already linked to a different Discord account (`{existing_link}`). "
                "Update the 'Discord ID' field in GHL first if this is a mistake.",
                ephemeral=True,
            )
            return

        try:
            await self.bot.ghl_client.set_contact_discord_id(contact["id"], member.id)
        except Exception:
            logger.exception("ghl_link_member: failed to write Discord ID for contact %s", contact.get("id"))
            await interaction.followup.send(
                "⚠️ Failed to write the Discord ID back to GHL. Nothing was changed.", ephemeral=True
            )
            return

        await self.bot.verified_member_store.set_verified(interaction.guild.id, member.id, email)

        tag_roles = self.bot.settings.ghl_tag_roles
        outcome = (
            await self._recheck_member(interaction.guild, member, email, tag_roles)
            if tag_roles
            else MemberOutcome(member=member, skipped_reason="No GHL_TAG_ROLES configured")
        )

        embed = discord.Embed(title="GHL Member Linked", color=discord.Color.gold())
        embed.add_field(name="Member", value=member.mention, inline=True)
        embed.add_field(name="Email", value=email, inline=True)
        embed.add_field(
            name="Roles Added",
            value=", ".join(role.mention for role in outcome.added) or "None",
            inline=False,
        )
        embed.add_field(
            name="Roles Removed",
            value=", ".join(role.mention for role in outcome.removed) or "None",
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_activity_log(
            interaction.guild,
            "GHL Member Manually Linked",
            f"{interaction.user.mention} linked {member.mention} to GHL contact `{email}` and synced roles.",
            discord.Color.gold(),
        )

    def _build_summary_embed(
        self, guild: discord.Guild, outcomes: list[MemberOutcome]
    ) -> discord.Embed:
        added = [outcome for outcome in outcomes if outcome.added]
        removed = [outcome for outcome in outcomes if outcome.removed]
        skipped = [outcome for outcome in outcomes if outcome.skipped_reason]
        unchanged = len(outcomes) - len(added) - len(removed) - len(skipped)

        embed = discord.Embed(
            title="GHL Recheck — Cycle Summary",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Members Checked", value=str(len(outcomes)), inline=True)
        embed.add_field(name="Roles Added", value=str(len(added)), inline=True)
        embed.add_field(name="Roles Removed", value=str(len(removed)), inline=True)
        embed.add_field(name="Skipped", value=str(len(skipped)), inline=True)
        embed.add_field(name="No Change", value=str(unchanged), inline=True)

        embed.add_field(
            name="✅ Added",
            value=self._format_outcomes(added, lambda o: o.added) or "None",
            inline=False,
        )
        embed.add_field(
            name="❌ Removed",
            value=self._format_outcomes(removed, lambda o: o.removed) or "None",
            inline=False,
        )
        if skipped:
            embed.add_field(
                name="⏭️ Skipped",
                value=self._format_skipped(skipped) or "None",
                inline=False,
            )

        embed.set_footer(text=f"Guild ID: {guild.id}")
        embed.timestamp = discord.utils.utcnow()
        return embed

    @staticmethod
    def _format_outcomes(outcomes: list[MemberOutcome], roles_of) -> str:
        lines = [
            f"{outcome.member.mention}: {', '.join(role.mention for role in roles_of(outcome))}"
            for outcome in outcomes[:MAX_LISTED_MEMBERS]
        ]
        if len(outcomes) > MAX_LISTED_MEMBERS:
            lines.append(f"...and {len(outcomes) - MAX_LISTED_MEMBERS} more")
        text = "\n".join(lines)
        return text[:1024]

    @staticmethod
    def _format_skipped(outcomes: list[MemberOutcome]) -> str:
        lines = [
            f"{outcome.member.mention}: {outcome.skipped_reason}"
            for outcome in outcomes[:MAX_LISTED_MEMBERS]
        ]
        if len(outcomes) > MAX_LISTED_MEMBERS:
            lines.append(f"...and {len(outcomes) - MAX_LISTED_MEMBERS} more")
        text = "\n".join(lines)
        return text[:1024]

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

    async def run_recheck(self) -> dict[int, list[MemberOutcome]]:
        tag_roles = self.bot.settings.ghl_tag_roles
        if not tag_roles:
            logger.info("GHL recheck skipped: no GHL_TAG_ROLES configured")
            return {}

        tag_role_ids = set(tag_roles.values())
        results: dict[int, list[MemberOutcome]] = {}
        checked = 0
        for guild in self.bot.guilds:
            verified = await self.bot.verified_member_store.get_all(guild.id)
            logger.info(
                "GHL recheck starting for guild %s: %s verified member(s) on record",
                guild.id,
                len(verified),
            )

            guild_outcomes: list[MemberOutcome] = []
            handled_member_ids: set[int] = set()

            for member in guild.members:
                verified_entry = verified.get(member.id)
                if verified_entry is None:
                    continue

                handled_member_ids.add(member.id)
                checked += 1
                try:
                    outcome = await self._recheck_member(guild, member, verified_entry.email, tag_roles)
                except Exception:
                    logger.exception(
                        "GHL recheck failed unexpectedly for member %s (%s) in guild %s",
                        member.id,
                        verified_entry.email,
                        guild.id,
                    )
                    outcome = MemberOutcome(member=member, skipped_reason="Unexpected error, see logs")
                guild_outcomes.append(outcome)

            # Catch anyone holding a configured tag-role with no local verification record on
            # file (role predates this bot's tracking, or the record was lost) — reverse-look
            # them up in GHL by Discord ID instead of requiring an email, so no admin has to
            # manually relink them.
            for member in guild.members:
                if member.id in handled_member_ids:
                    continue
                if not any(role.id in tag_role_ids for role in member.roles):
                    continue

                handled_member_ids.add(member.id)
                checked += 1
                try:
                    outcome = await self._recheck_member_by_discord_id(guild, member, tag_roles)
                except Exception:
                    logger.exception(
                        "GHL recheck (by Discord ID) failed unexpectedly for member %s in guild %s",
                        member.id,
                        guild.id,
                    )
                    outcome = MemberOutcome(member=member, skipped_reason="Unexpected error, see logs")
                guild_outcomes.append(outcome)

            results[guild.id] = guild_outcomes

        logger.info("GHL recheck cycle finished: %s verified member(s) checked", checked)
        return results

    async def _recheck_member(
        self,
        guild: discord.Guild,
        member: discord.Member,
        email: str,
        tag_roles: dict[str, int],
    ) -> MemberOutcome:
        """Rechecks a member whose email is already on file from a completed /verify."""
        try:
            contact = await self.bot.ghl_client.get_contact_by_email(email)
        except Exception:
            logger.exception(
                "GHL recheck lookup failed for member %s (%s) in guild %s",
                member.id,
                email,
                guild.id,
            )
            return MemberOutcome(member=member, skipped_reason="GHL lookup failed")

        if contact is not None:
            try:
                linked_discord_id = await self.bot.ghl_client.get_linked_discord_id(contact)
            except Exception:
                logger.exception(
                    "GHL recheck: failed to check linked Discord ID for member %s (%s) in guild %s",
                    member.id,
                    email,
                    guild.id,
                )
                return MemberOutcome(member=member, skipped_reason="Discord ID lookup failed")

            if linked_discord_id is None:
                # Not bound yet (e.g. verified before GHL linking existed). We already trust
                # this email<->member pairing since it's our own verified record, so bind it
                # now instead of requiring manual admin action.
                try:
                    await self.bot.ghl_client.set_contact_discord_id(contact["id"], member.id)
                    logger.info(
                        "GHL recheck: auto-linked Discord ID for member %s (%s) in guild %s",
                        member.id,
                        email,
                        guild.id,
                    )
                except Exception:
                    logger.exception(
                        "GHL recheck: failed to auto-link Discord ID for member %s (%s) in guild %s",
                        member.id,
                        email,
                        guild.id,
                    )
            elif linked_discord_id != member.id:
                logger.info(
                    "GHL recheck skipped for member %s (%s) in guild %s: "
                    "GHL contact's Discord ID field is bound to a different Discord account (%s)",
                    member.id,
                    email,
                    guild.id,
                    linked_discord_id,
                )
                return MemberOutcome(
                    member=member, skipped_reason="GHL contact linked to a different Discord account"
                )

        return await self._apply_tag_roles(guild, member, contact, tag_roles)

    async def _recheck_member_by_discord_id(
        self,
        guild: discord.Guild,
        member: discord.Member,
        tag_roles: dict[str, int],
    ) -> MemberOutcome:
        """Rechecks a member who holds a tag-role but has no local verification record, by
        reverse-searching GHL for a contact whose Discord ID field matches them."""
        try:
            contact = await self.bot.ghl_client.get_contact_by_discord_id(member.id)
        except Exception:
            logger.exception(
                "GHL recheck: reverse lookup by Discord ID failed for member %s in guild %s",
                member.id,
                guild.id,
            )
            return MemberOutcome(member=member, skipped_reason="GHL reverse lookup failed")

        if contact is None:
            return MemberOutcome(
                member=member,
                skipped_reason="Holds a tag-role but no linked GHL contact found — ask them to re-verify",
            )

        email = (contact.get("email") or "").strip().lower()
        if email:
            await self.bot.verified_member_store.set_verified(guild.id, member.id, email)

        return await self._apply_tag_roles(guild, member, contact, tag_roles)

    async def _apply_tag_roles(
        self,
        guild: discord.Guild,
        member: discord.Member,
        contact: dict | None,
        tag_roles: dict[str, int],
    ) -> MemberOutcome:
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

        outcome = MemberOutcome(member=member)

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
                outcome.removed = roles_to_remove
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
                outcome.added = roles_to_add
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

        return outcome

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
