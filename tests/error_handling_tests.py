"""Regression tests for the global error handlers.

These lock in the Phase 1 fix: the prefix-command error handler in
``events.message_handler`` used to be dead code (its ``hasattr(ctx.command,
'on_error')`` guard always returned early in discord.py 2.x), and app-command
errors were never surfaced at all (the tree's default ``on_error`` only logs).

The tests run without a Discord connection and without pytest-asyncio:
contexts/interactions are minimal stand-ins with the attributes the handlers
touch, and coroutines are driven with ``asyncio.run``.
"""

import asyncio
import logging
from types import SimpleNamespace

from discord.ext import commands

from events.message_handler import MessageHandler, build_error_embed
from bot import CodeVerseTree


def run(coro):
    """Drive a coroutine synchronously (tests are sync by design)."""
    return asyncio.run(coro)


def make_command(has_error_handler: bool = False):
    cmd = SimpleNamespace(qualified_name="testcmd", name="testcmd")
    cmd.has_error_handler = lambda: has_error_handler
    return cmd


def make_ctx(interaction=None):
    sent = []

    async def send(embed=None, **kwargs):
        sent.append((embed, kwargs))

    ctx = SimpleNamespace(
        command=make_command(),
        cog=None,
        guild=SimpleNamespace(id=123456),
        interaction=interaction,
        send=send,
    )
    ctx.sent = sent
    return ctx


def make_interaction(done: bool = False, command=None):
    calls: dict = {"followup": [], "response": []}

    response = SimpleNamespace()
    response.is_done = lambda: done
    response.send_message = _record_async(calls["response"])

    followup = SimpleNamespace()
    followup.send = _record_async(calls["followup"])

    interaction = SimpleNamespace(
        command=command or make_command(),
        response=response,
        followup=followup,
    )
    interaction.calls = calls
    return interaction


def _record_async(store):
    async def record(embed=None, **kwargs):
        store.append((embed, kwargs))

    return record


def make_handler():
    return MessageHandler(bot=None)


def make_tree():
    """Build a CodeVerseTree without running its __init__ (which needs a real
    client with ``http`` and ``_connection`` attributes). ``on_error`` only
    touches the interaction, so a bare instance is enough."""
    tree = object.__new__(CodeVerseTree)
    return tree


# --------------------------------------------------------------------------
# Prefix-command error handler (events.message_handler.MessageHandler)
# --------------------------------------------------------------------------


def test_prefix_handler_does_not_short_circuit():
    """The old `hasattr(ctx.command, 'on_error')` guard made this dead code.

    A MissingPermissions error must actually reach the user.
    """
    ctx = make_ctx()
    run(make_handler().on_command_error(ctx, commands.MissingPermissions(["kick_members"])))

    assert ctx.sent, "expected an error embed to be sent"
    embed, _ = ctx.sent[0]
    assert embed.title == "❌ Missing Permissions"


def test_prefix_handler_ignores_command_not_found():
    ctx = make_ctx()
    run(make_handler().on_command_error(ctx, commands.CommandNotFound("?nope")))

    assert ctx.sent == []


def test_prefix_handler_shows_cooldown_retry_time():
    ctx = make_ctx()
    run(make_handler().on_command_error(ctx, commands.CommandOnCooldown(1, 3.0, commands.BucketType.user)))

    assert ctx.sent
    embed, _ = ctx.sent[0]
    assert embed.title == "⏰ Command on Cooldown"
    assert "3.0" in embed.description


def test_prefix_handler_logs_unexpected_errors(caplog):
    ctx = make_ctx()
    with caplog.at_level(logging.ERROR, logger="events.message_handler"):
        run(make_handler().on_command_error(ctx, RuntimeError("boom")))

    assert ctx.sent
    embed, _ = ctx.sent[0]
    assert embed.title == "❌ An Error Occurred"
    assert any("Unhandled error in testcmd" in r.message for r in caplog.records)


def test_prefix_handler_skips_commands_with_local_error_handler():
    ctx = make_ctx()
    ctx.command = make_command(has_error_handler=True)
    run(make_handler().on_command_error(ctx, commands.MissingPermissions(["kick_members"])))

    assert ctx.sent == []


def test_prefix_handler_replies_via_interaction_followup():
    interaction = make_interaction(done=True)
    ctx = make_ctx(interaction=interaction)
    run(make_handler().on_command_error(ctx, commands.MissingPermissions(["kick_members"])))

    assert interaction.calls["followup"], "expected an ephemeral followup"
    embed, kwargs = interaction.calls["followup"][0]
    assert embed.title == "❌ Missing Permissions"
    assert kwargs.get("ephemeral") is True


# --------------------------------------------------------------------------
# App-command error handler (CodeVerseTree.on_error)
# --------------------------------------------------------------------------


def test_tree_on_error_sends_ephemeral_cooldown_embed():
    import discord

    tree = make_tree()
    interaction = make_interaction(done=False)

    run(
        tree.on_error(
            interaction,
            discord.app_commands.CommandOnCooldown(
                discord.app_commands.Cooldown(1, 4.5), 4.5
            ),
        )
    )

    assert interaction.calls["response"], "expected a response send"
    embed, kwargs = interaction.calls["response"][0]
    assert embed.title == "⏰ Command on Cooldown"
    assert "4.5" in embed.description
    assert kwargs.get("ephemeral") is True


def test_tree_on_error_does_nothing_when_already_responded():
    import discord

    tree = make_tree()
    interaction = make_interaction(done=True)

    run(
        tree.on_error(
            interaction,
            discord.app_commands.MissingPermissions(["manage_messages"]),
        )
    )

    assert interaction.calls["response"] == []
    assert interaction.calls["followup"] == []


def test_tree_on_error_sends_permission_embed():
    import discord

    tree = make_tree()
    interaction = make_interaction(done=False)

    run(
        tree.on_error(
            interaction,
            discord.app_commands.MissingPermissions(["manage_messages"]),
        )
    )

    assert interaction.calls["response"]
    embed, kwargs = interaction.calls["response"][0]
    assert embed.title == "❌ Missing Permissions"
    assert kwargs.get("ephemeral") is True


# --------------------------------------------------------------------------
# Shared embed builder
# --------------------------------------------------------------------------


def test_build_error_embed_prefix_and_app_permission_errors_share_title():
    import discord

    prefix = run(build_error_embed(SimpleNamespace(), commands.MissingPermissions(["x"]), make_command()))
    app = run(
        build_error_embed(
            SimpleNamespace(), discord.app_commands.MissingPermissions(["x"]), make_command()
        )
    )
    assert prefix.title == app.title == "❌ Missing Permissions"
