"""Unit tests for the Components V2 help menu (commands.help_menu).

Covers the V2 rendering helpers and the interactive dashboard without a
Discord connection, using minimal stand-ins for the bot and commands.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import discord

from commands import help_menu as hm


def make_bot(n_commands: int = 5):
    commands = []
    for i in range(n_commands):
        commands.append(
            SimpleNamespace(
                name=f"cmd{i}",
                qualified_name=f"cmd{i}",
                help=f"Command number {i}",
                short_doc=f"Command number {i}",
                aliases=[],
                hidden=False,
                extras={},
                checks=[],
                cog_name="Core",
                signature="",
                app_command=None,
                commands=[],
            )
        )
    return SimpleNamespace(
        user=SimpleNamespace(
            id=123, avatar=SimpleNamespace(url="https://example.com/avatar.png")
        ),
        owner_id=1,
        owner_ids=None,
        start_time=datetime.now(timezone.utc),
        commands=commands,
        tree=SimpleNamespace(walk_commands=lambda: []),
        cogs={},
        get_command=lambda k: None,
    )


def make_ctx(bot):
    return SimpleNamespace(
        bot=bot, author=SimpleNamespace(id=1), clean_prefix="?"
    )


def test_chunk_lines_splits_long_lists():
    lines = [f"line-{i}-" + "x" * 300 for i in range(20)]
    chunks = hm._chunk_lines(lines, max_chars=1500)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 1500


def test_chunk_lines_keeps_short_lists_together():
    assert hm._chunk_lines(["a", "b"], max_chars=1500) == ["a\nb"]


def test_total_pages():
    assert hm._total_pages([]) == 1
    assert hm._total_pages(list(range(1))) == 1
    assert hm._total_pages(list(range(30))) == 1
    assert hm._total_pages(list(range(31))) == 2


def test_build_categories_groups_commands():
    bot = make_bot()
    cats = hm.build_categories(bot, make_ctx(bot))
    assert "Core" in cats
    assert len(cats["Core"]) == 5


def test_home_container_within_limits():
    bot = make_bot()
    cats = hm.build_categories(bot, make_ctx(bot))
    container = hm.build_home_container(bot, cats, "?")
    assert sum(1 for _ in container.walk_children()) <= 40


def test_category_container_within_limits():
    bot = make_bot(40)
    cats = hm.build_categories(bot, make_ctx(bot))
    container = hm.build_category_container(bot, "Core", cats["Core"], "?", 0)
    assert sum(1 for _ in container.walk_children()) <= 40


def test_command_container_within_limits():
    bot = make_bot()
    cmd = bot.commands[0]
    container = hm.build_command_container(bot, cmd, "?", False)
    assert sum(1 for _ in container.walk_children()) <= 40


def test_help_view_within_component_limit():
    """The full dashboard (containers + nav) must fit Discord's 40-item cap."""
    bot = make_bot(40)
    cats = hm.build_categories(bot, make_ctx(bot))
    view = hm.HelpMenuView(bot, cats, "?")
    assert sum(1 for _ in view.walk_children()) <= 40
    # Nav must exist: one category select + Home/prev/next buttons.
    selects = [c for c in view.walk_children() if isinstance(c, discord.ui.Select)]
    buttons = [c for c in view.walk_children() if isinstance(c, discord.ui.Button)]
    assert len(selects) == 1
    assert len(buttons) == 3


def test_help_view_rerenders_category_page():
    bot = make_bot(40)
    cats = hm.build_categories(bot, make_ctx(bot))
    view = hm.HelpMenuView(bot, cats, "?")
    view.current_label = "Core"
    view.current_cmds = cats["Core"]
    view.total_pages = hm._total_pages(cats["Core"])
    view.current_page = 0
    view._render()
    assert sum(1 for _ in view.walk_children()) <= 40
