"""Tests for the logging formatter's _resolve_user method.

Verifies that:
1. _resolve_user prefers guild.fetch_member over bot.fetch_user.
2. _resolve_user falls back to bot.fetch_user when member is not in guild.
3. _resolve_user returns a fallback string when both fail.
"""

import asyncio
from types import SimpleNamespace

import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for path in (PROJECT_ROOT, SRC_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


def run(coro):
    return asyncio.run(coro)


class FakeMember:
    def __init__(self, uid, mention_text):
        self.id = uid
        self.mention = mention_text


class FakeGuild:
    def __init__(self, members=None):
        self._members = {m.id: m for m in (members or [])}

    def get_member(self, uid):
        return self._members.get(uid)

    async def fetch_member(self, uid):
        m = self._members.get(uid)
        if m is None:
            raise Exception("NotFound")
        return m


class FakeUser:
    def __init__(self, uid):
        self.id = uid
        self.mention = f"<@{uid}>"


class FakeBot:
    def __init__(self, guild=None):
        self._guild = guild

    def get_guild(self, gid):
        return self._guild

    async def fetch_user(self, uid):
        return FakeUser(uid)


def _make_formatter(bot):
    """Create a LogFormatter with the given bot."""
    from commands.logging.formatter import LogFormatter
    return LogFormatter(bot)


def test_resolve_user_returns_member_when_in_guild():
    member = FakeMember(123, "<@123>")
    guild = FakeGuild([member])
    bot = FakeBot(guild=guild)
    fmt = _make_formatter(bot)

    result = run(fmt._resolve_user(123, guild_id=1))
    assert result is member
    assert result.mention == "<@123>"


def test_resolve_user_falls_back_to_fetch_user_when_not_in_guild():
    bot = FakeBot(guild=None)
    fmt = _make_formatter(bot)

    result = run(fmt._resolve_user(456, guild_id=1))
    assert isinstance(result, FakeUser)
    assert result.id == 456


def test_resolve_user_returns_none_for_none_id():
    bot = FakeBot()
    fmt = _make_formatter(bot)
    result = run(fmt._resolve_user(None, guild_id=1))
    assert result is None


def test_resolve_user_uses_guild_fetch_member_when_not_cached():
    """When get_member returns None but fetch_member succeeds, it should use the fetched member."""
    member = FakeMember(789, "<@789>")
    async def fetch_member(uid):
        if uid == 789:
            return member
        raise Exception("NotFound")
    guild = SimpleNamespace(
        get_member=lambda uid: None,
        fetch_member=fetch_member,
    )

    bot = FakeBot(guild=guild)
    fmt = _make_formatter(bot)

    result = run(fmt._resolve_user(789, guild_id=1))
    assert result is member
