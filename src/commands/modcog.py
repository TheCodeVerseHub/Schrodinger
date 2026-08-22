"""
Comprehensive moderation commands for server management
Merges functionality from moderation.py, moderation_extended.py, and sam warnings module.
"""

import discord  # type: ignore[import-not-found]
import asyncio
import re
from discord.ext import commands  # type: ignore[import-not-found]
from discord import app_commands  # type: ignore[import-not-found]
from datetime import datetime, timezone, timedelta
from typing import Optional, Union, Any, cast
from collections.abc import Awaitable, Callable
from utils.helpers import safe_send, register_mod_action, discard_mod_action
from config import (
    BOT_OWNER_ID,
    MODERATION_ROLE_ID,
    ADMIN_BYPASS_ROLE_ID,
    VERIFY_STREAM_ROLE_ID,
    VERIFY_VOICE_ROLE_ID,
    VERIFY_EMBED_ROLE_ID,
    VERIFY_JOIN_VC_ROLE_ID,
)

# SAM Module imports for warnings
try:
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401  type: ignore[import-not-found]
    from .modules.sam.internal import database, logger_config  # noqa: F401
    from .modules.sam.features.warnings.services import WarnService  # noqa: F401
    from .modules.sam.features.warnings.models import Warn  # noqa: F401
    from .modules.sam.public import logging_api  # noqa: F401
    
    SAM_AVAILABLE = True
    logger = logger_config.logger.getChild("modcog.warnings")
except ImportError:
    SAM_AVAILABLE = False
    print("Warning: SAM module not available. Warnings functionality limited.")


