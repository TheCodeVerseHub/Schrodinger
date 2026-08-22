"""Dynamic, self-maintaining help menu for CodeVerse Bot.

The help menu is built entirely from the bot's loaded command tree at
render time, so new commands appear automatically once their cog is loaded.
There is no manual command list to keep in sync.

Rendering uses Components V2 (containers / text displays / sections), so a
whole category fits on one message without the old per-field truncation.
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

HELP_COLOR = 0x5865F2

# ---------------------------------------------------------------------------
# Category configuration
# ---------------------------------------------------------------------------
# Maps cog class names -> display label. Commands from any cog not listed
# here are grouped under a "Miscellaneous" category automatically.
COG_CATEGORIES: dict[str, str] = {
    "Core": "Core",
    # Admin is a single section for staff-facing tooling: diagnostics,
    # the ticket system and the permit system.
    "Diagnostics": "Admin",
    "Tickets": "Admin",
    "PermitSystem": "Admin",
    # Moderation is a single broad section: basic moderation (ModCog),
    # advanced moderation tools and the SAM warnings system.
    "ModCog": "Moderation",
    "AdvancedModeration": "Moderation",
    "Warnings": "Moderation",
    # AutoMod & Protection covers the anti-abuse systems.
    "AutoBanChannel": "AutoMod & Protection",
    "Appeals": "Appeals",
    "ReactionRoles": "Reaction Roles",
    "LoggingCog": "Logging",
    # Utilities is the general-purpose section: embed builder plus the
    # smaller helper systems (sticky messages, rules, threads, help threads).
    "EmbedBuilder": "Utilities",
    "StickyMessage": "Utilities",
    "RulesCog": "Utilities",
    "ThreadCloser": "Utilities",
    "HelpThreadNotification": "Utilities",
    "MemberEvents": "Utilities",
    "MessageHandler": "Miscellaneous",
}

# Cog classes that are purely automated (no user-invocable commands).
_AUTOMATED_COGS = {"LoggingCog"}

# Hidden commands that are still intended for regular users.
_USER_HIDDEN_COMMANDS = {"needhelp"}

# Commands that should never surface in the help menu at all.
_SYSTEM_COMMANDS = {"introreact", "sync", "load"}

DEFAULT_PREFIX = "?"


# ---------------------------------------------------------------------------
# Command discovery / categorization
# ---------------------------------------------------------------------------
def _is_owner(ctx: commands.Context) -> bool:
    """Return whether the invoking user is the bot owner (sync check)."""
    author = getattr(ctx, "author", None)
    if author is None:
        return False
    owner_ids = set(getattr(ctx.bot, "owner_ids", None) or ())
    if getattr(ctx.bot, "owner_id", None):
        owner_ids.add(ctx.bot.owner_id)
    if getattr(ctx.bot, "user", None):
        owner_ids.add(ctx.bot.user.id)
    return author.id in owner_ids


def _is_visible_command(cmd, is_owner: bool) -> bool:
    """Decide whether a command should appear in the help menu.

    Works for both prefix/hybrid commands (commands.Command) and slash-only
    commands (app_commands.Command / our _SlashCommandInfo wrapper).

    - Explicit system commands (sync/load/introreact) are always hidden.
    - Owner-only commands are always decorated hidden=True by convention
      (commands.is_owner is a function, not a class, so it cannot be used
      with isinstance) they are excluded via the hidden filter below.
    - Other hidden commands are hidden unless whitelisted for users.
    - Regular commands are always visible.
    """
    name = getattr(cmd, "name", "")
    if name in _SYSTEM_COMMANDS:
        return False
    hidden = getattr(cmd, "hidden", False) or bool(
        getattr(cmd, "extras", {}).get("hidden", False)
    )
    if hidden:
        return name in _USER_HIDDEN_COMMANDS
    return True


# ---------------------------------------------------------------------------
# Command type detection (Slash / Hybrid / Prefix)
# ---------------------------------------------------------------------------
def command_type(cmd) -> str:
    """Classify a command as "slash", "hybrid" or "prefix".

    - Hybrid: commands.HybridCommand / commands.HybridGroup (have an
      app_command attached AND live in the prefix command list).
    - Slash: app_commands.Command / Group (slash-only, from the command tree).
    - Prefix: commands.Command with no slash counterpart.
    """
    if isinstance(cmd, _SlashCommandInfo):
        return "slash"
    if isinstance(cmd, (commands.HybridCommand, commands.HybridGroup)):
        return "hybrid"
    if isinstance(cmd, (app_commands.Command, app_commands.Group)):
        return "slash"
    if getattr(cmd, "app_command", None) is not None:
        return "hybrid"
    return "prefix"


def _cog_category(cog_name: Optional[str]) -> str:
    """Return the display label for a cog's commands."""
    if cog_name:
        label = COG_CATEGORIES.get(cog_name)
        if label:
            return label
    return "Miscellaneous"


