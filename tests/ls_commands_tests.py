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
