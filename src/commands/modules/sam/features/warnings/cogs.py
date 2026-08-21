import re
from typing import Optional, Any

import discord  # type: ignore[import-not-found]
from discord.ext import commands  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from ...internal import database, logger_config
from .services import WarnService

logger = logger_config.logger.getChild("warnings")

DEFAULT_REASON = "No reason specified."

# Accent colours for Components V2 cards.
_CARD_COLORS: dict[str, int] = {
    "warn":    0xFEE75C,
    "unwarn":  0x57F287,
    "error":   0xED4245,
    "info":    0x5865F2,
}


def _mod_card(
    title: str,
    color_key: str,
    *,
    description: str = "",
    fields: dict[str, str] | None = None,
    footer: str = "",
) -> discord.ui.LayoutView:
    """Build a compact Components V2 container."""
    container = discord.ui.Container(accent_color=discord.Color(_CARD_COLORS.get(color_key, 0x5865F2)))
    container.add_item(discord.ui.TextDisplay(f"## {title}"))
    container.add_item(discord.ui.Separator())
    if description:
        container.add_item(discord.ui.TextDisplay(description))
    if fields:
        field_lines = [f"**{k}:** {v}" for k, v in fields.items()]
        container.add_item(discord.ui.TextDisplay("\n".join(field_lines)))
    if footer:
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(f"*{footer}*"))
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(container)
    return view


