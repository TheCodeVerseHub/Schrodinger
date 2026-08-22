import discord  # type: ignore[import-not-found]
from discord.ext import commands  # type: ignore[import-not-found]
from discord import app_commands  # type: ignore[import-not-found]
import asyncio
import os
import sqlite3
import time
import logging
from collections import defaultdict
from typing import Optional

from config import DATABASE_NAME
from utils.helpers import register_mod_action, discard_mod_action, safe_send

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persistent tempban store.
#
# ``_schedule_unban`` is an in-memory ``asyncio.sleep`` task: if the bot
# restarts mid-ban, the task dies with the process and the tempban silently
# becomes a permanent ban. To prevent that, every tempban is recorded in the
# ``tempbans`` table of the main database and re-scheduled on startup.
# ---------------------------------------------------------------------------


def _connect() -> sqlite3.Connection:
    """Open the main bot database, creating the data dir if needed."""
    os.makedirs(os.path.dirname(DATABASE_NAME) or ".", exist_ok=True)
    # The bot may touch the DB from a task pool; be explicit about it.
    return sqlite3.connect(DATABASE_NAME, check_same_thread=False)


def _persist_tempban(guild_id: int, user_id: int, unban_at: float, reason: str) -> Optional[int]:
    """Record a tempban so it survives a bot restart; returns the row id."""
    try:
        conn = _connect()
        try:
            cur = conn.execute(
                "INSERT INTO tempbans (guild_id, user_id, unban_at, reason) VALUES (?, ?, ?, ?)",
                (guild_id, user_id, unban_at, reason),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()
    except Exception as e:
        # Best-effort: the unban task is already scheduled in-process, so a
        # failed write only means we lose restart durability for this one.
        logger.error("Failed to persist tempban for user %s in guild %s: %s", user_id, guild_id, e)
        return None


def _load_pending_tempbans() -> list[tuple[int, int, int, float, str]]:
    """Return (id, guild_id, user_id, unban_at, reason) for all pending tempbans."""
    try:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT id, guild_id, user_id, unban_at, reason FROM tempbans ORDER BY unban_at ASC"
            )
            return cur.fetchall()
        finally:
            conn.close()
    except sqlite3.Error as e:
        # Table missing (old DB before the schema landed) -- nothing to recover.
        logger.debug("Could not load tempbans table: %s", e)
        return []


def _delete_tempban(tempban_id: int) -> None:
    """Remove a fulfilled/cancelled tempban record."""
    try:
        conn = _connect()
        try:
            conn.execute("DELETE FROM tempbans WHERE id = ?", (tempban_id,))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to delete tempban record %s: %s", tempban_id, e)