class _SlashCommandInfo:
    """Lightweight display wrapper for slash-only commands from the tree.

    app_commands.Command objects lack help/short_doc/cog_name, so we project
    them onto a uniform shape that the embed builders and visibility filter
    already understand. The owning cog is derived from cog attributes via
    _slash_command_cogs(); .extras carries the command's hidden flag.
    """

    def __init__(self, app_cmd, qualified_name: str, label: str):
        self.app_command = app_cmd
        self.name = app_cmd.name
        self.qualified_name = qualified_name
        self.label = label
        self.aliases: list[str] = []
        self.hidden = False
        self.extras: dict = dict(getattr(app_cmd, "extras", {}) or {})
        self.cog_name = label

    @property
    def help(self):
        return self.app_command.description or None

    @property
    def short_doc(self):
        return self.app_command.description or None

    @property
    def checks(self):
        return []


def _tree_commands(bot: commands.Bot) -> dict[str, app_commands.Command]:
    """Flatten the app command tree into {qualified_name: command}."""
    result: dict[str, app_commands.Command] = {}
    for cmd in bot.tree.walk_commands():  # type: ignore[attr-defined]
        result.setdefault(cmd.qualified_name, cmd)
    return result


def _slash_command_cogs(bot: commands.Bot) -> dict[str, str]:
    """Map every slash command's qualified name to its defining cog class name.

    app_commands.Command/Group objects do not carry a reference to the cog
    that defined them (extras is empty, no binding attr in this discord.py
    version), so we discover them by scanning each loaded cog's class
    attributes for Command/Group instances.
    """
    result: dict[str, str] = {}
    for cog in bot.cogs.values():
        for attr_name in dir(cog):
            if attr_name.startswith("_"):
                continue
            attr = getattr(cog, attr_name, None)
            if isinstance(attr, (app_commands.Command, app_commands.Group)):
                result.setdefault(attr.qualified_name, cog.__class__.__name__)
                # Direct subcommands of a group belong to the same cog.
                if isinstance(attr, app_commands.Group):
                    for sub in attr.commands:
                        result.setdefault(sub.qualified_name, cog.__class__.__name__)
    return result


def build_categories(bot: commands.Bot, ctx) -> dict[str, list]:
    """Group every visible command into its display category.

    Returns an ordered dict of {category_label: [commands]} where each entry
    is either a commands.Command (prefix/hybrid) or a _SlashCommandInfo
    (slash-only). Every command appears exactly once.
    """
    is_owner = _is_owner(ctx)
    categories: dict[str, list] = defaultdict(list)

    # Prefix + hybrid commands (hybrids carry .app_command and live here).
    tree = _tree_commands(bot)
    registered_prefix_names: set[str] = set()
    for cmd in bot.commands:
        if not _is_visible_command(cmd, is_owner):
            continue
        # Hybrid commands are also present in the tree; register by qualified
        # name so slash-only commands from the tree don't duplicate them.
        qname = cmd.qualified_name
        label = _cog_category(cmd.cog_name)
        categories[label].append((qname, cmd))
        tree.pop(qname, None)
        registered_prefix_names.add(cmd.name)

    # Slash-only commands from the tree (hybrids were already popped above).
    # Subcommands of groups are skipped here they are listed inside the
    # group's detailed help instead, keeping each category list tidy.
    slash_cogs = _slash_command_cogs(bot)
    for qname, app_cmd in tree.items():
        if getattr(app_cmd, "parent", None) is not None:
            continue  # subcommand of a group (shown via detail view)
        # A command registered as a plain prefix command AND as a slash command
        # is shown once under its prefix form.
        if app_cmd.name in registered_prefix_names:
            continue
        if not _is_visible_command(app_cmd, is_owner):
            continue
        label = _cog_category(slash_cogs.get(qname))
        categories[label].append((qname, _SlashCommandInfo(app_cmd, qname, label)))

    result: dict[str, list] = {}
    for label, entries in categories.items():
        entries.sort(key=lambda e: e[0])
        result[label] = [cmd for _, cmd in entries]
    return dict(sorted(result.items()))


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def _format_uptime(bot: commands.Bot) -> str:
    try:
        start_time = getattr(bot, "start_time", datetime.now(timezone.utc))
        uptime = datetime.now(timezone.utc) - start_time
        return str(uptime).split(".")[0]
    except Exception:
        return "Unknown"


