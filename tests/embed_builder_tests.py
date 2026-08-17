"""Unit tests for the interactive embed builder (commands.embed_builder).

The builder is a Components V2 dashboard; these tests exercise its pure
helpers (parsing, rendering limits, button/embed construction) without a
Discord connection, mirroring the sync style used by the error-handler tests.
"""

import asyncio
from types import SimpleNamespace

import discord

from commands.embed_builder import EmbedBuilderDashboard


def make_cog():
    bot = SimpleNamespace(
        get_channel=lambda cid: None,
        user=SimpleNamespace(display_avatar=SimpleNamespace(url="https://example.com/avatar.png")),
        fetch_user=None,
    )
    return SimpleNamespace(bot=bot, colors={"red": discord.Color.red()})


def make_builder(**kwargs):
    return EmbedBuilderDashboard(make_cog(), user_id=123, channel_id=456, **kwargs)


def run(coro):
    return asyncio.run(coro)


def test_dashboard_stays_within_component_limit():
    """Discord caps a message at 40 components; the builder must fit."""
    view = make_builder()
    assert sum(1 for _ in view.walk_children()) <= 40


def test_parse_channel_id():
    parse = EmbedBuilderDashboard._parse_channel_id
    assert parse("<#789>") == 789
    assert parse("789") == 789
    assert parse("  <#42>  ") == 42
    assert parse("abc") is None
    assert parse("") is None
    assert parse(None) is None


def test_parse_color():
    builder = make_builder()
    assert builder._parse_color("#FF0000").value == 0xFF0000
    assert builder._parse_color("red") is not None
    assert builder._parse_color("not-a-color") is None
    assert builder._parse_color(None) is None


def test_button_view_is_none_without_button():
    builder = make_builder()
    assert builder._build_button_view() is None


def test_button_view_contains_link_button():
    builder = make_builder()
    builder.data["button_label"] = "Read More"
    builder.data["button_url"] = "https://example.com"
    view = builder._build_button_view()
    assert view is not None
    buttons = [
        c
        for c in view.walk_children()
        if isinstance(c, discord.ui.Button)
        and c.style == discord.ButtonStyle.link
        and c.url == "https://example.com"
    ]
    assert buttons and buttons[0].label == "Read More"


def test_button_view_is_not_components_v2():
    """The sent button must be a classic View so it can travel with the embed.

    Components V2 views set MessageFlags.IS_COMPONENTS_V2, which makes Discord
    reject the 'embeds' field in the same message (error 50035).
    """
    builder = make_builder()
    builder.data["button_label"] = "Read More"
    builder.data["button_url"] = "https://example.com"
    view = builder._build_button_view()
    assert view is not None
    assert not view.has_components_v2()


def test_build_embed_title_optional():
    builder = make_builder()
    builder.data["description"] = "Hello world"
    interaction = SimpleNamespace(guild=None)
    embed = run(builder._build_embed(interaction))
    assert embed.title is None
    assert embed.description == "Hello world"

    builder.data["title"] = "My Title"
    embed = run(builder._build_embed(interaction))
    assert embed.title == "My Title"


def test_build_embed_sanitizes_mentions():
    builder = make_builder()
    builder.data["title"] = "hi @everyone"
    builder.data["description"] = "ping <@123>"
    interaction = SimpleNamespace(guild=None)
    embed = run(builder._build_embed(interaction))
    assert embed.title == "hi @\u200beveryone"
    assert embed.description == "ping <@\u200b123>"


def test_author_resolves_from_user_id():
    async def fetch_user(uid):
        assert uid == 999
        return SimpleNamespace(
            display_name="ResolvedUser",
            display_avatar=SimpleNamespace(url="https://example.com/u.png"),
        )

    cog = make_cog()
    cog.bot.fetch_user = fetch_user
    builder = EmbedBuilderDashboard(cog, user_id=123, channel_id=456)
    builder.data["author_id"] = "999"
    author = run(builder._resolve_author(SimpleNamespace(guild=None)))
    assert author == ("ResolvedUser", "https://example.com/u.png")


def test_apply_section_rejects_bad_channel():
    builder = make_builder()
    sent = []

    async def send_message(*args, **kwargs):
        sent.append((args, kwargs))

    interaction = SimpleNamespace(
        user=SimpleNamespace(id=123),
        response=SimpleNamespace(send_message=send_message),
    )
    run(
        builder.apply_section(
            interaction, "channel", {"channel_id": "not-a-channel"}
        )
    )
    assert sent, "expected an error reply"
    assert builder.data["channel_id"] == "456"  # unchanged


def test_description_shows_set_not_content():
    """The builder must not render the full description (up to 4000 chars)
    inside a TextDisplay - it would overflow the 4000-char limit."""
    builder = make_builder()
    assert builder._display_value("description") == "*Not set*"
    builder.data["description"] = "x" * 4000
    assert builder._display_value("description") == "Set"


def test_truncate_display_keeps_content_under_limit():
    long_text = "x" * 5000
    truncated = EmbedBuilderDashboard._truncate_display(long_text)
    assert len(truncated) <= 3500
    assert truncated.endswith("…")
    assert EmbedBuilderDashboard._truncate_display("short") == "short"


def test_apply_section_accepts_channel_mention():
    builder = make_builder()
    deferred = []

    async def defer(*args, **kwargs):
        deferred.append(True)

    async def edit_original_response(*args, **kwargs):
        pass

    interaction = SimpleNamespace(
        user=SimpleNamespace(id=123),
        response=SimpleNamespace(send_message=defer, defer=defer),
        edit_original_response=edit_original_response,
    )
    run(builder.apply_section(interaction, "channel", {"channel_id": "<#789>"}))
    assert builder.data["channel_id"] == "789"
