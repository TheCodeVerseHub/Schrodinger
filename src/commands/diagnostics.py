import os
import discord
from discord.ext import commands
from datetime import datetime, timezone
from pathlib import Path

# Accent colors for the diag dashboard containers (green = healthy, red = problem).
DIAG_OK_COLOR = 0x00FF00
DIAG_BAD_COLOR = 0xFF0000


def _diag_container(title: str, lines: list, ok: bool) -> discord.ui.Container:
    """One Components V2 container per subsystem, accent-colored by status."""
    container = discord.ui.Container(
        accent_color=discord.Color(DIAG_OK_COLOR if ok else DIAG_BAD_COLOR)
    )
    container.add_item(discord.ui.TextDisplay(f"## {title}"))
    container.add_item(discord.ui.TextDisplay("\n".join(lines)))
    return container


class Diagnostics(commands.Cog):
    """Bot diagnostics and health monitoring."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="diag", help="Show comprehensive bot diagnostics")
    async def diag(self, ctx: commands.Context):
        """Show bot diagnostics and health status."""
        uptime = datetime.now(timezone.utc) - getattr(self.bot, 'start_time', datetime.now(timezone.utc))
        latency = round(self.bot.latency * 1000)

        # Database Status
        db_files = []
        data_dir = Path("data")
        if data_dir.exists():
            for db_file in data_dir.glob("*.db"):
                db_files.append(db_file.name)

        # Environment Check
        required_vars = ['DISCORD_TOKEN', 'GUILD_ID']
        missing_vars = [var for var in required_vars if not os.getenv(var)]

        view = discord.ui.LayoutView(timeout=None)

        # Instance Information
        instance_ok = getattr(self.bot, 'start_time', None) is not None
        view.add_item(_diag_container(
            "Instance Information",
            [
                f"**ID:** {os.getenv('INSTANCE_ID', 'production')}",
                f"**Uptime:** {str(uptime).split('.')[0]}",
                f"**Status:** {'Online' if instance_ok else 'Restarting'}",
            ],
            instance_ok,
        ))

        # Performance
        perf_ok = latency < 1000
        view.add_item(_diag_container(
            "Performance Metrics",
            [
                f"**Latency:** {latency}ms",
                f"**Guilds:** {len(self.bot.guilds)}",
                f"**Status:** {'Healthy' if perf_ok else 'High latency'}",
            ],
            perf_ok,
        ))

        # Database Status
        db_ok = bool(db_files)
        view.add_item(_diag_container(
            "Database Status",
            [
                f"**Active DBs:** {len(db_files)}",
                f"**Files:** {', '.join(db_files) if db_files else 'None'}",
                f"**Status:** {'Connected' if db_ok else 'No databases found'}",
            ],
            db_ok,
        ))

        # Environment Check
        env_ok = not missing_vars
        env_container = _diag_container(
            "Environment Status",
            [
                f"**Config:** {'Complete' if env_ok else 'Missing variables'}",
                f"**Platform:** {os.getenv('HOSTING_PLATFORM', 'Unknown')}",
                f"**Status:** {'Ready' if env_ok else 'Missing: ' + ', '.join(missing_vars)}",
            ],
            env_ok,
        )
        env_container.add_item(discord.ui.TextDisplay(
            f"*Bot Version: Production | Instance: {os.getenv('INSTANCE_ID', 'prod')}*"
        ))
        view.add_item(env_container)

        await ctx.send(view=view, allowed_mentions=discord.AllowedMentions.none())

async def setup(bot: commands.Bot):
    await bot.add_cog(Diagnostics(bot))