class ModCog(commands.Cog):
    """Comprehensive moderation commands for server management"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.lockdown_channels = set()  # Store locked down channels
        # SAM warnings are handled via the Warnings cog directly, not this cog

    # -------- Helpers --------

    async def _safe_reply(self, ctx: commands.Context, content: str | None = None, *,
                          embed: discord.Embed | None = None, view: discord.ui.View | None = None,
                          ephemeral: bool = True):
        """Unified reply for hybrid commands. Delegates to shared safe_send from helpers."""
        return await safe_send(ctx, content=content, embed=embed, view=view, ephemeral=ephemeral)

    # -- Permit helper -------------------------------------------------------

    def _check_permit(self, ctx: commands.Context, permission: str) -> bool:
        """Return True if the invoking user has native Discord perms *or* a
        matching custom permit.  ``permission`` is the canonical Discord
        permission name (e.g. ``"kick_members"``).
        """
        # Native permission check
        guild_perms = getattr(ctx.author, "guild_permissions", None)
        if guild_perms and getattr(guild_perms, permission, False):
            return True
        # Custom permit check
        permits_cog: Any = self.bot.get_cog("PermitSystem")
        if permits_cog and hasattr(permits_cog, "check_permit") and ctx.guild:
            return permits_cog.check_permit(ctx.author.id, ctx.guild.id, permission)
        return False

    # -- Components V2 moderation card builder -------------------------------

    # Accent colours keyed by action family.
    _CARD_COLORS: dict[str, int] = {
        "ban":    0xED4245,   # red
        "unban":  0x57F287,   # green
        "kick":   0xFEE75C,   # yellow/gold
        "timeout":0xFEE75C,
        "untimeout": 0x57F287,
        "warn":   0xFEE75C,
        "success":0x57F287,
        "info":   0x5865F2,   # blurple
        "error":  0xED4245,
    }

    @staticmethod
    def _mod_action_card(
        title: str,
        color_key: str,
        *,
        user: discord.Member | discord.User | None = None,
        description: str = "",
        fields: dict[str, str] | None = None,
        footer: str = "",
    ) -> discord.ui.LayoutView:
        """Build a compact Components V2 container for a mod-action confirmation.

        Returns a LayoutView ready to be sent via ``view=``.
        """
        color_val = ModCog._CARD_COLORS.get(color_key, 0x5865F2)
        accent = discord.Color(color_val)

        container = discord.ui.Container(accent_color=accent)
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

    # -------- Basic Moderation Commands --------
    
    @commands.hybrid_command(name="purge", description="Delete a number of messages from the current channel or thread.")
    @commands.bot_has_permissions(manage_messages=True)
    @commands.guild_only()
    async def purge(self, ctx: commands.Context, amount: int):
        """Delete messages (prefix: ?purge, slash: /purge). Works in channels and threads!"""
        if not self._check_permit(ctx, "manage_messages"):
            return await self._safe_reply(ctx, "You need the 'Manage Messages' permission or a matching permit to use this command.")
        if amount < 1 or amount > 100:
            return await self._safe_reply(ctx, "The amount must be a number between 1 and 100.")

        if ctx.channel is None:
            return await self._safe_reply(ctx, "This command can only be used in a server channel, not in DMs.")

        # Allow text channels, threads, and voice/stage channel text chats (when supported by the API/library).
        if not isinstance(ctx.channel, discord.abc.Messageable):
            return await self._safe_reply(ctx, "This channel type doesn't support message purging. Use a text channel or thread instead.")
        
        if ctx.interaction and not ctx.interaction.response.is_done():
            try:
                await ctx.interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        try:
            # For prefix commands, include the invoking message in the fetch window.
            limit = amount + (0 if ctx.interaction else 1)

            purge_fn = getattr(ctx.channel, "purge", None)
            if callable(purge_fn):
                deleted = await purge_fn(limit=limit)  # type: ignore[misc]
                count = len(deleted)
            else:
                # Fallback for messageable channels that don't expose `.purge()`.
                # We implement a safe version using history + bulk delete when possible.
                import datetime

                now = discord.utils.utcnow()
                bulk_threshold = now - datetime.timedelta(days=14)

                fetched = [m async for m in ctx.channel.history(limit=limit)]  # type: ignore[attr-defined]
                if not ctx.interaction and getattr(ctx, "message", None) is not None:
                    fetched = [m for m in fetched if m.id != ctx.message.id]

                targets = fetched[:amount]
                bulk_candidates = [m for m in targets if m.created_at > bulk_threshold]
                old_messages = [m for m in targets if m.created_at <= bulk_threshold]

                count = 0

                delete_messages_fn = getattr(ctx.channel, "delete_messages", None)
                if callable(delete_messages_fn) and len(bulk_candidates) > 1:
                    try:
                        delete_messages = cast(Callable[[list[Any]], Awaitable[Any]], delete_messages_fn)
                        await delete_messages(bulk_candidates)
                        count += len(bulk_candidates)
                    except Exception:
                        # Fall back to individual deletes if bulk delete isn't supported.
                        for m in bulk_candidates:
                            try:
                                await m.delete()
                                count += 1
                            except Exception:
                                pass
                else:
                    for m in bulk_candidates:
                        try:
                            await m.delete()
                            count += 1
                        except Exception:
                            pass

                for m in old_messages:
                    try:
                        await m.delete()
                        count += 1
                    except Exception:
                        pass
            
            # For slash commands (interactions), ephemeral already auto-hides
            # For prefix commands, send regular message and delete after 5s
            if ctx.interaction:
                await self._safe_reply(ctx, f"Deleted {count} messages.")
            else:
                msg = await ctx.send(
                    f"Deleted {count} messages.\n-# This message will be deleted in 5 seconds",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                await msg.delete(delay=5)
        except discord.Forbidden:
            await self._safe_reply(ctx, "I'm missing the 'Manage Messages' permission in this channel. Ask an admin to grant me that permission.")
        except Exception as e:
            await self._safe_reply(ctx, f"Failed to purge messages: {e}")

    @commands.hybrid_command(name="kick", description="Kick a member from the server.")
    @commands.bot_has_permissions(kick_members=True)
    @commands.guild_only()
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
        if not self._check_permit(ctx, "kick_members"):
            return await self._safe_reply(ctx, "You need the 'Kick Members' permission or a matching permit to use this command.")

        if ctx.guild is None:
            return await self._safe_reply(ctx, "This command can only be used in a server, not in DMs.")
        if member == ctx.author:
            return await self._safe_reply(ctx, "You cannot kick yourself. Use this command on another member.")
        if isinstance(member, discord.Member) and isinstance(ctx.author, discord.Member) and ctx.guild is not None:
            if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
                return await self._safe_reply(ctx, "Cannot complete this action. Their highest role is equal to or above yours. Only the server owner can act on members with higher roles.")
        try:
            register_mod_action(self.bot, ctx.guild.id, member.id, ctx.author.id, reason, "KICK")
            await member.kick(reason=reason)
            view = self._mod_action_card(
                "Member Kicked", "kick",
                user=member,
                description=f"**{member}** was kicked from the server.",
                fields={"User": f'{member.display_name} ({member.id})', "Reason": reason, "Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
                footer=f"User ID: {member.id}",
            )
            await self._safe_reply(ctx, view=view)

        except discord.Forbidden:
            discard_mod_action(self.bot, ctx.guild.id, member.id, "KICK")
            await self._safe_reply(ctx, "I'm missing the 'Kick Members' permission in this server. Ask an admin to grant me that permission in Server Settings > Roles.")
        except Exception as e:
            discard_mod_action(self.bot, ctx.guild.id, member.id, "KICK")
            await self._safe_reply(ctx, f"An unexpected error occurred: {e}")

    @commands.hybrid_command(name="ban", description="Ban a member from the server.")
    @commands.bot_has_permissions(ban_members=True)
    @commands.guild_only()
    async def ban(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
        if not self._check_permit(ctx, "ban_members"):
            return await self._safe_reply(ctx, "You need the 'Ban Members' permission or a matching permit to use this command.")

        if ctx.guild is None:
            return await self._safe_reply(ctx, "This command can only be used in a server, not in DMs.")
        if member == ctx.author:
            return await self._safe_reply(ctx, "You cannot ban yourself. Use this command on another member.")
        if isinstance(member, discord.Member) and isinstance(ctx.author, discord.Member) and ctx.guild is not None:
            if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
                return await self._safe_reply(ctx, "Cannot complete this action. Their highest role is equal to or above yours. Only the server owner can act on members with higher roles.")
        try:
            register_mod_action(self.bot, ctx.guild.id, member.id, ctx.author.id, reason, "BAN")
            await member.ban(reason=reason)
            view = self._mod_action_card(
                "Member Banned", "ban",
                user=member,
                description=f"**{member}** has been banned from the server.",
                fields={"User": f'{member.display_name} ({member.id})', "Reason": reason, "Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
            )
            await self._safe_reply(ctx, view=view)

        except discord.Forbidden:
            discard_mod_action(self.bot, ctx.guild.id, member.id, "BAN")
            await self._safe_reply(ctx, "I'm missing the 'Ban Members' permission in this server. Ask an admin to grant me that permission in Server Settings > Roles.")
        except Exception as e:
            discard_mod_action(self.bot, ctx.guild.id, member.id, "BAN")
            await self._safe_reply(ctx, f"An unexpected error occurred: {e}")

    @commands.hybrid_command(name="unban", description="Unban a previously banned user (use their ID).")
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self, ctx: commands.Context, user_id: int):
        if not self._check_permit(ctx, "ban_members"):
            return await self._safe_reply(ctx, "You need the 'Ban Members' permission or a matching permit to unban users.")
        if ctx.guild is None:
            return await self._safe_reply(ctx, "This command can only be used in a server, not in DMs.")
        try:
            user = await self.bot.fetch_user(user_id)
        except discord.NotFound:
            return await self._safe_reply(ctx, "No user found with that ID. Make sure you are using the correct numeric user ID.")

        try:
            await ctx.guild.fetch_ban(user)
        except discord.NotFound:
            return await self._safe_reply(ctx, "That user is not currently banned from this server.")

        try:
            unban_reason = f"Unbanned by {ctx.author}"
            register_mod_action(self.bot, ctx.guild.id, user.id, ctx.author.id, unban_reason, "UNBAN")
            await ctx.guild.unban(user, reason=unban_reason)
            view = self._mod_action_card(
                "Member Unbanned", "unban",
                description=f"**{user}** has been unbanned.",
                fields={"User": f'{user.display_name} ({user.id})', "Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
            )
            await self._safe_reply(ctx, view=view)
        except discord.Forbidden:
            discard_mod_action(self.bot, ctx.guild.id, user.id, "UNBAN")
            await self._safe_reply(ctx, "I'm missing the 'Ban Members' permission in this server. Ask an admin to grant me that permission.")
        except Exception as e:
            discard_mod_action(self.bot, ctx.guild.id, user.id, "UNBAN")
            await self._safe_reply(ctx, f"An unexpected error occurred: {e}")

    # -------- Advanced Moderation Commands --------
    
    @commands.hybrid_command(name="softban", help="Kick a user and delete their messages")
    @app_commands.describe(user="The user to softban", reason="Reason for the softban")
    @commands.bot_has_permissions(ban_members=True)
    @commands.guild_only()
    async def softban(self, ctx: commands.Context, user: discord.Member, *, reason: str = "No reason provided"):
        """Ban and immediately unban a user to delete their recent messages"""
        if not self._check_permit(ctx, "ban_members"):
            return await self._safe_reply(ctx, "You need the 'Ban Members' permission or a matching permit to use this command.")
        if ctx.guild is None:
            return await self._safe_reply(ctx, "This command can only be used in a server, not in DMs.")
        if user == ctx.author:
            return await self._safe_reply(ctx, "You cannot softban yourself. Use this command on another member.")
        if isinstance(ctx.author, discord.Member) and ctx.guild is not None:
            if user.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
                return await self._safe_reply(ctx, "Cannot softban this member. Their highest role is equal to or above yours. Only the server owner can softban members with higher roles.")
        try:
            ban_reason = f"[SOFTBAN] {reason}"
            unban_reason = f"Softban by {ctx.author}"
            register_mod_action(self.bot, ctx.guild.id, user.id, ctx.author.id, ban_reason, "BAN")
            await user.ban(reason=ban_reason, delete_message_days=1)
            register_mod_action(self.bot, ctx.guild.id, user.id, ctx.author.id, unban_reason, "UNBAN")
            await ctx.guild.unban(user, reason=unban_reason)
            view = self._mod_action_card(
                "Member Softbanned", "kick",
                user=user,
                description=f"**{user}** was softbanned. Messages deleted, user can rejoin.",
                fields={"User": f'{user.display_name} ({user.id})', "Reason": reason, "Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
                footer=f"User ID: {user.id}",
            )
            await self._safe_reply(ctx, view=view)
        except discord.Forbidden:
            discard_mod_action(self.bot, ctx.guild.id, user.id, "BAN")
            discard_mod_action(self.bot, ctx.guild.id, user.id, "UNBAN")
            await self._safe_reply(ctx, "I'm missing the 'Ban Members' permission in this server. Ask an admin to grant me that permission.")
        except Exception as e:
            discard_mod_action(self.bot, ctx.guild.id, user.id, "BAN")
            discard_mod_action(self.bot, ctx.guild.id, user.id, "UNBAN")
            await self._safe_reply(ctx, f"Failed to softban: {e}")

    @commands.hybrid_command(name="clean", help="Delete bot messages and command invocations")
    @app_commands.describe(count="Number of messages to check (default 100)")
    @commands.bot_has_permissions(manage_messages=True)
    @commands.guild_only()
    async def clean(self, ctx: commands.Context, count: int = 100):
        """Delete bot messages and command invocations from the channel"""
        if not self._check_permit(ctx, "manage_messages"):
            return await self._safe_reply(ctx, "You need the 'Manage Messages' permission or a matching permit to use this command.")
        if count < 1 or count > 1000:
            return await self._safe_reply(ctx, "The count must be a number between 1 and 1000.")
        if not isinstance(ctx.channel, discord.TextChannel):
            return await self._safe_reply(ctx, "This command can only be used in text channels, not in voice channels or DMs.")

        def is_bot_message(msg):
            return msg.author.bot or msg.content.startswith(('/', '!', '?'))

        try:
            deleted = await ctx.channel.purge(limit=count, check=is_bot_message)
            view = self._mod_action_card(
                "Messages Cleaned", "success",
                description=f"Deleted **{len(deleted)}** bot/command messages from the last {count} messages.",
                fields={"Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
            )
            msg = await self._safe_reply(ctx, view=view)
            if msg:
                await msg.delete(delay=5)
        except discord.Forbidden:
            await self._safe_reply(ctx, "I'm missing the 'Manage Messages' permission in this channel. Ask an admin to grant me that permission.")
        except Exception as e:
            await self._safe_reply(ctx, f"Failed to clean messages: {e}")

    @commands.hybrid_command(name="role", help="Toggle a role for a user")
    @app_commands.describe(user="Member to toggle role for", role="The role to toggle")
    @commands.has_permissions(manage_roles=True)
    @commands.guild_only()
    async def role(self, ctx: commands.Context, user: discord.Member, *, role: discord.Role):
        """Add or remove a role from a user"""
        assert ctx.guild is not None

        try:
            if role in user.roles:
                register_mod_action(self.bot, ctx.guild.id, user.id, ctx.author.id, f"Role toggle by {ctx.author}", "ROLE_REMOVE")
                await user.remove_roles(role, reason=f"Role toggle by {ctx.author}")
                view = self._mod_action_card(
                    "Role Removed", "error",
                    description=f"Removed {role.name} from {user.display_name}.",
                    fields={"User": f'{user.display_name} ({user.id})', "Role": role.name, "Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
                )
            else:
                register_mod_action(self.bot, ctx.guild.id, user.id, ctx.author.id, f"Role toggle by {ctx.author}", "ROLE_ADD")
                await user.add_roles(role, reason=f"Role toggle by {ctx.author}")
                view = self._mod_action_card(
                    "Role Added", "success",
                    description=f"Added {role.name} to {user.display_name}.",
                    fields={"User": f'{user.display_name} ({user.id})', "Role": role.name, "Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
                )
            await self._safe_reply(ctx, view=view)
        except discord.Forbidden:
            discard_mod_action(self.bot, ctx.guild.id, user.id, "ROLE_ADD")
            discard_mod_action(self.bot, ctx.guild.id, user.id, "ROLE_REMOVE")
            await self._safe_reply(ctx, "I'm missing the 'Manage Roles' permission. Ask an admin to grant me that permission in Server Settings > Roles.")
        except Exception as e:
            discard_mod_action(self.bot, ctx.guild.id, user.id, "ROLE_ADD")
            discard_mod_action(self.bot, ctx.guild.id, user.id, "ROLE_REMOVE")
            await self._safe_reply(ctx, f"Failed to toggle role: {e}")

    @commands.hybrid_command(name="addmod", help="Add the moderator role to a user")
    @app_commands.describe(user="Member to promote to moderator")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def addmod(self, ctx: commands.Context, user: discord.Member):
        """Promote a user to moderator"""
        if ctx.guild is None:
             return await ctx.send("This command can only be used in a server, not in DMs.", allowed_mentions=discord.AllowedMentions.none())

        MOD_ROLE_ID = MODERATION_ROLE_ID
        role = ctx.guild.get_role(MOD_ROLE_ID)
        
        if not role:
            await ctx.send(f"The moderator role (ID: {MOD_ROLE_ID}) does not exist in this server. Ask an admin to create it or update the MODERATION_ROLE_ID in the bot config.", allowed_mentions=discord.AllowedMentions.none())
            return
            
        if role in user.roles:
            await ctx.send(f"{user.display_name} already has the moderator role.", allowed_mentions=discord.AllowedMentions.none())
            return
            
        try:
            register_mod_action(self.bot, ctx.guild.id, user.id, ctx.author.id, f"Promoted to Moderator by {ctx.author}", "ROLE_ADD")
            await user.add_roles(role, reason=f"Promoted to Moderator by {ctx.author}")
            view = self._mod_action_card(
                "Staff Addition", "info",
                description=f"Successfully made {user.display_name} a staff member.",
                fields={"User": f'{user.display_name} ({user.id})', "Role": role.name, "Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
            )
            await self._safe_reply(ctx, view=view)
        except discord.Forbidden:
            discard_mod_action(self.bot, ctx.guild.id, user.id, "ROLE_ADD")
            await self._safe_reply(ctx, "I'm missing the 'Manage Roles' permission. Ask an admin to grant me that permission.")
        except Exception as e:
            discard_mod_action(self.bot, ctx.guild.id, user.id, "ROLE_ADD")
            await self._safe_reply(ctx, f"Failed to promote user: {e}")

    @commands.hybrid_command(name="timeout", aliases=["mute"], help="Timeout a member for a specified duration")
    @app_commands.describe(
        member="Member to timeout",
        duration="Duration (e.g., 10m, 2h, 1d)",
        reason="Reason for the timeout",
        appeal="Whether the user can appeal this timeout (default: True)",
    )
    @commands.bot_has_permissions(moderate_members=True)
    @commands.guild_only()
    async def timeout(
        self, ctx: commands.Context, member: discord.Member, duration: str,
        *, reason: str = "No reason provided", appeal: Optional[bool] = None,
    ):
        """Timeout a member. Slash: /timeout ... appeal:False  Prefix: ?mute ... reason ?a (non-appealable)"""
        if not self._check_permit(ctx, "moderate_members"):
            return await self._safe_reply(ctx, "You need the 'Moderate Members' permission or a matching permit to use this command.")
        if member == ctx.author:
            return await self._safe_reply(ctx, "You cannot timeout yourself. Use this command on another member.")
        if isinstance(ctx.author, discord.Member) and ctx.guild is not None:
            if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
                return await self._safe_reply(ctx, "Cannot complete this action. Their highest role is equal to or above yours. Only the server owner can act on members with higher roles.")

        # Parse ?a tag from prefix reason (e.g. "spam ?a" -> non-appealable)
        appealable = True
        if appeal is not None:
            appealable = appeal
        if "?a" in reason.lower():
            appealable = False
            reason = re.sub(r"\s*\?a\s*", "", reason, flags=re.IGNORECASE).strip() or "No reason provided"
        if not appealable and reason == "No reason provided":
            reason = "No reason provided"

        # Parse duration
        time_regex = re.compile(r"(\d+)([smhd])")
        matches = time_regex.findall(duration.lower())
        if not matches:
            return await self._safe_reply(ctx, "Invalid duration format. Use a number followed by s (seconds), m (minutes), h (hours), or d (days). Examples: 30m, 2h, 1d, 12h30m.")

        total_seconds = 0
        for value, unit in matches:
            value = int(value)
            if unit == 's':
                total_seconds += value
            elif unit == 'm':
                total_seconds += value * 60
            elif unit == 'h':
                total_seconds += value * 3600
            elif unit == 'd':
                total_seconds += value * 86400

        if total_seconds < 60:
            return await self._safe_reply(ctx, "Discord requires timeouts to be at least 1 minute long.")
        if total_seconds > 2419200:
            return await self._safe_reply(ctx, "Discord limits timeouts to a maximum of 28 days.")

        try:
            timeout_until = datetime.now(timezone.utc) + timedelta(seconds=total_seconds)
            register_mod_action(self.bot, ctx.guild.id, member.id, ctx.author.id, reason, "TIMEOUT_APPLIED")
            # Embed appealable flag in the audit reason so appeals.py can detect it.
            appeal_tag = "appealable:true" if appealable else "appealable:false"
            audit_reason = f"{reason} | By: {ctx.author} ({ctx.author.id}) | {appeal_tag}"
            await member.timeout(timeout_until, reason=audit_reason)
            appeal_text = "Appealable" if appealable else "Non-appealable"
            view = self._mod_action_card(
                "Member Timed Out", "timeout",
                user=member,
                description=f"**{member}** has been timed out.",
                fields={
                    "User": f'{member.display_name} ({member.id})',
                    "Duration": duration,
                    "Expires": f"<t:{int(timeout_until.timestamp())}:F>",
                    "Reason": reason,
                    "Appeal": appeal_text,
                    "Moderator": f'{ctx.author.display_name} ({ctx.author.id})',
                },
            )
            await self._safe_reply(ctx, view=view)
        except discord.Forbidden:
            discard_mod_action(self.bot, ctx.guild.id, member.id, "TIMEOUT_APPLIED")
            await self._safe_reply(ctx, "I'm missing the 'Moderate Members' permission in this server. Ask an admin to grant me that permission.")
        except Exception as e:
            discard_mod_action(self.bot, ctx.guild.id, member.id, "TIMEOUT_APPLIED")
            await self._safe_reply(ctx, f"Failed to timeout: {e}")

    @commands.hybrid_command(name="untimeout", aliases=["unmute"], help="Remove timeout from a member")
    @app_commands.describe(member="Member to remove timeout from", reason="Reason for removing timeout")
    @commands.bot_has_permissions(moderate_members=True)
    @commands.guild_only()
    async def untimeout(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
        """Remove timeout from a member"""
        if not self._check_permit(ctx, "moderate_members"):
            return await self._safe_reply(ctx, "You need the 'Moderate Members' permission or a matching permit to remove timeouts.")
        if not member.timed_out_until:
            return await self._safe_reply(ctx, f"{member.display_name} is not timed out.")

        try:
            register_mod_action(self.bot, ctx.guild.id, member.id, ctx.author.id, reason, "TIMEOUT_REMOVED")
            audit_reason = f"{reason} | By: {ctx.author} ({ctx.author.id})"
            await member.timeout(None, reason=audit_reason)
            view = self._mod_action_card(
                "Timeout Removed", "untimeout",
                user=member,
                description=f"Timeout removed from **{member}**.",
                fields={"User": f'{member.display_name} ({member.id})', "Reason": reason, "Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
            )
            await self._safe_reply(ctx, view=view)
        except discord.Forbidden:
            discard_mod_action(self.bot, ctx.guild.id, member.id, "TIMEOUT_REMOVED")
            await self._safe_reply(ctx, "I'm missing the 'Moderate Members' permission in this server. Ask an admin to grant me that permission.")
        except Exception as e:
            discard_mod_action(self.bot, ctx.guild.id, member.id, "TIMEOUT_REMOVED")
            await self._safe_reply(ctx, f"Failed to remove timeout: {e}")

    @commands.hybrid_command(name="slowmode", help="View or set slowmode delay for the current channel")
    @app_commands.describe(seconds="Slowmode delay in seconds (0 to disable, max 21600)")
    @commands.bot_has_permissions(manage_channels=True)
    @commands.guild_only()
    async def slowmode(self, ctx: commands.Context, seconds: Optional[int] = None):
        """View or set slowmode delay for the current channel"""
        if not self._check_permit(ctx, "manage_channels"):
            return await self._safe_reply(ctx, "You need the 'Manage Channels' permission or a matching permit to change slowmode.")
        if not isinstance(ctx.channel, (discord.TextChannel, discord.Thread)):
            return await self._safe_reply(ctx, "This command can only be used in text channels or threads.")

        if seconds is None:
            current_delay = getattr(ctx.channel, "slowmode_delay", 0) or 0
            view = self._mod_action_card(
                "Current Slowmode", "info",
                description=f"Slowmode in {ctx.channel.mention} is **{current_delay} seconds**.\nUse `?slowmode <seconds>` to change it.",
            )
            return await self._safe_reply(ctx, view=view)

        if seconds < 0 or seconds > 21600:
            return await self._safe_reply(ctx, "The delay must be between 0 (disable) and 21600 seconds (6 hours).")

        try:
            await ctx.channel.edit(slowmode_delay=seconds, reason=f"Slowmode set by {ctx.author}")
            if seconds == 0:
                view = self._mod_action_card(
                    "Slowmode Disabled", "success",
                    description=f"Slowmode has been disabled in {ctx.channel.mention}.",
                    fields={"Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
                )
            else:
                view = self._mod_action_card(
                    "Slowmode Enabled", "info",
                    description=f"Slowmode set to **{seconds}** seconds in {ctx.channel.mention}.",
                    fields={"Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
                )
            await self._safe_reply(ctx, view=view)
        except discord.Forbidden:
            await self._safe_reply(ctx, "I'm missing the 'Manage Channels' permission for this channel. Ask an admin to grant me that permission.")
        except Exception as e:
            await self._safe_reply(ctx, f"Failed to set slowmode: {e}")

    @commands.hybrid_command(name="lock", help="Lock a channel or thread to prevent members from sending messages")
    @app_commands.describe(channel="Channel/thread to lock (optional, defaults to current)")
    @commands.bot_has_permissions(manage_channels=True, manage_threads=True)
    @commands.guild_only()
    async def lock(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Lock a channel or thread to prevent members from sending messages"""
        if not self._check_permit(ctx, "manage_channels"):
            return await self._safe_reply(ctx, "You need the 'Manage Channels' permission or a matching permit to lock channels.")

        # Handle threads
        if isinstance(ctx.channel, discord.Thread):
            thread = ctx.channel
            try:
                await thread.edit(locked=True)
                new_name = thread.name
                if not new_name.startswith("🔒"):
                    new_name = f"🔒 {thread.name}"
                    await thread.edit(name=new_name, reason=f"Thread locked by {ctx.author}")
                view = self._mod_action_card(
                    "Thread Locked", "info",
                    description=f"**{new_name}** has been locked.",
                    fields={"Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
                )
                await self._safe_reply(ctx, view=view)
            except discord.Forbidden:
                await self._safe_reply(ctx, "I'm missing the 'Manage Threads' permission. Ask an admin to grant me that permission.")
            except Exception as e:
                await self._safe_reply(ctx, f"Failed to lock thread: {e}")
            return

        # Handle text channels
        assert ctx.guild is not None
        target_channel = channel if isinstance(channel, discord.TextChannel) else (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if target_channel is None:
            return await self._safe_reply(ctx, "This command can only be used on text channels or threads.")

        try:
            overwrites = target_channel.overwrites_for(ctx.guild.default_role)
            overwrites.send_messages = False
            await target_channel.set_permissions(ctx.guild.default_role, overwrite=overwrites, reason=f"Channel locked by {ctx.author}")
            self.lockdown_channels.add(target_channel.id)
            view = self._mod_action_card(
                "Channel Locked", "error",
                description=f"{target_channel.mention} has been locked. Members cannot send messages.",
                fields={"Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
            )
            await self._safe_reply(ctx, view=view)
        except discord.Forbidden:
            await self._safe_reply(ctx, "I'm missing the 'Manage Channels' permission for this channel. Ask an admin to grant me that permission.")
        except Exception as e:
            await self._safe_reply(ctx, f"Failed to lock channel: {e}")

    @commands.hybrid_command(name="unlock", help="Unlock a previously locked channel or thread")
    @app_commands.describe(channel="Channel/thread to unlock (optional, defaults to current)")
    @commands.bot_has_permissions(manage_channels=True, manage_threads=True)
    @commands.guild_only()
    async def unlock(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Unlock a channel or thread to allow members to send messages"""
        if not self._check_permit(ctx, "manage_channels"):
            return await self._safe_reply(ctx, "You need the 'Manage Channels' permission or a matching permit to unlock channels.")

        # Handle threads
        if isinstance(ctx.channel, discord.Thread):
            thread = ctx.channel
            try:
                await thread.edit(locked=False)
                new_name = thread.name
                if new_name.startswith("🔒"):
                    new_name = new_name[len("🔒"):].lstrip()
                    await thread.edit(name=new_name, reason=f"Thread unlocked by {ctx.author}")
                view = self._mod_action_card(
                    "Thread Unlocked", "success",
                    description=f"**{new_name}** has been unlocked.",
                    fields={"Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
                )
                await self._safe_reply(ctx, view=view)
            except discord.Forbidden:
                await self._safe_reply(ctx, "I'm missing the 'Manage Threads' permission. Ask an admin to grant me that permission.")
            except Exception as e:
                await self._safe_reply(ctx, f"Failed to unlock thread: {e}")
            return

        # Handle text channels
        assert ctx.guild is not None
        target_channel = channel if isinstance(channel, discord.TextChannel) else (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if target_channel is None:
            return await self._safe_reply(ctx, "This command can only be used on text channels or threads.")

        try:
            overwrites = target_channel.overwrites_for(ctx.guild.default_role)
            overwrites.send_messages = None
            await target_channel.set_permissions(ctx.guild.default_role, overwrite=overwrites, reason=f"Channel unlocked by {ctx.author}")
            self.lockdown_channels.discard(target_channel.id)
            view = self._mod_action_card(
                "Channel Unlocked", "success",
                description=f"{target_channel.mention} has been unlocked.",
                fields={"Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
            )
            await self._safe_reply(ctx, view=view)
        except discord.Forbidden:
            await self._safe_reply(ctx, "I'm missing the 'Manage Channels' permission for this channel. Ask an admin to grant me that permission.")
        except Exception as e:
            await self._safe_reply(ctx, f"Failed to unlock channel: {e}")

    @commands.hybrid_command(name="lockdown", help="Lock all channels in the server")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True)
    @commands.guild_only()
    async def lockdown(self, ctx: commands.Context):
        """Lock all channels in the server"""
        assert ctx.guild is not None
        await self._safe_reply(ctx, "Initiating server lockdown...")
        locked_count = 0
        failed_count = 0
        for channel in ctx.guild.text_channels:
            try:
                overwrites = channel.overwrites_for(ctx.guild.default_role)
                overwrites.send_messages = False
                await channel.set_permissions(ctx.guild.default_role, overwrite=overwrites, reason=f"Server lockdown by {ctx.author}")
                self.lockdown_channels.add(channel.id)
                locked_count += 1
            except (discord.Forbidden, Exception):
                failed_count += 1
        desc = f"Successfully locked **{locked_count}** channels."
        if failed_count > 0:
            desc += f"\n{failed_count} channels could not be locked."
        view = self._mod_action_card(
            "Server Lockdown", "error",
            description=desc,            fields={"Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
        )
        await self._safe_reply(ctx, view=view)


    @commands.hybrid_command(name="unlockdown", help="Unlock all previously locked channels")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True)
    @commands.guild_only()
    async def unlockdown(self, ctx: commands.Context):
        """Unlock all previously locked channels"""
        assert ctx.guild is not None
        if not self.lockdown_channels:
            return await self._safe_reply(ctx, "No channels are currently locked down. Use ?lockdown to lock all channels first.")
        await self._safe_reply(ctx, "Removing server lockdown...")
        unlocked_count = 0
        failed_count = 0
        for channel_id in list(self.lockdown_channels):
            channel = ctx.guild.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                try:
                    overwrites = channel.overwrites_for(ctx.guild.default_role)
                    overwrites.send_messages = None
                    await channel.set_permissions(ctx.guild.default_role, overwrite=overwrites, reason=f"Lockdown removed by {ctx.author}")
                    self.lockdown_channels.discard(channel_id)
                    unlocked_count += 1
                except (discord.Forbidden, Exception):
                    failed_count += 1
        desc = f"Successfully unlocked **{unlocked_count}** channels."
        if failed_count > 0:
            desc += f"\n{failed_count} channels could not be unlocked."
        view = self._mod_action_card(
            "Lockdown Removed", "success",
            description=desc,
            fields={"Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
        )
        await self._safe_reply(ctx, view=view)

    @commands.hybrid_command(name="nuke", help="Clone and delete a channel to clear all messages (OWNER ONLY)")
    @app_commands.describe(channel="Channel to nuke (optional, defaults to current)")
    @commands.bot_has_permissions(manage_channels=True, read_message_history=True, add_reactions=True)
    @commands.guild_only()
    async def nuke(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Nuke a channel by cloning and deleting it (Owner only)

        Flow: send embed -> react green tick / red tick -> nuke -> send success in new channel.
        """
        # 1. Owner check
        if ctx.author.id != BOT_OWNER_ID:
            return await self._safe_reply(ctx, "This command is restricted to the bot owner only.",
                                          allowed_mentions=discord.AllowedMentions.none())

        # 2. Resolve target channel
        channel_to_nuke: discord.TextChannel | None = None
        if isinstance(channel, discord.TextChannel):
            channel_to_nuke = channel
        elif isinstance(ctx.channel, discord.TextChannel):
            channel_to_nuke = ctx.channel

        if channel_to_nuke is None:
            return await self._safe_reply(ctx, "This command can only be used on text channels.",
                                          allowed_mentions=discord.AllowedMentions.none())

        # 3. Prevent nuking system channels
        if channel_to_nuke.is_news():
            return await self._safe_reply(ctx, "Cannot nuke announcement channels.",
                                          allowed_mentions=discord.AllowedMentions.none())

        # 4. Prevent nuking protected channels by name
        protected_names = {"rules", "announcements", "welcome", "server-info", "faq"}
        if channel_to_nuke.name.lower() in protected_names:
            return await self._safe_reply(ctx, f"Cannot nuke protected channel: {channel_to_nuke.mention}",
                                          allowed_mentions=discord.AllowedMentions.none())

        # 5. Check bot has permissions in the target channel
        bot_perms = channel_to_nuke.permissions_for(ctx.guild.me)  # type: ignore[union-attr]
        required = ["manage_channels", "read_message_history"]
        missing = [p for p in required if not getattr(bot_perms, p, False)]
        if missing:
            return await self._safe_reply(
                ctx,
                f"I'm missing permissions in {channel_to_nuke.mention}: **{', '.join(missing)}**. "
                "Ask an admin to grant me that permission.",
                allowed_mentions=discord.AllowedMentions.none(),
            )

        # 6. Count messages for preview
        msg_count = 0
        try:
            async for _ in channel_to_nuke.history(limit=None):
                msg_count += 1
        except discord.Forbidden:
            msg_count = "unknown"

        created_ts = int(channel_to_nuke.created_at.timestamp()) if channel_to_nuke.created_at else 0
        created = f"<t:{created_ts}:R>" if created_ts else "unknown"
        topic = (channel_to_nuke.topic or "None")
        if len(topic) > 100:
            topic = topic[:97] + "..."
        category = channel_to_nuke.category.name if channel_to_nuke.category else "None"
        thread_count = len(channel_to_nuke.threads) if hasattr(channel_to_nuke, "threads") else 0
        invite_count = 0
        try:
            invites = await channel_to_nuke.guild.invites()
            invite_count = sum(1 for inv in invites if inv.channel.id == channel_to_nuke.id)
        except discord.Forbidden:
            invite_count = "?"

        # 7. Log the nuke attempt
        import logging
        log = logging.getLogger("modcog.nuke")
        log.warning(
            f"NUKE requested by {ctx.author} ({ctx.author.id}) "
            f"on #{channel_to_nuke.name} ({channel_to_nuke.id}) in {ctx.guild.name}"
        )

        # 8. Build the nuke embed with details
        embed = discord.Embed(
            title="Channel Nuke",
            description=(
                f"You are about to **permanently destroy** {channel_to_nuke.mention}.\n\n"
                "All messages, pins, threads, and invites will be **irreversibly deleted**."
            ),
            color=discord.Color(0xED4245),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Channel", value=f"{channel_to_nuke.mention} (`{channel_to_nuke.id}`)", inline=False)
        embed.add_field(name="Category", value=category, inline=True)
        embed.add_field(name="Created", value=created, inline=True)
        embed.add_field(name="Messages", value=f"~{msg_count}", inline=True)
        embed.add_field(name="Threads", value=str(thread_count), inline=True)
        embed.add_field(name="Pending Invites", value=str(invite_count), inline=True)
        if topic != "None":
            embed.add_field(name="Topic", value=topic, inline=False)
        embed.add_field(
            name="What Happens",
            value=(
                "1. Delete all messages and pins\n"
                "2. Delete all active threads\n"
                "3. Revoke all pending invites\n"
                "4. Clone channel (preserves permissions, position, category)\n"
                "5. Delete original channel"
            ),
            inline=False,
        )
        embed.set_footer(text=f"Requested by {ctx.author.display_name} ({ctx.author.id})")

        # 9. Send the embed and add reaction buttons
        confirm_msg = await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        try:
            await confirm_msg.add_reaction("\u2705")  # green tick
            await confirm_msg.add_reaction("\u274c")  # red cross
        except discord.Forbidden:
            return await self._safe_reply(ctx, "I'm missing the 'Add Reactions' permission.",
                                          allowed_mentions=discord.AllowedMentions.none())

        # 10. Wait for reaction from the command author only
        def check(reaction: discord.Reaction, user: discord.Member) -> bool:
            return user.id == ctx.author.id and str(reaction) in ["\u2705", "\u274c"]

        try:
            reaction, _ = await self.bot.wait_for("reaction_add", timeout=30.0, check=check)
        except asyncio.TimeoutError:
            try:
                await confirm_msg.clear_reactions()
            except discord.Forbidden:
                pass
            await confirm_msg.edit(embed=discord.Embed(
                title="Nuke Cancelled",
                description="Confirmation timed out after 30 seconds.",
                color=discord.Color(0x99AAB5),
            ))
            return

        # 11. Handle reaction
        if str(reaction) == "\u274c":  # red cross - cancel
            try:
                await confirm_msg.clear_reactions()
            except discord.Forbidden:
                pass
            await confirm_msg.edit(embed=discord.Embed(
                title="Nuke Cancelled",
                description="No changes were made to the channel.",
                color=discord.Color(0x57F287),
            ))
            return

        # 12. Green tick confirmed - execute the nuke
        log.warning(
            f"NUKE CONFIRMED by {ctx.author} ({ctx.author.id}) "
            f"on #{channel_to_nuke.name} ({channel_to_nuke.id}) in {ctx.guild.name}"
        )

        try:
            position = channel_to_nuke.position
            new_channel = await channel_to_nuke.clone(
                reason=f"Channel nuked by {ctx.author} ({ctx.author.id})"
            )
            await channel_to_nuke.delete(
                reason=f"Channel nuked by {ctx.author} ({ctx.author.id})"
            )
            await new_channel.edit(position=position)
        except discord.Forbidden:
            return
        except Exception as e:
            try:
                await ctx.send(
                    f"Failed to nuke channel: {e}",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.Forbidden:
                pass
            return

        # 13. Send success embed with nuclear bomb gif in the recreated channel
        success_embed = discord.Embed(
            title="Nuked",
            description=(
                "This channel has been completely reset.\n"
                "All previous messages, pins, and threads have been permanently deleted."
            ),
            color=discord.Color(0x57F287),
            timestamp=datetime.now(timezone.utc),
        )
        success_embed.set_image(url="https://media.tenor.com/images/40f540506e13b53c2f44615a168923f8/tenor.gif")
        success_embed.add_field(
            name="Moderator",
            value=f"{ctx.author.display_name} ({ctx.author.id})",
            inline=True,
        )
        success_embed.add_field(
            name="Channel",
            value=new_channel.mention,
            inline=True,
        )
        try:
            await new_channel.send(embed=success_embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.ForForbidden:
            pass

    @commands.hybrid_command(name="massban", help="Ban multiple users by ID (OWNER ONLY)")
    @app_commands.describe(user_ids="User IDs to ban (space-separated)", reason="Reason for the bans")
    @commands.bot_has_permissions(ban_members=True)
    @commands.guild_only()
    async def massban(self, ctx: commands.Context, user_ids: str, *, reason: str = "Mass ban"):
        """Ban multiple users by their IDs (Owner only)"""
        # Check if user is the bot owner
        if ctx.author.id != BOT_OWNER_ID:
            return await ctx.send("This command is restricted to the bot owner only.", allowed_mentions=discord.AllowedMentions.none())
        
        assert ctx.guild is not None
        
        # Parse user IDs
        ids = [int(id.strip()) for id in user_ids.split() if id.strip().isdigit()]
        
        if not ids:
            return await ctx.send("No valid user IDs provided. Enter one or more numeric user IDs separated by spaces.", allowed_mentions=discord.AllowedMentions.none())
        
        if len(ids) > 50:
            return await ctx.send("Cannot ban more than 50 users at once. Split the list into smaller batches.", allowed_mentions=discord.AllowedMentions.none())
        
        await ctx.send(f"Processing ban for {len(ids)} user(s)...", allowed_mentions=discord.AllowedMentions.none())
        
        banned = []
        failed = []
        
        for user_id in ids:
            try:
                user = await self.bot.fetch_user(user_id)
                ban_reason = f"[MASSBAN] {reason}"
                register_mod_action(self.bot, ctx.guild.id, user_id, ctx.author.id, ban_reason, "BAN")
                await ctx.guild.ban(user, reason=ban_reason)
                banned.append(f"{user} ({user_id})")
            except Exception as e:
                discard_mod_action(self.bot, ctx.guild.id, user_id, "BAN")
                failed.append(f"{user_id}: {str(e)}")
        
        lines = []
        if banned:
            lines.append(f"**Banned ({len(banned)})**")
            lines.extend(banned[:10])
            if len(banned) > 10:
                lines.append(f"...and {len(banned) - 10} more")
        if failed:
            lines.append(f"**Failed ({len(failed)})**")
            lines.extend(failed[:10])
            if len(failed) > 10:
                lines.append(f"...and {len(failed) - 10} more")
        lines.append(f"**Reason:** {reason}")
        view = self._mod_action_card(
            "Mass Ban Complete", "ban",
            description="\n".join(lines),
            fields={"Moderator": f'{ctx.author.display_name} ({ctx.author.id})'},
        )
        await self._safe_reply(ctx, view=view)

    @commands.hybrid_command(name="nickname", help="Change a member's nickname")
    @app_commands.describe(member="Member to change nickname", nickname="New nickname (leave empty to reset)")
    @commands.bot_has_permissions(manage_nicknames=True)
    @commands.guild_only()
    async def nickname(self, ctx: commands.Context, member: discord.Member, *, nickname: Optional[str] = None):
        """Change a member's nickname"""
        if not self._check_permit(ctx, "manage_nicknames"):
            return await self._safe_reply(ctx, "You need the 'Manage Nicknames' permission or a matching permit to change nicknames.")
        if isinstance(ctx.author, discord.Member) and ctx.guild is not None:
            if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
                return await self._safe_reply(ctx, "Cannot complete this action. Their highest role is equal to or above yours. Only the server owner can act on members with higher roles.")

        old_nick = member.display_name
        new_nick = nickname or member.name

        try:
            register_mod_action(self.bot, ctx.guild.id, member.id, ctx.author.id, f"Nickname changed by {ctx.author}", "NICKNAME_UPDATE")
            await member.edit(nick=nickname, reason=f"Nickname changed by {ctx.author}")
            view = self._mod_action_card(
                "Nickname Changed", "info",
                user=member,
                fields={
                    "Member": f'{member.display_name} ({member.id})',
                    "Old": old_nick,
                    "New": new_nick,
                    "Moderator": f'{ctx.author.display_name} ({ctx.author.id})',
                },
            )
            await self._safe_reply(ctx, view=view)
        except discord.Forbidden:
            discard_mod_action(self.bot, ctx.guild.id, member.id, "NICKNAME_UPDATE")
            await self._safe_reply(ctx, "I don't have permission to change that member's nickname.")
        except Exception as e:
            discard_mod_action(self.bot, ctx.guild.id, member.id, "NICKNAME_UPDATE")
            await self._safe_reply(ctx, f"Failed to change nickname: {e}")

    # -------- Server Information Commands --------
    
    @commands.hybrid_command(name="info", aliases=["userinfo"], help="Get detailed information about a user")
    @app_commands.describe(user="User to get information about (defaults to yourself)")
    @commands.guild_only()
    async def userinfo(self, ctx: commands.Context, user: Optional[Union[discord.Member, discord.User]] = None):
        """Get comprehensive user information"""
        target_user = user if user is not None else ctx.author
        assert ctx.guild is not None
        
        embed = discord.Embed(
            title=f"User Information: {target_user}",
            color=target_user.color if isinstance(target_user, discord.Member) and target_user.color != discord.Color.default() else discord.Color.blue(),
            timestamp=datetime.now(tz=timezone.utc)
        )
        
        if target_user.avatar:
            embed.set_thumbnail(url=target_user.avatar.url)
        
        # Basic Info
        embed.add_field(name="Username", value=str(target_user), inline=True)
        embed.add_field(name="User ID", value=f"`{target_user.id}`", inline=True)
        embed.add_field(name="Bot", value="Yes" if target_user.bot else "No", inline=True)
        
        # Account Creation
        embed.add_field(
            name="Account Created",
            value=f"<t:{int(target_user.created_at.timestamp())}:F>\n(<t:{int(target_user.created_at.timestamp())}:R>)",
            inline=False
        )
        
        # Member-specific info
        if isinstance(target_user, discord.Member):
            # Join date
            if target_user.joined_at:
                embed.add_field(
                    name="Joined Server",
                    value=f"<t:{int(target_user.joined_at.timestamp())}:F>\n(<t:{int(target_user.joined_at.timestamp())}:R>)",
                    inline=False
                )
            
            # Roles
            if len(target_user.roles) > 1:
                roles = [role.mention for role in reversed(target_user.roles[1:])][:20]
                embed.add_field(
                    name=f"Roles [{len(target_user.roles) - 1}]",
                    value=" ".join(roles) if roles else "None",
                    inline=False
                )
            
            # Status
            status_emoji = {
                discord.Status.online: "Online",
                discord.Status.idle: "Idle",
                discord.Status.dnd: "Do Not Disturb",
                discord.Status.offline: "Offline"
            }
            embed.add_field(name="Status", value=status_emoji.get(target_user.status, "Unknown"), inline=True)
            
            # Highest role
            if target_user.top_role != ctx.guild.default_role:
                embed.add_field(name="⬆Highest Role", value=target_user.top_role.mention, inline=True)
            
            # Boost status
            if target_user.premium_since:
                embed.add_field(
                    name="Boosting Since",
                    value=f"<t:{int(target_user.premium_since.timestamp())}:R>",
                    inline=True
                )
            
            # Timeout status
            if target_user.timed_out_until:
                embed.add_field(
                    name="Timed Out Until",
                    value=f"<t:{int(target_user.timed_out_until.timestamp())}:F>",
                    inline=False
                )
        
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    
    @commands.hybrid_command(name="avatar", help="Get a user's avatar")
    @app_commands.describe(user="User to get avatar from (defaults to yourself)")
    async def avatar(self, ctx: commands.Context, user: Optional[Union[discord.Member, discord.User]] = None):
        """Get a user's avatar in high resolution"""
        target_user = user if user is not None else ctx.author
        
        embed = discord.Embed(
            title=f"{target_user}'s Avatar",
            color=discord.Color.blue()
        )
        
        if target_user.avatar:
            embed.set_image(url=target_user.avatar.url)
            embed.add_field(name="Links", value=f"[PNG]({target_user.avatar.replace(format='png', size=1024).url}) | [JPG]({target_user.avatar.replace(format='jpg', size=1024).url}) | [WEBP]({target_user.avatar.replace(format='webp', size=1024).url})", inline=False)
        else:
            embed.description = "This user has no custom avatar."
        
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    
    @commands.hybrid_command(name="roleinfo", help="Get information about a role")
    @app_commands.describe(role="Role to get information about")
    @commands.guild_only()
    async def roleinfo(self, ctx: commands.Context, *, role: discord.Role):
        """Get comprehensive role information"""
        assert ctx.guild is not None
        
        embed = discord.Embed(
            title=f"Role Information: {role.name}",
            color=role.color if role.color != discord.Color.default() else discord.Color.blue(),
            timestamp=datetime.now(tz=timezone.utc)
        )
        
        # Basic info
        embed.add_field(name="Name", value=role.name, inline=True)
        embed.add_field(name="ID", value=f"`{role.id}`", inline=True)
        embed.add_field(name="Color", value=str(role.color), inline=True)
        
        # Position
        embed.add_field(name="Position", value=f"{role.position}/{len(ctx.guild.roles)}", inline=True)
        
        # Members
        member_count = len(role.members)
        embed.add_field(name="Members", value=str(member_count), inline=True)
        
        # Created
        embed.add_field(
            name="Created",
            value=f"<t:{int(role.created_at.timestamp())}:F>\n(<t:{int(role.created_at.timestamp())}:R>)",
            inline=False
        )
        
        # Properties
        properties = []
        if role.hoist:
            properties.append("Hoisted")
        if role.mentionable:
            properties.append("Mentionable")
        if role.managed:
            properties.append("Managed")
        if role.is_premium_subscriber():
            properties.append("Booster Role")
        
        if properties:
            embed.add_field(name="Properties", value="\n".join(properties), inline=False)
        
        # Key permissions
        key_perms = []
        if role.permissions.administrator:
            key_perms.append("Administrator")
        if role.permissions.manage_guild:
            key_perms.append("Manage Server")
        if role.permissions.manage_roles:
            key_perms.append("Manage Roles")
        if role.permissions.manage_channels:
            key_perms.append("Manage Channels")
        if role.permissions.kick_members:
            key_perms.append("Kick Members")
        if role.permissions.ban_members:
            key_perms.append("Ban Members")
        if role.permissions.moderate_members:
            key_perms.append("Timeout Members")
        
        if key_perms:
            embed.add_field(name="Key Permissions", value="\n".join(key_perms), inline=False)
        
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    
    @commands.hybrid_command(name="serverinfo", help="Get detailed server information")
    @app_commands.describe()
    @commands.guild_only()
    async def serverinfo(self, ctx: commands.Context):
        """Get comprehensive server information"""
        guild = ctx.guild
        assert guild is not None  # Since we have @commands.guild_only()
        
        # Calculate server stats
        total_members = guild.member_count or len(guild.members)
        online_members = sum(1 for member in guild.members if member.status != discord.Status.offline)
        bot_count = sum(1 for member in guild.members if member.bot)
        human_count = len([m for m in guild.members if not m.bot])
        
        # Channel counts
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)
        
        # Role count
        role_count = len(guild.roles) - 1  # Exclude @everyone
        
        # Boost info
        boost_level = guild.premium_tier
        boost_count = guild.premium_subscription_count
        
        # Server features
        features = []
        if guild.features:
            feature_names = {
                'COMMUNITY': 'Community Server',
                'PARTNERED': 'Discord Partner',
                'VERIFIED': 'Verified',
                'VANITY_URL': 'Custom Invite URL',
                'ANIMATED_ICON': 'Animated Icon',
                'BANNER': 'Server Banner',
                'WELCOME_SCREEN_ENABLED': 'Welcome Screen',
                'MEMBER_VERIFICATION_GATE_ENABLED': 'Membership Screening',
                'PREVIEW_ENABLED': 'Server Preview'
            }
            features = [feature_names.get(f, f.replace('_', ' ').title()) for f in guild.features[:10]]
        
        embed = discord.Embed(
            title=f"{guild.name} Server Information",
            color=discord.Color.blue(),
            timestamp=datetime.now(tz=timezone.utc)
        )
        
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        
        embed.add_field(
            name="Member Stats",
            value=f"**Total:** {total_members:,}\n**Online:** {online_members:,}\n**Humans:** {human_count:,}\n**Bots:** {bot_count:,}",
            inline=True
        )
        
        embed.add_field(
            name="Channels",
            value=f"**Text:** {text_channels}\n**Voice:** {voice_channels}\n**Categories:** {categories}\n**Total:** {text_channels + voice_channels}",
            inline=True
        )
        
        embed.add_field(
            name="Roles & Boosts",
            value=f"**Roles:** {role_count}\n**Boost Level:** {boost_level}/3\n**Boosts:** {boost_count}",
            inline=True
        )
        
        owner = guild.owner or (guild.get_member(guild.owner_id) if guild.owner_id else None)
        if owner is None:
            owner_mention = "Unknown"
            owner_display = "Unknown"
        else:
            owner_mention = owner.mention
            owner_display = str(owner)
        embed.add_field(
            name="Server Owner",
            value=f"{owner.mention}\n{owner_display}" if owner else "Unknown",
            inline=True
        )
        
        embed.add_field(
            name="Created",
            value=f"<t:{int(guild.created_at.timestamp())}:F>\n(<t:{int(guild.created_at.timestamp())}:R>)",
            inline=True
        )
        
        embed.add_field(
            name="Server ID",
            value=f"`{guild.id}`",
            inline=True
        )
        
        if features:
            embed.add_field(
                name="Features",
                value="\n".join(f"• {feature}" for feature in features[:5]),
                inline=False
            )
        
        if guild.description:
            embed.add_field(
                name="Description",
                value=guild.description,
                inline=False
            )
        
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    # -------- Warnings Commands --------
    # Warnings system moved to SAM module (/warn, /unwarn, /warnings)
    # See: commands.modules.sam.features.warnings.cogs

    # -------- Verification Command --------

    @app_commands.command(name="verify", description="Verify a user by assigning a verification role")
    @app_commands.describe(user="The user to verify")
    async def verify(self, interaction: discord.Interaction, user: discord.User):
        """Verify a user by assigning a verification role."""
        # Check if invoker has the required admin/bypass role
        admin_bypass_role_id = ADMIN_BYPASS_ROLE_ID
        
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "You do not have permission to use this command.",
                ephemeral=True
            )
            return
        
        if not any(role.id == admin_bypass_role_id for role in interaction.user.roles) and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "You do not have permission to use this command.",
                ephemeral=True
            )
            return
        
        # Get target member
        if not isinstance(user, discord.Member):
            try:
                target_member = await interaction.guild.fetch_member(user.id)
            except discord.NotFound:
                await interaction.response.send_message(
                    f"User {user.display_name} is not a member of this server.",
                    ephemeral=True
                )
                return
        else:
            target_member = user
        
        # Create the verification view
        view = VerificationView(target_member, self.bot)
        
        embed = discord.Embed(
            title="Verification Panel",
            description=f"Select a verification type for {target_member.display_name}:",
            color=0x5865F2
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # -------- Shared Error Handler --------
    
    @purge.error
    @kick.error
    @ban.error
    @unban.error
    async def _command_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await self._safe_reply(ctx, "You lack the required permissions for this command. Contact an admin if you believe this is an error.")
        elif isinstance(error, commands.BotMissingPermissions):
            await self._safe_reply(ctx, "I am missing a permission required to run this command. Ask an admin to check my role permissions in Server Settings > Roles.")
        elif isinstance(error, commands.BadArgument):
            await self._safe_reply(ctx, "Invalid argument. Check the command usage with ?help for the correct format.")
        elif isinstance(error, commands.CommandInvokeError) and "Unknown interaction" in str(error):
            print(f"[ModCog] Interaction expired for {ctx.command}: {error}")
        else:
            await self._safe_reply(ctx, f"Something went wrong: {error}. If this keeps happening, contact an admin.")


class VerificationView(discord.ui.View):
    """View for verification role selection and confirmation."""
    
    VERIFICATION_ROLES = {
        "stream_verify": {
            "label": "Stream Verify",
            "role_id": VERIFY_STREAM_ROLE_ID,
            "value": "stream_verify"
        },
        "voice_verification": {
            "label": "Voice Verification",
            "role_id": VERIFY_VOICE_ROLE_ID,
            "value": "voice_verification"
        },
        "embed_verification": {
            "label": "Embed Verification",
            "role_id": VERIFY_EMBED_ROLE_ID,
            "value": "embed_verification"
        },
        "join_vc_verification": {
            "label": "Join VC Verification",
            "role_id": VERIFY_JOIN_VC_ROLE_ID,
            "value": "join_vc_verification"
        },
    }
    
    def __init__(self, target_member: discord.Member, bot: discord.Client):
        super().__init__(timeout=300)  # 5 minute timeout
        self.target_member = target_member
        self.bot = bot
        self.selected_verification = None
        
    @discord.ui.select(
        placeholder="Select a verification type...",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="Stream Verify", value="stream_verify"),
            discord.SelectOption(label="Voice Verification", value="voice_verification"),
            discord.SelectOption(label="Embed Verification", value="embed_verification"),
            discord.SelectOption(label="Join VC Verification", value="join_vc_verification"),
        ]
    )
    async def select_verification(self, interaction: discord.Interaction, select: discord.ui.Select):
        """Handle verification type selection."""
        self.selected_verification = select.values[0]
        
        # Update the embed to show selection
        embed = discord.Embed(
            title="Verification Panel",
            description=f"Selected: **{self.VERIFICATION_ROLES[self.selected_verification]['label']}** for {self.target_member.display_name}",
            color=0x5865F2
        )
        
        await interaction.response.defer()
        # After deferring, edits must go through edit_original_response
        # (response.edit_message would raise InteractionResponded).
        await interaction.edit_original_response(embed=embed, view=self)
    
    @discord.ui.button(label="Save", style=discord.ButtonStyle.green)
    async def save_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle saving the verification."""
        # Check if a verification type was selected
        if not self.selected_verification:
            await interaction.response.send_message(
                "❌ Please select a verification type before saving.",
                ephemeral=True
            )
            return
        
        await interaction.response.defer()
        
        role_id = self.VERIFICATION_ROLES[self.selected_verification]["role_id"]
        role = interaction.guild.get_role(role_id)
        
        if not role:
            await interaction.followup.send(
                f"❌ Verification role not found (ID: {role_id})",
                ephemeral=True
            )
            return
        
        # Check if user already has the role
        if role in self.target_member.roles:
            await interaction.followup.send(
                f"ℹ️ {self.target_member.display_name} already possesses the **{role.name}** role.",
                ephemeral=True
            )
            return
        
        # Try to assign the role
        try:
            await self.target_member.add_roles(role, reason=f"Verification by {interaction.user}")
            
            # Update embed with confirmation
            embed = discord.Embed(
                title="<:greentick:1529045309081256026> Verification Complete",
                description=f"Successfully assigned **{role.name}** to {self.target_member.display_name}",
                color=0x00FF00
            )
            embed.add_field(name="Verification Type", value=self.VERIFICATION_ROLES[self.selected_verification]["label"], inline=False)
            embed.add_field(name="Verified By", value=f"{interaction.user.display_name} ({interaction.user.id})", inline=False)
            embed.timestamp = datetime.now(timezone.utc)
            
            # Disable all components
            for item in self.children:
                item.disabled = True
            
            # The interaction was deferred above, so edits must use
            # edit_original_response (response.edit_message would raise
            # InteractionResponded after a defer).
            await interaction.edit_original_response(embed=embed, view=self)
            
        except discord.Forbidden:
            await interaction.followup.send(
                f"❌ I cannot assign the **{role.name}** role due to hierarchy restrictions.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ An error occurred while assigning the role: {str(e)}",
                ephemeral=True
            )
    
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle cancellation."""
        embed = discord.Embed(
            title="Verification Cancelled",
            description="The verification process has been cancelled.",
            color=0xFF0000
        )
        
        # Disable all components
        for item in self.children:
            item.disabled = True
        
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def on_timeout(self):
        """Handle view timeout."""
        # Disable all components
        for item in self.children:
            item.disabled = True


async def setup(bot: commands.Bot):
    await bot.add_cog(ModCog(bot))