class Warnings(commands.Cog):
    def __init__(
        self, bot: commands.Bot, warn_service_class: type[WarnService] | None = None
    ):
        self.bot = bot
        self.warn_service_class = warn_service_class or WarnService

    # -- Permit helper -------------------------------------------------------

    def _check_permit(self, ctx: commands.Context, permission: str) -> bool:
        """Return True if the invoking user has native Discord perms or a custom permit."""
        guild_perms = getattr(ctx.author, "guild_permissions", None)
        if guild_perms and getattr(guild_perms, permission, False):
            return True
        permits_cog: Any = self.bot.get_cog("PermitSystem")
        if permits_cog and hasattr(permits_cog, "check_permit") and ctx.guild:
            return permits_cog.check_permit(ctx.author.id, ctx.guild.id, permission)
        return False

    # -- Logging helper ------------------------------------------------------

    async def _log_warning(self, user_id: int, guild_id: int, moderator_id: int,
                           reason: str, case_id: int | None = None):
        """Send a warn event to the centralized logging system."""
        logging_cog = self.bot.get_cog("LoggingCog")
        if logging_cog and hasattr(logging_cog, "log_warning"):
            await logging_cog.log_warning(user_id, guild_id, moderator_id, reason, case_id=case_id)

    async def _log_event(self, event_type: str, user_id: int, guild_id: int,
                         moderator_id: int | None = None, reason: str | None = None):
        """Generic log helper for warn/unwarn events."""
        logging_cog = self.bot.get_cog("LoggingCog")
        if logging_cog and hasattr(logging_cog, "log_event"):
            await logging_cog.log_event(
                event_type=event_type, user_id=user_id, guild_id=guild_id,
                moderator_id=moderator_id, details=reason,
            )

    async def _send_dm(self, user_id: int, embed: discord.Embed) -> tuple[bool, str]:
        """
        Safely send a DM to a user with proper error handling.
        Returns: (success: bool, status: str)
        """
        try:
            # Try to fetch user from cache first, then from API
            user = self.bot.get_user(user_id)
            if user is None:
                user = await self.bot.fetch_user(user_id)

            if user is None:
                return False, "User not found"

            await user.send(embed=embed)
            return True, "✅ DM sent successfully"

        except discord.Forbidden:
            return False, "⚠️ User has DMs disabled or blocked the bot"
        except discord.NotFound:
            return False, "❌ User not found"
        except Exception as e:
            logger.error(f"Failed to send DM to user {user_id}: {str(e)}")
            return False, f"⚠️ Failed to send DM: {type(e).__name__}"

    @commands.hybrid_command(name="warn", description="Issue a warning to a user.")
    @commands.guild_only()
    async def warn(
        self, ctx: commands.Context, user: discord.User, *, reason: Optional[str] = None
    ):
        """
        Issue a warning to a user.
        Slash command: /warn user:@user reason:reason
        Prefix command: ?warn @user reason
        """
        if not self._check_permit(ctx, "warn_members") and not self._check_permit(ctx, "kick_members"):
            return await ctx.send("You do not have permission to warn members.")

        if reason is None:
            reason = DEFAULT_REASON

        try:
            async with database.get_session() as session:
                svc = self.warn_service_class(session)
                warn_obj = await svc.issue_warning(
                    user.id, ctx.guild.id, ctx.author.id, reason
                )

                # Send DM to the warned user
                dm_embed = discord.Embed(
                    title="Warning Issued",
                    description=f"You have received a warning in **{ctx.guild.name}**.",
                    color=discord.Color.gold(),
                )
                dm_embed.add_field(name="Case ID", value=f"#{warn_obj.id}", inline=True)
                dm_embed.add_field(name="Reason", value=reason, inline=False)
                dm_embed.add_field(name="Moderator", value=str(ctx.author), inline=True)
                dm_embed.set_footer(
                    text="Please review the rules and avoid further violations."
                )
                dm_sent, dm_status = await self._send_dm(user.id, dm_embed)

                # Log to the centralized logging channel
                await self._log_warning(user.id, ctx.guild.id, ctx.author.id, reason, case_id=warn_obj.id)

                # Send confirmation to moderator
                view = _mod_card(
                    "Warning Issued", "warn",
                    description=f"{user.mention} has been warned.",
                    fields={
                        "Case ID": f"#{warn_obj.id}",
                        "Reason": reason,
                        "Moderator": ctx.author.mention,
                        "DM Status": dm_status,
                    },
                    footer=f"User ID: {user.id}",
                )
                await ctx.send(view=view)
        except Exception as e:
            view = _mod_card(
                "Error", "error",
                description=f"Failed to issue warning: {e}",
            )
            await ctx.send(view=view)

    @commands.hybrid_command(name="unwarn", description="Remove a warning by ID.")
    @commands.guild_only()
    async def unwarn(
        self, ctx: commands.Context, case_id: int, *, reason: Optional[str] = None
    ):
        """
        Remove a warning by ID.
        Slash command: /unwarn case_id:123 reason:reason
        Prefix command: ?unwarn 123 reason
        """
        if not self._check_permit(ctx, "warn_members") and not self._check_permit(ctx, "kick_members"):
            return await ctx.send("You do not have permission to manage warnings.")

        if reason is None:
            reason = "Warning removed by moderator."

        try:
            async with database.get_session() as session:
                svc = self.warn_service_class(session)
                warn_obj = await svc.recall_warning(
                    case_id, ctx.guild.id, ctx.author.id, reason
                )

                dm_embed = discord.Embed(
                    title="Warning Removed",
                    description=f"A warning has been removed from your record in **{ctx.guild.name}**.",
                    color=discord.Color.green(),
                )
                dm_embed.add_field(name="Case ID", value=f"#{warn_obj.id}", inline=True)
                dm_embed.add_field(name="Removal Reason", value=reason, inline=False)
                dm_embed.add_field(name="Moderator", value=str(ctx.author), inline=True)
                dm_embed.set_footer(text="Keep up the good behavior!")
                dm_sent, dm_status = await self._send_dm(warn_obj.user_id, dm_embed)

                await self._log_event("WARN_REMOVED", warn_obj.user_id, ctx.guild.id, ctx.author.id, reason)

                view = _mod_card(
                    "Warning Removed", "unwarn",
                    description=f"Warning `#{case_id}` has been removed.",
                    fields={
                        "Affected User": f"<@{warn_obj.user_id}>",
                        "Removal Reason": reason,
                        "Moderator": ctx.author.mention,
                        "DM Status": dm_status,
                    },
                )
                await ctx.send(view=view)
        except ValueError as e:
            view = _mod_card("Error", "error", description=f"Warning `#{case_id}` not found or invalid.")
            await ctx.send(view=view)
        except Exception as e:
            view = _mod_card("Error", "error", description=f"Failed to remove warning: {e}")
            await ctx.send(view=view)

    @commands.hybrid_group(name="warnings", description="Manage warnings.")
    @commands.guild_only()
    async def warnings_group(self, ctx: commands.Context):
        """Warnings leaderboard; use the subcommands for detailed views.

        Prefix:
          ?warnings          -> server warnings leaderboard
          ?warnings view @user -> that user's warning history
        Slash:
          /warnings leaderboard -> server warnings leaderboard
          /warnings view user:@user -> that user's warning history
        """
        if ctx.invoked_subcommand is not None:
            return
        await self._display_leaderboard(ctx)

    @warnings_group.command(
        name="leaderboard", description="Show the warnings leaderboard for this server."
    )
    async def leaderboard(self, ctx: commands.Context):
        """Show the top warned users in this server."""
        await self._display_leaderboard(ctx)

    async def _display_leaderboard(self, ctx: commands.Context) -> None:
        """Render the server warnings leaderboard."""
        try:
            async with database.get_session() as session:
                svc = self.warn_service_class(session)
                entries = await svc.get_leaderboard(ctx.guild.id, 10)

                if not entries:
                    view = _mod_card(
                        "Warnings Leaderboard", "info",
                        description="No warnings have been issued yet in this server.",
                    )
                    await ctx.send(view=view)
                    return

                lines = []
                for i, (user_id, count) in enumerate(entries, start=1):
                    lines.append(
                        f"**{i}.** <@{user_id}> — **{count}** warning{'s' if count != 1 else ''}"
                    )

                view = _mod_card(
                    "Warnings Leaderboard", "warn",
                    description="\n".join(lines),
                    footer="Top 10 -- Revoked warnings are excluded",
                )
                await ctx.send(view=view)
        except Exception as e:
            view = _mod_card(
                "Error", "error",
                description=f"Failed to load the warnings leaderboard: {e}",
            )
            await ctx.send(view=view)

    @warnings_group.command(name="view", description="View warnings for a user.")
    async def view_warnings(self, ctx: commands.Context, user: discord.User):
        """View all warnings for a specific user."""
        await self._display_user_warnings(ctx, user)

    async def _display_user_warnings(
        self, ctx: commands.Context, user: discord.User
    ) -> None:
        """Render a user's warning history."""
        try:
            async with database.get_session() as session:
                svc = self.warn_service_class(session)
                warnings_list = await svc.get_warnings_for_user(user.id, ctx.guild.id)

                if not warnings_list:
                    view = _mod_card(
                        "No Warnings", "unwarn",
                        description=f"{user.mention} has no warnings.",
                    )
                    await ctx.send(view=view)
                    return

                active_warnings = [w for w in warnings_list if not w.revoked]
                revoked_warnings = [w for w in warnings_list if w.revoked]

                fields: dict[str, str] = {
                    "Total": f"**{len(active_warnings)}** active / **{len(revoked_warnings)}** revoked",
                }

                if active_warnings:
                    active_content = "\n".join([str(w) for w in active_warnings])
                    if len(active_content) > 1024:
                        active_content = active_content[:1024] + "..."
                    fields[f"Active ({len(active_warnings)})"] = active_content

                if revoked_warnings:
                    revoked_content = "\n".join([str(w) for w in revoked_warnings])
                    if len(revoked_content) > 1024:
                        revoked_content = revoked_content[:1024] + "..."
                    fields[f"Revoked ({len(revoked_warnings)})"] = revoked_content

                color_key = "warn" if active_warnings else "unwarn"
                view = _mod_card(
                    f"Warnings for {user.name}", color_key,
                    fields=fields,
                    footer=f"{len(active_warnings)} active, {len(revoked_warnings)} revoked",
                )
                await ctx.send(view=view)
        except Exception as e:
            view = _mod_card(
                "Error", "error",
                description=f"Failed to retrieve warnings: {e}",
            )
            await ctx.send(view=view)

    @warnings_group.command(
        name="modify", description="Modify a warning (remove/revoke it)."
    )
    async def modify_warning(
        self, ctx: commands.Context, case_id: int, *, reason: Optional[str] = None
    ):
        """Modify a warning by revoking it."""
        if not self._check_permit(ctx, "warn_members") and not self._check_permit(ctx, "kick_members"):
            return await ctx.send("You do not have permission to manage warnings.")

        if reason is None:
            reason = "Warning revoked by moderator."

        try:
            async with database.get_session() as session:
                svc = self.warn_service_class(session)
                warn_obj = await svc.recall_warning(
                    case_id, ctx.guild.id, ctx.author.id, reason
                )

                dm_embed = discord.Embed(
                    title="Warning Revoked",
                    description=f"A warning has been revoked from your record in **{ctx.guild.name}**.",
                    color=discord.Color.green(),
                )
                dm_embed.add_field(name="Case ID", value=f"#{warn_obj.id}", inline=True)
                dm_embed.add_field(name="Revoke Reason", value=reason, inline=False)
                dm_embed.add_field(name="Moderator", value=str(ctx.author), inline=True)
                dm_embed.set_footer(text="Thank you for your cooperation!")
                dm_sent, dm_status = await self._send_dm(warn_obj.user_id, dm_embed)

                await self._log_event("WARN_REVOKED", warn_obj.user_id, ctx.guild.id, ctx.author.id, reason)

                view = _mod_card(
                    "Warning Revoked", "unwarn",
                    description=f"Warning `#{case_id}` has been revoked.",
                    fields={
                        "Affected User": f"<@{warn_obj.user_id}>",
                        "Revoke Reason": reason,
                        "Moderator": ctx.author.mention,
                        "DM Status": dm_status,
                    },
                )
                await ctx.send(view=view)
        except ValueError:
            view = _mod_card("Error", "error", description=f"Warning `#{case_id}` not found or invalid.")
            await ctx.send(view=view)
        except Exception as e:
            view = _mod_card("Error", "error", description=f"Failed to modify warning: {e}")
            await ctx.send(view=view)

    @warnings_group.command(name="clear", description="Clear all warnings for a user.")
    async def clear_warnings(
        self, ctx: commands.Context, user: discord.User, *, reason: Optional[str] = None
    ):
        """Clear all warnings for a user (admin only)."""
        if not self._check_permit(ctx, "administrator"):
            return await ctx.send("You need administrator permission to clear all warnings.")

        if reason is None:
            reason = "All warnings cleared."

        try:
            async with database.get_session() as session:
                svc = self.warn_service_class(session)
                await svc.clear_warnings_for_user(
                    user.id, ctx.guild.id, ctx.author.id, reason
                )

                dm_embed = discord.Embed(
                    title="All Warnings Cleared",
                    description=f"All your warnings have been cleared in **{ctx.guild.name}**.",
                    color=discord.Color.green(),
                )
                dm_embed.add_field(name="Clear Reason", value=reason, inline=False)
                dm_embed.add_field(name="Moderator", value=str(ctx.author), inline=True)
                dm_embed.set_footer(text="Your record has been reset.")
                dm_sent, dm_status = await self._send_dm(user.id, dm_embed)

                await self._log_event("WARN_CLEARED", user.id, ctx.guild.id, ctx.author.id, reason)

                view = _mod_card(
                    "Warnings Cleared", "unwarn",
                    description=f"All warnings for {user.mention} have been cleared.",
                    fields={
                        "Clear Reason": reason,
                        "Moderator": ctx.author.mention,
                        "DM Status": dm_status,
                    },
                )
                await ctx.send(view=view)
        except Exception as e:
            view = _mod_card(
                "Error", "error",
                description=f"Failed to clear warnings: {e}",
            )
            await ctx.send(view=view)


async def setup(bot: commands.Bot) -> None:
    """Set up the warnings cog."""
    await bot.add_cog(Warnings(bot))