def _format_permissions(cmd: commands.Command) -> str:
    """Extract human-readable permission requirements from command checks.

    Note: owner-only commands are excluded from the help menu upstream
    (commands.is_owner is a function, not a class, so it cannot be used
    with isinstance).
    """
    perms: list[str] = []
    for check in getattr(cmd, "checks", []) or []:
        kw = getattr(check, "kwargs", None)
        if not kw:
            continue
        for perm, value in kw.items():
            if isinstance(value, bool) and value:
                perms.append(_perm_label(perm))
    return ", ".join(perms) if perms else "Everyone"


def _perm_label(perm: str) -> str:
    """Convert a discord.Permissions attribute to a friendly label."""
    labels = {
        "administrator": "Administrator",
        "ban_members": "Ban Members",
        "kick_members": "Kick Members",
        "manage_messages": "Manage Messages",
        "manage_roles": "Manage Roles",
        "manage_channels": "Manage Channels",
        "manage_guild": "Manage Server",
        "manage_threads": "Manage Threads",
        "moderate_members": "Moderate Members",
        "manage_webhooks": "Manage Webhooks",
        "manage_events": "Manage Events",
        "manage_nicknames": "Manage Nicknames",
        "send_messages": "Send Messages",
        "embed_links": "Embed Links",
        "mute_members": "Mute Members",
        "move_members": "Move Members",
        "deafen_members": "Deafen Members",
        "view_audit_log": "View Audit Log",
        "manage_expressions": "Manage Expressions",
        "mention_everyone": "Mention Everyone",
        "attach_files": "Attach Files",
    }
    return labels.get(perm, perm.replace("_", " ").title())


def _format_cooldown(cmd) -> Optional[str]:
    """Return a short cooldown description if the command defines one."""
    # discord.py wraps @cooldown(...) checks as functions with a .cooldown
    # attribute (commands.CooldownMapping), not bare Cooldown objects.
    cooldown = getattr(cmd, "cooldown", None)
    if cooldown is not None:
        mapping = getattr(cooldown, "mapping", cooldown)
        per = getattr(mapping, "per", None)
        rate = getattr(mapping, "rate", None)
        if per is not None and rate is not None:
            unit = "second"
            if per >= 3600:
                per, unit = per / 3600, "hour"
            elif per >= 60:
                per, unit = per / 60, "minute"
            return f"{rate} use{'s' if rate != 1 else ''}/{int(per)} {unit}{'s' if int(per) != 1 else ''}"
    return None


def _type_label(cmd) -> str:
    """Classify a command as Slash, Prefix or Hybrid."""
    ctype = command_type(cmd)
    return ctype.capitalize()


def _get_aliases(cmd: commands.Command) -> list[str]:
    """Return the effective alias list (excluding slash command names)."""
    aliases = [a for a in getattr(cmd, "aliases", []) or []]
    app_cmd = getattr(cmd, "app_command", None)
    if app_cmd is not None:
        app_name = getattr(app_cmd, "name", None)
        if app_name:
            aliases = [a for a in aliases if a != app_name]
    return aliases


def _display_name(cmd) -> str:
    """Name shown in list views: uses /-form for slash commands, prefix form otherwise."""
    if command_type(cmd) == "slash":
        return f"/{cmd.qualified_name}"
    return cmd.qualified_name


def _display_usage(cmd, prefix: str) -> str:
    """Build the usage line(s) for a command of any type."""
    ctype = command_type(cmd)
    if ctype == "slash":
        return f"`/{cmd.qualified_name}`"
    if ctype == "hybrid":
        sig = getattr(cmd, "signature", "") or ""
        sig = " " + sig if sig else sig
        return f"`{prefix}{cmd.qualified_name}{sig}` / `{cmd.qualified_name}{sig}`"
    sig = getattr(cmd, "signature", "") or ""
    sig = " " + sig if sig else sig
    return f"`{prefix}{cmd.qualified_name}{sig}`"


