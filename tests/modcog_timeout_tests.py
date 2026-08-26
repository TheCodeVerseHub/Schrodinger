"""Tests for prefix-only timeout inspection commands."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from commands.modcog import ModCog


def run(coro):
    return asyncio.run(coro)


class FakeMember:
    def __init__(self, mid: int, name: str, timed_out_until=None):
        self.id = mid
        self.name = name
        self.display_name = name
        self.mention = f"<@{mid}>"
        self.timed_out_until = timed_out_until
        self.guild_permissions = SimpleNamespace(moderate_members=True, administrator=False)
        self.roles = []


class FakeGuild:
    def __init__(self, members):
        self.id = 123
        self.members = members

    async def fetch_members(self, limit=None):
        for member in self.members:
            yield member


class FakeCtx:
    def __init__(self, guild, author):
        self.guild = guild
        self.author = author
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append({"args": args, "kwargs": kwargs})


def make_cog():
    bot = SimpleNamespace(get_cog=lambda name: None)
    return ModCog(bot)


def test_currently_muted_lists_only_active_timeouts():
    active_until = datetime.now(timezone.utc) + timedelta(minutes=15)
    expired_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    active = FakeMember(1, "active-user", timed_out_until=active_until)
    expired = FakeMember(2, "expired-user", timed_out_until=expired_until)
    untouched = FakeMember(3, "normal-user", timed_out_until=None)

    guild = FakeGuild([active, expired, untouched])
    ctx = FakeCtx(guild, author=FakeMember(99, "mod"))
    cog = make_cog()

    run(ModCog.currently_muted.callback(cog, ctx))

    assert len(ctx.sent) == 1
    kwargs = ctx.sent[0]["kwargs"]
    embeds = kwargs.get("embeds")
    assert embeds and len(embeds) == 1
    embed = embeds[0]
    assert embed.title == "Currently Timed Out Members"
    assert "<@1>" in embed.description
    assert "<@2>" not in embed.description
    assert "<@3>" not in embed.description

