"""Unit tests for the Components V2 diagnostics dashboard (?diag)."""

import asyncio
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import discord

from commands.diagnostics import Diagnostics, DIAG_BAD_COLOR, DIAG_OK_COLOR


class FakeCtx:
    def __init__(self):
        self.sent: dict = {}

    async def send(self, **kwargs):
        self.sent = kwargs


def healthy_bot():
    return SimpleNamespace(
        latency=0.05,
        guilds=[1, 2, 3],
        start_time=datetime.now(timezone.utc),
    )


def containers_of(view) -> list:
    return [
        c for c in view.walk_children() if isinstance(c, discord.ui.Container)
    ]


def accent_values(view) -> list:
    """Accent color values, skipping containers with no accent set."""
    values = []
    for c in containers_of(view):
        color = c.accent_color
        if color is not None:
            values.append(color.value)
    return values


def test_diag_renders_four_subsystem_containers():
    async def run():
        ctx = FakeCtx()
        await Diagnostics(healthy_bot()).diag.callback(
            Diagnostics(healthy_bot()), ctx
        )
        view = ctx.sent["view"]
        assert view.has_components_v2()
        containers = containers_of(view)
        assert len(containers) == 4
        titles = [
            t.content
            for c in containers
            for t in c.walk_children()
            if isinstance(t, discord.ui.TextDisplay)
        ]
        joined = " ".join(titles)
        for name in (
            "Instance Information",
            "Performance Metrics",
            "Database Status",
            "Environment Status",
        ):
            assert name in joined

    asyncio.run(run())


def test_diag_stays_within_component_limit():
    async def run():
        ctx = FakeCtx()
        await Diagnostics(healthy_bot()).diag.callback(
            Diagnostics(healthy_bot()), ctx
        )
        view = ctx.sent["view"]
        assert sum(1 for _ in view.walk_children()) <= 40

    asyncio.run(run())


def test_diag_healthy_all_green():
    async def run():
        old = dict(os.environ)
        os.environ.setdefault("DISCORD_TOKEN", "test-token")
        os.environ.setdefault("GUILD_ID", "123")
        data_dir = __import__("pathlib").Path("data")
        data_dir.mkdir(exist_ok=True)
        dummy_db = data_dir / "test.db"
        dummy_db.touch(exist_ok=True)
        try:
            ctx = FakeCtx()
            await Diagnostics(healthy_bot()).diag.callback(
                Diagnostics(healthy_bot()), ctx
            )
            view = ctx.sent["view"]
            assert accent_values(view) == [DIAG_OK_COLOR] * 4
        finally:
            dummy_db.unlink(missing_ok=True)
            os.environ.clear()
            os.environ.update(old)

    asyncio.run(run())


def test_diag_degraded_flags_red():
    async def run():
        old = dict(os.environ)
        for var in ("DISCORD_TOKEN", "GUILD_ID"):
            os.environ.pop(var, None)
        try:
            bad_bot = SimpleNamespace(latency=1.5, guilds=[])
            ctx = FakeCtx()
            await Diagnostics(bad_bot).diag.callback(Diagnostics(bad_bot), ctx)
            view = ctx.sent["view"]
            colors = accent_values(view)
            # Instance (no start_time) and performance (high latency) must be red;
            # env (missing vars) red; DB may be green if data/*.db files exist.
            assert colors[0] == DIAG_BAD_COLOR
            assert colors[1] == DIAG_BAD_COLOR
            assert colors[3] == DIAG_BAD_COLOR
        finally:
            os.environ.clear()
            os.environ.update(old)

    asyncio.run(run())


def test_diag_sends_view_not_embed():
    async def run():
        ctx = FakeCtx()
        await Diagnostics(healthy_bot()).diag.callback(
            Diagnostics(healthy_bot()), ctx
        )
        assert "view" in ctx.sent
        assert "embed" not in ctx.sent

    asyncio.run(run())