def _normalize_command_name(name: str) -> str:
    """Normalize user input like '/verify', '?ban' or 'ls role' to a lookup key."""
    name = name.strip().lstrip("/").lstrip("?")
    return name.replace(" ", ".")


def _find_command(bot: commands.Bot, name: str):
    """Find a command by (possibly qualified) name across prefix + slash."""
    name = _normalize_command_name(name)
    # Try dotted form first (tree-style keys), then the space form (the
    # natural prefix syntax, e.g. 'ls role' resolves via bot.get_command).
    for key in (name, name.replace(".", " ")):
        cmd = bot.get_command(key)
        if cmd is not None:
            return cmd
        for app_cmd in _tree_commands(bot).values():
            if app_cmd.qualified_name == key:
                label = _cog_category(_slash_command_cogs(bot).get(key))
                return _SlashCommandInfo(app_cmd, key, label)
    return None


def _section_lines(cmds: list, prefix: str) -> list[str]:
    """Format command lines (without a section heading)."""
    lines = []
    for cmd in cmds:
        summary = (
            (cmd.short_doc or cmd.help or "No description").strip().replace("\n", " ")
        )
        if len(summary) > 70:
            summary = summary[:67] + "…"
        lines.append(f"`{_display_name(cmd)}` - {summary}")
    return lines


def _group_by_type(cmds: list) -> dict[str, list]:
    """Split commands into slash/hybrid/prefix buckets."""
    buckets: dict[str, list] = {"slash": [], "hybrid": [], "prefix": []}
    for cmd in cmds:
        buckets[command_type(cmd)].append(cmd)
    return buckets


_SECTION_TITLES = {
    "slash": "Slash Commands",
    "hybrid": "Hybrid Commands",
    "prefix": "Prefix Commands",
}


