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
from utils.helpers import register_mod_action, discard_mod_action

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

    def __init__(self, bot):
        self.bot = bot
        # Rate limiting for safety
        self.command_cooldowns = defaultdict(list)

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
        # Safety checks
        if not self._check_rate_limit(ctx.author.id, "tempban", 3, 300):  # 3 tempbans per 5 minutes
            await ctx.send("❌ Rate limit: You can only use tempban 3 times per 5 minutes.", ephemeral=True)
            return
            
        if duration > 10080:  # Max 7 days
            await ctx.send("❌ Maximum tempban duration is 7 days (10080 minutes)", ephemeral=True)
            return
            
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send("❌ You cannot ban someone with equal or higher role", ephemeral=True)
            return
            
        if member == ctx.guild.owner:
            await ctx.send("❌ Cannot ban the server owner", ephemeral=True)
            return

        try:
            # Note: per server policy we do not DM users for ban actions.
            
            # Register the actual invoker so the logging system attributes the
            # tempban to the moderator instead of the bot.
            ban_reason = f"Tempban ({duration}m): {reason}"
            register_mod_action(self.bot, ctx.guild.id, member.id, ctx.author.id, ban_reason, "BAN")
            
            # Ban the member
            await member.ban(reason=ban_reason)
            
            unban_at = time.time() + duration * 60
            # Persist BEFORE scheduling so a crash in between still recovers.
            tempban_id = await asyncio.to_thread(_persist_tempban, ctx.guild.id, member.id, unban_at, ban_reason)
            # Schedule the unban (the task deletes the record when it fires).
            self.bot.loop.create_task(self._schedule_unban(ctx.guild, member.id, delay=duration * 60, tempban_id=tempban_id))
            
            embed = discord.Embed(
                title="⏰ Temporary Ban Issued",
                description=f"**{member}** has been temporarily banned",
                color=0xff0000
            )
            embed.add_field(name="Duration", value=f"{duration} minutes", inline=True)
            embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.add_field(name="Unban Time", value=f"<t:{int(unban_at)}:F>", inline=False)
            
            await ctx.send(embed=embed)
            
            # Log to designated channel handled by LoggingCog (via audit logs)
            
        except discord.Forbidden:
            discard_mod_action(self.bot, ctx.guild.id, member.id, "BAN")
            await ctx.send("❌ I don't have permission to ban this member", ephemeral=True)
        except Exception as e:
            discard_mod_action(self.bot, ctx.guild.id, member.id, "BAN")
            await ctx.send(f"❌ Error occurred: {str(e)}", ephemeral=True)

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
        """Hide a channel from @everyone"""
        guild = ctx.guild
        if guild is None:
            await ctx.send("❌ This command can only be used in a server.")
            return

        resolved_channel = channel or ctx.channel

        # Type guard to ensure channel is TextChannel
        if not isinstance(resolved_channel, discord.TextChannel):
            await ctx.send("❌ This command can only be used in text channels.", ephemeral=True)
            return

        target_channel: discord.TextChannel = resolved_channel
        
        try:
            overwrite = target_channel.overwrites_for(guild.default_role)
            overwrite.view_channel = False
            await target_channel.set_permissions(guild.default_role, overwrite=overwrite, 
                                        reason=f"Channel hidden by {ctx.author}")
            
            embed = discord.Embed(
                title="👁️‍🗨️ Channel Hidden",
                description=f"**{target_channel.name}** has been hidden from @everyone",
                color=0x95a5a6
            )
            embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
            await ctx.send(embed=embed)
            
            # Log to designated channel
            logging_cog = self.bot.get_cog("LoggingCog")
            if logging_cog:
                await logging_cog.log_event(
                    event_type="CHANNEL_UPDATE",
                    guild_id=guild.id,
                    moderator_id=ctx.author.id,
                    details=f"**#{target_channel.name}** was hidden from @everyone"
                )
            
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to manage this channel", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Error occurred: {str(e)}", ephemeral=True)

    @commands.command(name="unhide")
    @commands.has_permissions(manage_channels=True)
    async def unhide_channel(self, ctx, channel: Optional[discord.TextChannel] = None):
        """Unhide a channel for @everyone"""
        guild = ctx.guild
        if guild is None:
            await ctx.send("❌ This command can only be used in a server.")
            return

        resolved_channel = channel or ctx.channel

        # Type guard to ensure channel is TextChannel
        if not isinstance(resolved_channel, discord.TextChannel):
            await ctx.send("❌ This command can only be used in text channels.", ephemeral=True)
            return

        target_channel: discord.TextChannel = resolved_channel
        
        try:
            overwrite = target_channel.overwrites_for(guild.default_role)
            overwrite.view_channel = True
            await target_channel.set_permissions(guild.default_role, overwrite=overwrite, 
                                        reason=f"Channel unhidden by {ctx.author}")
            
            embed = discord.Embed(
                title="👁️ Channel Unhidden",
                description=f"**{target_channel.name}** is now visible to @everyone",
                color=0x00ff00
            )
            embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
            await ctx.send(embed=embed)
            
            # Log to designated channel
            logging_cog = self.bot.get_cog("LoggingCog")
            if logging_cog:
                await logging_cog.log_event(
                    event_type="CHANNEL_UPDATE",
                    guild_id=guild.id,
                    moderator_id=ctx.author.id,
                    details=f"**#{target_channel.name}** is now visible to @everyone"
                )
            
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to manage this channel", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Error occurred: {str(e)}", ephemeral=True)

    # Note: slowmode command already exists in modcog.py, so not implementing here to avoid conflicts

async def setup(bot):
    await bot.add_cog(AdvancedModeration(bot))