class AdvancedModeration(commands.Cog):
    """Advanced moderation features with built-in safety mechanisms"""

    _CARD_COLORS: dict[str, int] = {
        "ban": 0xED4245,
        "success": 0x57F287,
        "info": 0x5865F2,
        "error": 0xED4245,
    }

    def __init__(self, bot):
        self.bot = bot
        self.command_cooldowns = defaultdict(list)

    def _check_permit(self, ctx: commands.Context, permission: str) -> bool:
        guild_perms = getattr(ctx.author, "guild_permissions", None)
        if guild_perms and getattr(guild_perms, permission, False):
            return True
        permits_cog = self.bot.get_cog("PermitSystem")
        if permits_cog and hasattr(permits_cog, "check_permit") and ctx.guild:
            return permits_cog.check_permit(ctx.author.id, ctx.guild.id, permission)
        return False

    @staticmethod
    def _mod_action_card(title, color_key, *, description="", fields=None, footer=""):
        color_val = AdvancedModeration._CARD_COLORS.get(color_key, 0x5865F2)
        container = discord.ui.Container(accent_color=discord.Color(color_val))
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

    async def cog_load(self):
        """Restore pending tempbans after a restart.

        Recovery is deferred to ``on_ready`` because guilds are not cached
        while cogs are being loaded during ``setup_hook``. An overdue tempban
        (bot was down past expiry) is executed immediately instead of
        silently becoming permanent.
        """
        self._recovery_started = False

    @commands.Cog.listener()
    async def on_ready(self):
        """Run the pending-tempban recovery once the gateway is ready."""
        if getattr(self, "_recovery_started", False):
            return
        self._recovery_started = True
        self.bot.loop.create_task(self._recover_pending_tempbans())

    async def _recover_pending_tempbans(self):
        """Reschedule (or immediately execute) tempbans found in the database."""
        pending = await asyncio.to_thread(_load_pending_tempbans)
        for tempban_id, guild_id, user_id, unban_at, _reason in pending:
            remaining = unban_at - time.time()
            guild = self.bot.get_guild(guild_id)
            if remaining <= 0:
                # Already expired while the bot was offline -- unban now.
                if guild is not None:
                    await self._execute_unban(guild, user_id, tempban_id, reason="Temporary ban expired")
                else:
                    # Bot no longer in this guild; drop the stale record.
                    await asyncio.to_thread(_delete_tempban, tempban_id)
            elif guild is not None:
                # Still in the future -- reschedule the in-process task.
                self.bot.loop.create_task(
                    self._schedule_unban(guild, user_id, delay=int(remaining), tempban_id=tempban_id)
                )
            else:
                await asyncio.to_thread(_delete_tempban, tempban_id)

    def _check_rate_limit(self, user_id: int, command: str, max_uses: int = 5, window: int = 60) -> bool:
        """Check if user is rate limited for a command (safety mechanism)"""
        now = time.time()
        user_commands = self.command_cooldowns[f"{user_id}_{command}"]
        
        # Remove old entries
        user_commands[:] = [cmd_time for cmd_time in user_commands if now - cmd_time < window]
        
        if len(user_commands) >= max_uses:
            return False  # Rate limited
        
        user_commands.append(now)
        return True

    @commands.hybrid_command(name="tempban")
    @commands.has_permissions(ban_members=True)
    @app_commands.describe(
        member="Member to temporarily ban",
        duration="Ban duration in minutes (max 10080 = 7 days)",
        reason="Reason for the ban"
    )
    async def tempban(self, ctx, member: discord.Member, duration: int, *, reason: str = "No reason provided"):
        """Temporarily ban a member (max 7 days for safety)"""
        if not self._check_permit(ctx, "ban_members"):
            return await safe_send(ctx, content="You need the 'Ban Members' permission or a matching permit to use this command.", ephemeral=True)
        if not self._check_rate_limit(ctx.author.id, "tempban", 3, 300):
            return await safe_send(ctx, content="Rate limit reached. You can only use tempban 3 times per 5 minutes. Please wait before trying again.", ephemeral=True)
        if duration > 10080:
            return await safe_send(ctx, content="The maximum tempban duration is 7 days. Choose a shorter duration.", ephemeral=True)
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await safe_send(ctx, content="Cannot ban this member. Their highest role is equal to or above yours. Only the server owner can ban members with higher roles.", ephemeral=True)
        if member == ctx.guild.owner:
            return await safe_send(ctx, content="Cannot ban the server owner. Only Discord can remove a server owner.", ephemeral=True)

        try:
            ban_reason = f"Tempban ({duration}m): {reason}"
            register_mod_action(self.bot, ctx.guild.id, member.id, ctx.author.id, ban_reason, "BAN")
            await member.ban(reason=ban_reason)
            unban_at = time.time() + duration * 60
            tempban_id = await asyncio.to_thread(_persist_tempban, ctx.guild.id, member.id, unban_at, ban_reason)
            self.bot.loop.create_task(self._schedule_unban(ctx.guild, member.id, delay=duration * 60, tempban_id=tempban_id))
            view = self._mod_action_card(
                "Temporary Ban Issued", "ban",
                description=f"**{member}** has been temporarily banned.",
                fields={
                    "User": member.display_name,
                    "Duration": f"{duration} minutes",
                    "Expires": f"<t:{int(unban_at)}:F>",
                    "Reason": reason,
                    "Moderator": ctx.author.mention,
                },
            )
            await safe_send(ctx, view=view)
        except discord.Forbidden:
            discard_mod_action(self.bot, ctx.guild.id, member.id, "BAN")
            await safe_send(ctx, content="I'm missing the 'Ban Members' permission in this server. Ask an admin to grant me that permission.", ephemeral=True)
        except Exception as e:
            discard_mod_action(self.bot, ctx.guild.id, member.id, "BAN")
            await safe_send(ctx, content=f"An error occurred: {e}. Contact an admin if this persists.", ephemeral=True)

    async def _execute_unban(self, guild: discord.Guild, user_id: int, tempban_id: Optional[int] = None, reason: str = "Temporary ban expired"):
        """Unban a user and clean up the persisted tempban record.

        Uses the current guild/user objects so it is safe to call after a
        restart (the cached ``Member`` from the command may be stale).
        """
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
        except discord.NotFound:
            user = None  # User deleted their account; unban by id still works
        try:
            await guild.unban(user or discord.Object(id=user_id), reason=reason)
        except discord.NotFound:
            # Member may have been manually unbanned (or the ban expired) -- the
            # intent is fulfilled, so clean up and treat as done.
            pass
        else:
            # Unban succeeded. Only now remove the persisted record: if the
            # unban failed (Forbidden, HTTPException, ...) the row is kept so it
            # is retried on the next restart instead of silently becoming a
            # permanent ban.
            if tempban_id is not None:
                await asyncio.to_thread(_delete_tempban, tempban_id)

    async def _schedule_unban(self, guild: discord.Guild, user_id: int, delay: int, tempban_id: Optional[int] = None):
        """Schedule automatic unban (durable: recovers after restarts)."""
        await asyncio.sleep(delay)
        try:
            await self._execute_unban(guild, user_id, tempban_id=tempban_id, reason="Temporary ban expired")
        except Exception as e:
            logger.warning("Auto-unban failed for user %s in guild %s: %s", user_id, guild.id, e)

    @commands.command(name="hide")
    @commands.has_permissions(manage_channels=True)
    async def hide_channel(self, ctx, channel: Optional[discord.TextChannel] = None):
        """Hide a channel from everyone"""
        guild = ctx.guild
        if guild is None:
            return await safe_send(ctx, content="This command can only be used in a server, not in DMs.")
        if not self._check_permit(ctx, "manage_channels"):
            return await safe_send(ctx, content="You need the 'Manage Channels' permission or a matching permit to use this command.", ephemeral=True)
        resolved_channel = channel or ctx.channel
        if not isinstance(resolved_channel, discord.TextChannel):
            return await safe_send(ctx, content="This command can only be used in text channels.", ephemeral=True)
        try:
            overwrite = resolved_channel.overwrites_for(guild.default_role)
            overwrite.view_channel = False
            await resolved_channel.set_permissions(guild.default_role, overwrite=overwrite, reason=f"Channel hidden by {ctx.author}")
            view = self._mod_action_card(
                "Channel Hidden", "info",
                description=f"**{resolved_channel.name}** has been hidden from everyone.",
                fields={"Channel": resolved_channel.mention, "Moderator": ctx.author.mention},
            )
            await safe_send(ctx, view=view)
            logging_cog = self.bot.get_cog("LoggingCog")
            if logging_cog:
                await logging_cog.log_event(event_type="CHANNEL_UPDATE", guild_id=guild.id, moderator_id=ctx.author.id, details=f"**#{resolved_channel.name}** was hidden from everyone")
        except discord.Forbidden:
            await safe_send(ctx, content="I'm missing the 'Manage Channels' permission for this channel.", ephemeral=True)
        except Exception as e:
            await safe_send(ctx, content=f"An error occurred: {e}.", ephemeral=True)

    @commands.command(name="unhide")
    @commands.has_permissions(manage_channels=True)
    async def unhide_channel(self, ctx, channel: Optional[discord.TextChannel] = None):
        """Unhide a channel for everyone"""
        guild = ctx.guild
        if guild is None:
            return await safe_send(ctx, content="This command can only be used in a server, not in DMs.")
        if not self._check_permit(ctx, "manage_channels"):
            return await safe_send(ctx, content="You need the 'Manage Channels' permission or a matching permit to use this command.", ephemeral=True)
        resolved_channel = channel or ctx.channel
        if not isinstance(resolved_channel, discord.TextChannel):
            return await safe_send(ctx, content="This command can only be used in text channels.", ephemeral=True)
        try:
            overwrite = resolved_channel.overwrites_for(guild.default_role)
            overwrite.view_channel = True
            await resolved_channel.set_permissions(guild.default_role, overwrite=overwrite, reason=f"Channel unhidden by {ctx.author}")
            view = self._mod_action_card(
                "Channel Unhidden", "success",
                description=f"**{resolved_channel.name}** is now visible to everyone.",
                fields={"Channel": resolved_channel.mention, "Moderator": ctx.author.mention},
            )
            await safe_send(ctx, view=view)
            logging_cog = self.bot.get_cog("LoggingCog")
            if logging_cog:
                await logging_cog.log_event(event_type="CHANNEL_UPDATE", guild_id=guild.id, moderator_id=ctx.author.id, details=f"**#{resolved_channel.name}** is now visible to everyone")
        except discord.Forbidden:
            await safe_send(ctx, content="I'm missing the 'Manage Channels' permission for this channel.", ephemeral=True)
        except Exception as e:
            await safe_send(ctx, content=f"An error occurred: {e}.", ephemeral=True)

    # Note: slowmode command already exists in modcog.py, so not implementing here to avoid conflicts

async def setup(bot):
    await bot.add_cog(AdvancedModeration(bot))