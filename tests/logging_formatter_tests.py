"""Unit tests for the Components V2 moderation log cards (create_log_view)."""

from datetime import datetime, timezone
from types import SimpleNamespace

import discord

from commands.logging.formatter import LogFormatter


class FakeUser:
    def __init__(self, uid: int):
        self.id = uid
        self.mention = f"<@{uid}>"
        self.avatar = SimpleNamespace(url=f"https://example.com/{uid}.png")

    def __str__(self) -> str:
        return f"user{self.id}"


async def fetch_user(uid: int):
    return FakeUser(uid)


def make_formatter() -> LogFormatter:
    bot = SimpleNamespace(fetch_user=fetch_user)
    return LogFormatter(bot)


def base_item(**overrides) -> dict:
    item = {
        "event_type": "BAN",
        "user_id": 111,
        "moderator_id": 222,
        "details": "spam",
        "log_id": 5,
    }
    item.update(overrides)
    return item


def get_text_displays(view) -> list:
    return [
        c for c in view.walk_children() if isinstance(c, discord.ui.TextDisplay)
    ]


def get_thumbnails(view) -> list:
    return [
        c for c in view.walk_children() if isinstance(c, discord.ui.Thumbnail)
    ]


def test_ban_renders_v2_card_with_avatar_accessory():
    import asyncio

    async def run():
        view = await make_formatter().create_log_view(base_item())
        assert view is not None
        assert view.has_components_v2()
        assert get_thumbnails(view), "expected a user-avatar Thumbnail accessory"
        texts = " ".join(t.content for t in get_text_displays(view))
        assert "Member Banned" in texts
        assert "**<@111>** was banned" in texts
        assert "**Moderator:** <@222>" in texts
        assert "**Reason:** spam" in texts
        assert "Log ID: 5" in texts

    asyncio.run(run())


def test_non_moderation_event_falls_back_to_none():
    import asyncio

    async def run():
        view = await make_formatter().create_log_view(
            base_item(event_type="CHANNEL_CREATE")
        )
        assert view is None

    asyncio.run(run())


def test_timeout_applied_shows_duration_and_expiry():
    import asyncio

    async def run():
        expires = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
        view = await make_formatter().create_log_view(
            base_item(
                event_type="TIMEOUT_APPLIED",
                duration="1 hour",
                expires=expires,
            )
        )
        assert view is not None
        texts = " ".join(t.content for t in get_text_displays(view))
        assert "Member Timed Out" in texts
        assert "**Duration:** 1 hour" in texts
        assert f"<t:{int(expires.timestamp())}:R>" in texts

    asyncio.run(run())


def test_timeout_removed_via_appeal_and_expired_variants():
    import asyncio

    async def run():
        formatter = make_formatter()
        removed = await formatter.create_log_view(
            base_item(event_type="TIMEOUT_REMOVED", source="appeal")
        )
        assert removed is not None
        texts = " ".join(t.content for t in get_text_displays(removed))
        assert "removed via an approved appeal" in texts

        expired = await formatter.create_log_view(
            base_item(event_type="TIMEOUT_EXPIRED", details="auto")
        )
        assert expired is not None
        texts = " ".join(t.content for t in get_text_displays(expired))
        assert "naturally expired" in texts
        assert "**Details:** auto" in texts

    asyncio.run(run())


def test_warn_shows_case_id_and_avatar():
    import asyncio

    async def run():
        view = await make_formatter().create_log_view(
            base_item(event_type="WARN", case_id=42)
        )
        assert view is not None
        texts = " ".join(t.content for t in get_text_displays(view))
        assert "Warning Issued" in texts
        assert "**Case ID:** #42" in texts

    asyncio.run(run())


def test_moderation_cards_stay_within_component_limit():
    import asyncio

    async def run():
        formatter = make_formatter()
        for event_type in ("BAN", "UNBAN", "KICK", "TIMEOUT_APPLIED", "WARN"):
            view = await formatter.create_log_view(base_item(event_type=event_type))
            assert view is not None
            assert sum(1 for _ in view.walk_children()) <= 40

    asyncio.run(run())
