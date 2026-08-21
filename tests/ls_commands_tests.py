"""Unit tests for the Components V2 `ls` listing helpers (commands.utility).

Covers the chunking helper and the container builder used by every `ls`
subcommand, without a Discord connection.
"""

import discord

from commands import utility as u


def test_ls_chunk_lines_splits_long_lists():
    lines = [f"line-{i}-" + "x" * 300 for i in range(20)]
    chunks = u._ls_chunk_lines(lines, max_chars=1500)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 1500


def test_ls_chunk_lines_keeps_short_lists_together():
    assert u._ls_chunk_lines(["a", "b"], max_chars=1500) == ["a\nb"]


def test_ls_container_within_component_limit():
    """Even a very long list must stay under Discord's 40-component cap."""
    big_lines = [f"Entry {i} " + "y" * 90 for i in range(150)]
    container = u._ls_container("Big List", None, big_lines)
    assert sum(1 for _ in container.walk_children()) <= 40


def test_ls_container_empty_state():
    container = u._ls_container(
        "Bots", None, [], empty_text="No bots in this server."
    )
    displays = [
        c for c in container.walk_children() if isinstance(c, discord.ui.TextDisplay)
    ]
    assert any("No bots in this server." in d.content for d in displays)


def test_ls_container_footer():
    container = u._ls_container(
        "Roles", "Some intro.", ["one", "two"], footer="Total: 2 roles"
    )
    displays = [
        c for c in container.walk_children() if isinstance(c, discord.ui.TextDisplay)
    ]
    assert any("Total: 2 roles" in d.content for d in displays)


def test_ls_container_chunks_many_categories():
    """Many category headers + channels must not blow the component limit."""
    text_lines = []
    for c in range(40):
        text_lines.append(f"### CATEGORY {c}")
        text_lines.extend(f"└ <#{i}>" for i in range(8))
    container = u._ls_container("Channels", None, text_lines)
    assert sum(1 for _ in container.walk_children()) <= 40


# ── ?ls noroles pattern tests ──────────────────────────────────────────

def test_ls_container_noroles_empty_state():
    """Empty noroles list shows the expected fallback message."""
    container = u._ls_container(
        "Users with No Roles",
        "These members only have the @everyone role.",
        [],
        empty_text="Every member in this server has at least one role.",
    )
    displays = [
        c for c in container.walk_children() if isinstance(c, discord.ui.TextDisplay)
    ]
    assert any("Every member in this server has at least one role." in d.content for d in displays)


def test_ls_container_noroles_with_members():
    """A noroles list with entries renders a footer with count."""
    member_lines = ["• Alice (111)", "• Bob (222)"]
    container = u._ls_container(
        "Users with No Roles",
        "These members only have the @everyone role.",
        member_lines,
        footer="Total: 2 users",
    )
    displays = [
        c for c in container.walk_children() if isinstance(c, discord.ui.TextDisplay)
    ]
    assert any("Total: 2 users" in d.content for d in displays)
    assert any("Alice" in d.content for d in displays)


# ── ?ls channels ?v pattern tests ──────────────────────────────────────

def test_ls_container_channel_view_empty_overwrites():
    """Channel view with no overwrites shows the @everyone fallback."""
    container = u._ls_container(
        "Can View: general",
        "Channel: #general (`12345`)",
        ["*No explicit overwrites. **50** members can view via @everyone.*"],
    )
    displays = [
        c for c in container.walk_children() if isinstance(c, discord.ui.TextDisplay)
    ]
    assert any("No explicit overwrites" in d.content for d in displays)


def test_ls_container_channel_view_with_roles_and_users():
    """Channel view shows roles and users sections."""
    sections = [
        "### Roles (Explicit Allow)",
        "• @Admin",
        "### Users (5)",
        "• <@111>",
        "• <@222>",
        "### Roles (Explicit Deny)",
        "• @Muted",
    ]
    container = u._ls_container(
        "Can View: secret",
        "Channel: #secret (`99999`)",
        sections,
    )
    displays = [
        c for c in container.walk_children() if isinstance(c, discord.ui.TextDisplay)
    ]
    assert any("Roles (Explicit Allow)" in d.content for d in displays)
    assert any("Users (5)" in d.content for d in displays)
    assert any("Roles (Explicit Deny)" in d.content for d in displays)
    assert sum(1 for _ in container.walk_children()) <= 40


def test_ls_container_channel_view_deny_all():
    """Channel view when view denied at @everyone level."""
    container = u._ls_container(
        "Can View: private",
        "Channel: #private (`55555`)",
        ["*No one can view this channel (view denied at @everyone level).*"],
    )
    displays = [
        c for c in container.walk_children() if isinstance(c, discord.ui.TextDisplay)
    ]
    assert any("No one can view this channel" in d.content for d in displays)
