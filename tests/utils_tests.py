"""Unit tests for the pure utility modules.

These tests exercise ``src/utils/helpers.py`` (mention sanitization, duration
parsing, channel lookup), ``src/utils/embeds.py`` (embed builders) and
``src/utils/json_store.py`` (JSON persistence) without any Discord connection:
Discord objects are replaced with lightweight stand-ins exposing only the
attributes the functions touch.
"""

import asyncio
import os
from datetime import timedelta
from types import SimpleNamespace

import pytest

from utils import helpers, json_store
from utils.embeds import (
    create_ban_embed,
    create_error_embed,
    create_info_embed,
    create_points_embed,
    create_success_embed,
    create_warning_embed,
)


def run(coro):
    """Drive a coroutine synchronously (tests are sync by design)."""
    return asyncio.run(coro)


# --------------------------------------------------------------------------
# helpers.sanitize_mentions
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("@everyone look here", "@\u200beveryone look here"),
        ("ping @here now", "ping @\u200bhere now"),
        ("@EVERYONE loud", "@\u200bEVERYONE loud"),
        ("hi <@123456789>", "hi <@\u200b123456789>"),
        ("<@!987654> and <@&555>", "<@\u200b!987654> and <@\u200b&555>"),
        ("no mentions at all", "no mentions at all"),
        ("", ""),
        (None, ""),
    ],
)
def test_sanitize_mentions(raw, expected):
    assert helpers.sanitize_mentions(raw) == expected


def test_sanitize_mentions_leaves_email_like_text_alone():
    # "@here" inside a word boundary must still be caught; plain text untouched
    assert helpers.sanitize_mentions("hello world") == "hello world"


# --------------------------------------------------------------------------
# helpers.parse_duration
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1d", timedelta(days=1)),
        ("2h", timedelta(hours=2)),
        ("30m", timedelta(minutes=30)),
        ("45s", timedelta(seconds=45)),
        ("1d 2h 30m 15s", timedelta(days=1, hours=2, minutes=30, seconds=15)),
        ("1D 2H", timedelta(days=1, hours=2)),
        ("1d, 2h", timedelta(days=1, hours=2)),
        (" 5m ", timedelta(minutes=5)),
    ],
)
def test_parse_duration_valid(text, expected):
    assert helpers.parse_duration(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "abc", "0s", "1x", "-1d", "1.5h", "d", "1d2h", "banana 1d"],
)
def test_parse_duration_invalid(text):
    assert helpers.parse_duration(text) is None


# --------------------------------------------------------------------------
# helpers.find_channel_by_name
# --------------------------------------------------------------------------


def test_find_channel_by_name_matches_keyword():
    guild = SimpleNamespace(
        text_channels=[
            SimpleNamespace(name="general"),
            SimpleNamespace(name="mod-logs"),
            SimpleNamespace(name="chat"),
        ]
    )
    found = helpers.find_channel_by_name(guild, "mod", "staff")
    assert found is not None
    assert found.name == "mod-logs"


def test_find_channel_by_name_returns_first_match():
    guild = SimpleNamespace(
        text_channels=[
            SimpleNamespace(name="staff-lounge"),
            SimpleNamespace(name="staff-only"),
        ]
    )
    found = helpers.find_channel_by_name(guild, "staff")
    assert found.name == "staff-lounge"


def test_find_channel_by_name_no_match_returns_none():
    guild = SimpleNamespace(text_channels=[SimpleNamespace(name="general")])
    assert helpers.find_channel_by_name(guild, "appeal") is None


# --------------------------------------------------------------------------
# utils.embeds embed builders
# --------------------------------------------------------------------------


def test_create_points_embed():
    embed = create_points_embed("CodeVerse", 5, "spam", 25)
    assert embed.title == "Moderation Notice"
    assert "5" in embed.description
    assert "25/100" in str(embed.fields[1].value)  # current points


def test_create_ban_embed():
    embed = create_ban_embed("CodeVerse", "reached cap")
    assert embed.title == "Account Suspended"
    assert "CodeVerse" in embed.description


def test_create_warning_embed():
    user = SimpleNamespace(mention="<@1>")
    mod = SimpleNamespace(mention="<@2>")
    embed = create_warning_embed(user, mod, "rule break", 2, 7)
    assert embed.title == "User Warning Issued"
    field_map = {f.name: f.value for f in embed.fields}
    assert field_map["User"] == "<@1>"
    assert field_map["Moderator"] == "<@2>"
    assert field_map["Points Added"] == "2"
    assert field_map["Current Points"] == "7/100"


def test_create_error_success_info_embeds():
    error = create_error_embed("Boom", "details")
    success = create_success_embed("Done", "yay")
    info = create_info_embed("Info", "text")

    assert error.title == "Boom"
    assert error.color.value == 0xFF0000
    assert success.color.value == 0x00FF00
    assert info.title == "Info"
    assert info.color.value == 0x5865F2  # brand blurple


# --------------------------------------------------------------------------
# utils.json_store (isolated from the real data/ dir via tmp_path)
# --------------------------------------------------------------------------


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    """Point json_store at a throwaway directory and reset its locks."""
    monkeypatch.setattr(json_store, "_BASE", str(tmp_path))
    json_store._LOCKS.clear()
    yield
    json_store._LOCKS.clear()


def test_json_store_warning_roundtrip(isolated_store):
    async def scenario():
        await json_store.add_warning(111, 222, "spam")
        await json_store.add_warning(111, 333, "again")

        warnings = await json_store.get_warnings(111)
        assert len(warnings) == 2
        assert warnings[0]["reason"] == "spam"
        assert warnings[0]["moderator"] == 222
        assert warnings[0]["ts"]  # timestamp present

        assert await json_store.get_warnings(999) == []

    run(scenario())


def test_json_store_guild_prefix_roundtrip(isolated_store):
    async def scenario():
        assert await json_store.get_guild_prefix(123) is None

        await json_store.set_guild_prefix(123, "!")
        assert await json_store.get_guild_prefix(123) == "!"

        await json_store.set_guild_prefix(123, "?")
        assert await json_store.get_guild_prefix(123) == "?"

    run(scenario())


def test_json_store_corrupt_file_is_backed_up(isolated_store, tmp_path):
    bad = os.path.join(str(tmp_path), "warnings.json")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("{not valid json")

    assert run(json_store.get_warnings(1)) == {}
    # The corrupt file should have been moved aside, not silently deleted
    leftovers = [p for p in os.listdir(str(tmp_path)) if "corrupt" in p]
    assert leftovers, "expected a .corrupt backup file"
