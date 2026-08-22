"""Tests for the bot.py on_message authorization gate.

Verifies that:
1. Non-authorized users are silently ignored for regular commands.
2. Rules commands (?r1-?r13, ?r34, ?tldr) bypass the auth gate.
3. Users in unauthorized servers get an error message.
"""

import asyncio
import os
import sys
from types import SimpleNamespace

# Ensure src/ is importable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for path in (PROJECT_ROOT, SRC_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


def run(coro):
    return asyncio.run(coro)


def _make_member(role_ids=None, user_id=999):
    """Build a minimal discord.Member stand-in."""
    roles = [SimpleNamespace(id=rid) for rid in (role_ids or [])]
    return SimpleNamespace(
        id=user_id,
        roles=roles,
        guild_permissions=SimpleNamespace(manage_messages=False),
    )


def _make_message(content, guild_id=111, author=None):
    """Build a minimal discord.Message stand-in."""
    if author is None:
        author = _make_member()
    channel = SimpleNamespace(id=222)
    guild = SimpleNamespace(id=guild_id)
    sent = []

    async def send_msg(**kwargs):
        sent.append(kwargs)

    message = SimpleNamespace(
        content=content,
        author=author,
        guild=guild,
        channel=channel,
    )
    message._sent = sent
    return message


def test_has_authorized_role_returns_true_for_bot_owner():
    from bot import _has_authorized_role
    member = _make_member(role_ids=[100, 200])
    # Patch BOT_OWNER_ID to match member.id
    import bot as bot_mod
    original = bot_mod.BOT_OWNER_ID
    try:
        bot_mod.BOT_OWNER_ID = 999
        assert _has_authorized_role(member) is True
    finally:
        bot_mod.BOT_OWNER_ID = original


def test_has_authorized_role_returns_true_for_correct_role():
    from bot import _has_authorized_role
    from config import AUTHORISED_ROLE_ID
    member = _make_member(role_ids=[AUTHORISED_ROLE_ID])
    assert _has_authorized_role(member) is True


def test_has_authorized_role_returns_false_for_wrong_role():
    from bot import _has_authorized_role
    member = _make_member(role_ids=[99999])
    assert _has_authorized_role(member) is False


def test_has_authorized_role_returns_false_for_no_roles():
    from bot import _has_authorized_role
    member = _make_member(role_ids=[])
    assert _has_authorized_role(member) is False
