"""Unit tests for the paginated Components V2 appeal list (AppealListView)."""

from types import SimpleNamespace

import discord

from commands.appeals import AppealListView


def make_cog():
    return SimpleNamespace(
        bot=SimpleNamespace(
            user=SimpleNamespace(
                display_avatar=SimpleNamespace(url="https://example.com/bot.png")
            )
        )
    )


def make_rows(count: int = 20):
    return [
        {
            "appeal_id": i,
            "user_id": 1000 + i,
            "reason": "I am sorry for what happened." * 3,
            "status": ["pending", "approved", "denied", "auto_resolved"][i % 4],
            "timestamp": "2026-08-17 12:00:00",
            "review_reason": "Seems genuine." if i % 2 else None,
            "reviewed_by": 999 if i % 2 else None,
            "avatar_url": "https://example.com/a.png",
        }
        for i in range(count)
    ]


def test_appeal_list_stays_within_component_limit():
    view = AppealListView(make_cog(), make_rows(20), "All Appeals", user_id=1)
    assert sum(1 for _ in view.walk_children()) <= 40


def test_appeal_list_paginates():
    view = AppealListView(make_cog(), make_rows(20), "All Appeals", user_id=1)
    assert view.total_pages == 2
    assert view.page == 0

    view.page = 1
    view._render()
    assert sum(1 for _ in view.walk_children()) <= 40


def test_appeal_list_single_page_with_few_rows():
    view = AppealListView(make_cog(), make_rows(5), "Pending Appeals", user_id=1)
    assert view.total_pages == 1
    assert sum(1 for _ in view.walk_children()) <= 40


def test_appeal_section_shows_status_badge():
    view = AppealListView(make_cog(), make_rows(1), "Appeals", user_id=1)
    text = view._section_text(view.rows[0])
    assert "🟡 **Pending**" in text
    text_approved = view._section_text(
        {**view.rows[0], "status": "approved", "review_reason": "OK", "reviewed_by": 7}
    )
    assert "🟢 **Approved**" in text_approved
    assert "Reviewed by <@7>" in text_approved


def test_appeal_section_has_avatar_accessory():
    view = AppealListView(make_cog(), make_rows(1), "Appeals", user_id=1)
    thumbnails = [
        c
        for c in view.walk_children()
        if isinstance(c, discord.ui.Thumbnail)
    ]
    assert thumbnails