# ---------------------------------------------------------------------------
# Components V2 rendering
# ---------------------------------------------------------------------------
def _chunk_lines(lines: list[str], max_chars: int = 1500) -> list[str]:
    """Split command lines into chunks that fit a single TextDisplay safely."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) + 1 > max_chars:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def build_home_container(
    bot: commands.Bot, categories: dict[str, list], prefix: str
) -> discord.ui.Container:
    """Main help page: bot info, quick stats and category overview."""
    total = sum(len(cmds) for cmds in categories.values())
    uptime = _format_uptime(bot)

    intro = (
        "## CodeVerse Bot : Help Center\n"
        "Welcome to **CodeVerse Bot**! Pick a category from the dropdown "
        "below to explore its commands.\n\n"
        f"**Prefix:** `{prefix}` (e.g. `{prefix}ping`)\n"
        "**Slash:** `/` (e.g. `/ping`)\n"
        "Use `/help <command>` or `?help <command>` for detailed info on a "
        "specific command."
    )

    container = discord.ui.Container(accent_color=discord.Color(HELP_COLOR))
    if bot.user and bot.user.avatar:
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(intro),
                accessory=discord.ui.Thumbnail(
                    bot.user.avatar.url, description="CodeVerse Bot"
                ),
            )
        )
    else:
        container.add_item(discord.ui.TextDisplay(intro))
    container.add_item(discord.ui.Separator())

    stats = (
        "### Quick Stats\n"
        f"- **Commands:** {total}\n"
        f"- **Categories:** {len(categories)}\n"
        f"- **Uptime:** {uptime}"
    )
    container.add_item(discord.ui.TextDisplay(stats))
    container.add_item(discord.ui.Separator())

    overview = "\n".join(
        f"**{label}** - {len(cmds)} command{'s' if len(cmds) != 1 else ''}"
        for label, cmds in categories.items()
    )
    container.add_item(
        discord.ui.TextDisplay(
            f"### Categories\n{overview or 'No commands available.'}"
        )
    )
    return container


# Commands per category page. TextDisplays hold far more than the old embed
# fields, so most categories fit on a single page; pagination only kicks in
# for unusually large ones.
_PAGE_SIZE = 30


def _total_pages(cmds: list) -> int:
    return max(1, (len(cmds) + _PAGE_SIZE - 1) // _PAGE_SIZE)


def build_category_container(
    bot: commands.Bot,
    label: str,
    cmds: list,
    prefix: str,
    page: int = 0,
) -> discord.ui.Container:
    """One category page grouped into Slash / Hybrid / Prefix sections."""
    total_pages = _total_pages(cmds)
    page = max(0, min(page, total_pages - 1))
    page_cmds = cmds[page * _PAGE_SIZE : (page + 1) * _PAGE_SIZE]

    container = discord.ui.Container(accent_color=discord.Color(HELP_COLOR))
    container.add_item(
        discord.ui.TextDisplay(
            f"## {label} Commands\n"
            f"{len(cmds)} command{'s' if len(cmds) != 1 else ''} - use "
            "`?help <command>` or `/help <command>` for details"
        )
    )
    container.add_item(discord.ui.Separator())

    buckets = _group_by_type(page_cmds)
    for ctype in ("slash", "hybrid", "prefix"):
        group = buckets[ctype]
        if not group:
            continue
        title = _SECTION_TITLES[ctype]
        for chunk in _chunk_lines(_section_lines(group, prefix)):
            container.add_item(discord.ui.TextDisplay(f"### {title}\n{chunk}"))

    if total_pages > 1:
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(f"Page {page + 1} of {total_pages}")
        )
    return container


def build_command_container(
    bot: commands.Bot,
    cmd,
    prefix: str,
    is_owner: bool,
) -> discord.ui.Container:
    """Detailed card for a single command (any type)."""
    description = cmd.help or cmd.short_doc or "No description provided."

    container = discord.ui.Container(accent_color=discord.Color(HELP_COLOR))
    if bot.user and bot.user.avatar:
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(f"## `{cmd.qualified_name}`\n{description}"),
                accessory=discord.ui.Thumbnail(
                    bot.user.avatar.url, description="Command help"
                ),
            )
        )
    else:
        container.add_item(
            discord.ui.TextDisplay(f"## `{cmd.qualified_name}`\n{description}")
        )
    container.add_item(discord.ui.Separator())

    details = [
        f"**Category:** {_cog_category(getattr(cmd, 'cog_name', None))}",
        f"**Type:** {_type_label(cmd)}",
    ]
    aliases = _get_aliases(cmd)
    if aliases:
        details.append("**Aliases:** " + ", ".join(f"`{a}`" for a in aliases[:8]))
    details.append(f"**Usage:** {_display_usage(cmd, prefix)}")
    perms = _format_permissions(cmd)
    if perms:
        details.append(f"**Required Permissions:** {perms}")
    cooldown = _format_cooldown(cmd)
    if cooldown:
        details.append(f"**Cooldown:** {cooldown}")
    container.add_item(discord.ui.TextDisplay("### Details\n" + "\n".join(details)))

    subs = []
    if isinstance(cmd, commands.Group):
        subs = [s for s in cmd.commands if _is_visible_command(s, is_owner)]
    elif isinstance(cmd, _SlashCommandInfo) and isinstance(
        cmd.app_command, app_commands.Group
    ):
        subs = [s for s in cmd.app_command.commands if _is_visible_command(s, is_owner)]
    if subs:
        lines = [
            f"`{s.name}` - {s.short_doc or s.description or 'No description'}"
            for s in subs
        ]
        for chunk in _chunk_lines(lines):
            container.add_item(
                discord.ui.TextDisplay("### Subcommands\n" + chunk)
            )
    return container


# ---------------------------------------------------------------------------
# Interactive view
# ---------------------------------------------------------------------------
class HelpMenuView(discord.ui.LayoutView):
    """Components V2 help dashboard: dropdown + paginated category pages."""

    def __init__(
        self,
        bot: commands.Bot,
        categories: dict[str, list[commands.Command]],
        prefix: str,
    ):
        super().__init__(timeout=180)
        self.bot = bot
        self.categories = categories
        self.prefix = prefix
        self.message = None
        self.expired = False
        self.current_label: Optional[str] = None
        self.current_cmds: list[commands.Command] = []
        self.current_page = 0
        self.total_pages = 1
        self._render()

    # ------------------------------------------------------------------ render
    def _render(self) -> None:
        self.clear_items()

        if self.current_label is None:
            container = build_home_container(self.bot, self.categories, self.prefix)
        else:
            container = build_category_container(
                self.bot,
                self.current_label,
                self.current_cmds,
                self.prefix,
                self.current_page,
            )
        self.add_item(container)

        if self.expired:
            return

        category_row = discord.ui.ActionRow()
        category_row.add_item(self._make_category_select())
        self.add_item(category_row)

        nav_row = discord.ui.ActionRow()
        home = discord.ui.Button(
            label="Home",
            style=discord.ButtonStyle.secondary,
            custom_id="help:home",
        )
        home.callback = self._go_home  # type: ignore[assignment]
        prev = discord.ui.Button(
            label="◀",
            style=discord.ButtonStyle.primary,
            custom_id="help:prev",
            disabled=self.current_page <= 0,
        )
        prev.callback = self._go_prev  # type: ignore[assignment]
        nxt = discord.ui.Button(
            label="▶",
            style=discord.ButtonStyle.primary,
            custom_id="help:next",
            disabled=self.current_page >= self.total_pages - 1,
        )
        nxt.callback = self._go_next  # type: ignore[assignment]
        nav_row.add_item(home)
        nav_row.add_item(prev)
        nav_row.add_item(nxt)
        self.add_item(nav_row)

    def _make_category_select(self) -> discord.ui.Select:
        options = [
            discord.SelectOption(
                label=label,
                description=f"{len(cmds)} command{'s' if len(cmds) != 1 else ''}",
                value=label,
            )
            for label, cmds in self.categories.items()
        ]
        select = discord.ui.Select(
            placeholder="Choose a category to explore…",
            min_values=1,
            max_values=1,
            options=options[:25],
            custom_id="help:category",
        )
        select.callback = self._on_category  # type: ignore[assignment]
        return select

    # ------------------------------------------------------------ callbacks
    async def _on_category(self, interaction: discord.Interaction):
        label = interaction.data["values"][0]
        self.current_label = label
        self.current_cmds = self.categories[label]
        self.current_page = 0
        self.total_pages = _total_pages(self.current_cmds)
        self._render()
        await interaction.response.edit_message(view=self)

    async def _go_home(self, interaction: discord.Interaction):
        self.current_label = None
        self.current_cmds = []
        self.current_page = 0
        self.total_pages = 1
        self._render()
        await interaction.response.edit_message(view=self)

    async def _go_prev(self, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)
        self._render()
        await interaction.response.edit_message(view=self)

    async def _go_next(self, interaction: discord.Interaction):
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self._render()
        await interaction.response.edit_message(view=self)

    async def on_timeout(self) -> None:
        """Disable the menu when it times out."""
        self.expired = True
        try:
            self._render()
            if self.message is not None:
                await self.message.edit(view=self)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Entry point used by the help command
# ---------------------------------------------------------------------------
async def send_help_menu(
    ctx: commands.Context, command_name: Optional[str] = None
) -> None:
    """Render and send the interactive help menu.

    Works for both slash and prefix invocations via hybrid commands.
    """
    bot = ctx.bot
    prefix = getattr(ctx, "clean_prefix", DEFAULT_PREFIX) or DEFAULT_PREFIX
    is_owner = _is_owner(ctx)

    # Detailed help for a specific command
    if command_name:
        cmd = _find_command(bot, command_name.lower())
        if not cmd or not _is_visible_command(cmd, is_owner):
            await _reply(ctx, content=f"Command `{command_name}` not found.")
            return
        view = discord.ui.LayoutView(timeout=None)
        view.add_item(build_command_container(bot, cmd, prefix, is_owner))
        await _reply(ctx, view=view)
        return

    # Interactive menu
    categories = build_categories(bot, ctx)
    view = HelpMenuView(bot, categories, prefix)
    if ctx.interaction:
        await ctx.interaction.response.send_message(view=view, ephemeral=True)
    else:
        message = await ctx.send(view=view, allowed_mentions=discord.AllowedMentions.none())
        view.message = message


async def _reply(
    ctx,
    content: str | None = None,
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
) -> None:
    """Reply through either the interaction or a plain context."""
    if ctx.interaction:
        if not ctx.interaction.response.is_done():
            await ctx.interaction.response.send_message(
                content=content or "", embed=embed, view=view, ephemeral=True
            )
        else:
            await ctx.interaction.followup.send(
                content=content or "", embed=embed, view=view, ephemeral=True
            )
    else:
        await ctx.send(content=content or "", embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
