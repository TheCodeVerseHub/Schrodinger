from discord.ext import commands
import asyncio
import logging
import discord

from config import INTRODUCTION_CHANNEL_ID
from discord import app_commands

logger = logging.getLogger(__name__)

# Channel that should get automatic intro reactions (configured in .env)
INTRO_REACTIONS = ["👋🏻", "🔥", "❤️"]

class MessageHandler(commands.Cog):
    """Simplified message handler with auto-thanks points."""
    def __init__(self, bot):
        self.bot = bot

    async def _add_intro_reactions(self, message: discord.Message) -> None:
        if getattr(message, 'reference', None) and getattr(message.reference, 'message_id', None):
            return

        for emoji in INTRO_REACTIONS:
            try:
                await message.add_reaction(emoji)
            except discord.Forbidden:
                logger.warning(
                    "Missing permission to add reactions in channel_id=%s guild_id=%s",
                    getattr(message.channel, 'id', None),
                    getattr(message.guild, 'id', None),
                )
                return
            except discord.HTTPException:
                # Non-fatal (rate limit / already reacted / transient API issue)
                continue

    @commands.command(name="introreact", hidden=True)
    @commands.has_permissions(manage_messages=True)
    async def introreact(self, ctx: commands.Context, limit: str = "all"):
        """Backfill intro reactions in the introductions channel.

        Usage:
          `?introreact` (all messages; can take a long time)
          `?introreact 500` (only last 500 messages)
        """
        if not ctx.guild:
            return

        fetched_channel = ctx.guild.get_channel(INTRODUCTION_CHANNEL_ID)
        channel = fetched_channel if isinstance(fetched_channel, discord.TextChannel) else None
        if not isinstance(channel, discord.TextChannel):
            try:
                fetched = await ctx.guild.fetch_channel(INTRODUCTION_CHANNEL_ID)
                channel = fetched if isinstance(fetched, discord.TextChannel) else None
            except (discord.Forbidden, discord.NotFound) as e:
                logger.warning("Could not fetch intro channel: %s", e)
                channel = None

        if not isinstance(channel, discord.TextChannel):
            await ctx.reply("<:redtick:1529045360742502481> I can't access the introductions channel in this server.", mention_author=False)
            return

        history_limit = None
        if limit and limit.lower() != "all":
            try:
                history_limit = max(1, int(limit))
            except ValueError:
                await ctx.reply("<:redtick:1529045360742502481> Invalid limit. Use `all` or a number (e.g. `?introreact 500`).", mention_author=False)
                return

        status = await ctx.reply(
            f"⏳ Adding reactions in {channel.mention} (limit={history_limit or 'all'})...",
            mention_author=False,
        )

        assert isinstance(channel, discord.TextChannel)
        scanned = 0
        processed = 0
        try:
            async for msg in channel.history(limit=history_limit, oldest_first=True):
                scanned += 1
                if msg.author.bot:
                    continue

                await self._add_intro_reactions(msg)
                processed += 1

                # Conservative pacing to avoid long bursts hitting global rate limits
                if processed % 25 == 0:
                    await asyncio.sleep(1)

            await status.edit(content=f"<:greentick:1529045309081256026> Done. Scanned {scanned} messages; reacted to {processed}.")
        except discord.Forbidden:
            await status.edit(content="<:redtick:1529045360742502481> Missing permissions to read history and/or add reactions.")
        except Exception as e:
            await status.edit(content=f"<:redtick:1529045360742502481> Stopped due to error: {e}")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle messages for auto-thanks detection"""
        # Ignore bot messages or DMs
        if message.author.bot or not message.guild:
            return

        # Auto-react in introductions channel
        if getattr(message.channel, 'id', None) == INTRODUCTION_CHANNEL_ID:
            await self._add_intro_reactions(message)

        # NOTE: Don't call process_commands here - the bot already does this automatically
        # Calling it here would cause duplicate responses for prefix commands

    # Staff points/aura system removed per request.

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Global prefix-command error handler.

        Runs for legacy/hybrid commands invoked with the prefix. Slash/hybrid
        commands invoked as app commands are handled by the tree override in
        ``CodeVerseBot`` (``bot.py``), which reuses :func:`build_error_embed`.
        """
        # Don't handle errors for commands that define their own error handler
        # (``@command.error``). ``Command.on_error`` only exists on such commands,
        # so the old ``hasattr(ctx.command, 'on_error')`` guard always returned
        # early and made this entire handler dead code.
        if ctx.command is not None and ctx.command.has_error_handler():
            return
        if ctx.cog is not None and ctx.cog.has_error_handler():
            return

        if isinstance(error, commands.CommandNotFound):
            # Not a real error -- unknown command. Log at DEBUG for triage;
            # a high volume here usually means the prefix cache is out of sync.
            logger.debug("CommandNotFound: %s (guild_id=%s)", error, getattr(ctx.guild, 'id', None))
            return

        # For slash/hybrid invocations, prefer replying on the interaction
        # (works when the interaction is still open or already done).
        interaction = getattr(ctx, 'interaction', None)
        if interaction is not None:
            try:
                embed = await build_error_embed(ctx, error, ctx.command)
                if interaction.response.is_done():
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.response.send_message(embed=embed, ephemeral=True)
            except Exception as e:
                logger.warning("Failed to send error response on interaction: %s", e)
            return

        embed = await build_error_embed(ctx, error, ctx.command)
        try:
            await ctx.send(embed=embed, delete_after=15, allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            logger.warning("Missing permission to send error response for command %s", ctx.command)
        except Exception as e:
            logger.warning("Failed to send error response: %s", e)


async def build_error_embed(context, error, command=None) -> discord.Embed:
    """Build a user-facing error embed for a command or app-command error.

    Shared by the prefix error listener and the app-command tree override so
    both surfaces produce identical messages.
    """
    command_name = None
    if command is not None:
        command_name = getattr(command, 'qualified_name', None) or getattr(command, 'name', None)
    label = command_name or 'command'

    if isinstance(error, (commands.MissingPermissions, app_commands.MissingPermissions)):
        return discord.Embed(
            title="<:redtick:1529045360742502481> Missing Permissions",
            description="You don't have permission to use this command!",
            color=discord.Color.red()
        )

    if isinstance(error, commands.MissingRequiredArgument):
        return discord.Embed(
            title="<:redtick:1529045360742502481> Missing Argument",
            description=f"Missing required argument: `{error.param}`\n"
                       f"Use `?help {label}` for usage information.",
            color=discord.Color.red()
        )

    if isinstance(error, commands.BadArgument):
        return discord.Embed(
            title="<:redtick:1529045360742502481> Invalid Argument",
            description=f"Invalid argument provided!\nUse `?help {label}` for usage information.",
            color=discord.Color.red()
        )

    if isinstance(error, (commands.CommandOnCooldown, app_commands.CommandOnCooldown)):
        return discord.Embed(
            title="⏰ Command on Cooldown",
            description=f"This command is on cooldown. Try again in {error.retry_after:.1f} seconds.",
            color=discord.Color.orange()
        )

    if isinstance(error, commands.MemberNotFound):
        return discord.Embed(
            title="<:redtick:1529045360742502481> Member Not Found",
            description="Could not find the specified member!",
            color=discord.Color.red()
        )

    # Anything else: log with stack trace and tell the user generically.
    logger.error(
        "Unhandled error in %s (guild_id=%s): %s",
        label,
        getattr(getattr(context, 'guild', None), 'id', None),
        error,
        exc_info=True,
    )
    return discord.Embed(
        title="<:redtick:1529045360742502481> An Error Occurred",
        description="An unexpected error occurred while processing your command.\n"
                   "Please try again later or contact an administrator.",
        color=discord.Color.red()
    )

    # AFK and XP systems removed per request.

async def setup(bot):
    await bot.add_cog(MessageHandler(bot))