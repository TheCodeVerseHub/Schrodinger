"""Unit tests for the appeals cog's timeout-expiry guard.

``Appeals._timeout_already_expired_reason`` decides whether an appeal can be
accepted: it returns ``None`` while the timeout is still active, and a reason
string when the punishment is already gone (member left, timeout removed, or
naturally expired) so the appeal gets auto-resolved instead of approved.

These tests run without a Discord connection or a live bot: the helper is
stateless, so a bare instance (via ``object.__new__``, same trick as the
error-handler tests) and a ``SimpleNamespace`` member stand-in are enough.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from commands.appeals import AppealRecord, Appeals

NOW = datetime.now(timezone.utc)


def make_record(**overrides):
    base = dict(
        appeal_id=1,
        guild_id=1,
        guild_name="Test Guild",
        user_id=123,
        username="testuser",
        punishment_type="timed out",
        punishment_reason="Spam",
        timeout_issued_at=NOW - timedelta(hours=2),
        timeout_expires_at=NOW + timedelta(hours=1),
        appeal_reason="I'm sorry",
        should_remove="I'll stop",
        appeal_learned="I learned",
        appeal_extra=None,
        submitted_at=NOW,
    )
    base.update(overrides)
    return AppealRecord(**base)


def make_member(timed_out_until):
    return SimpleNamespace(timed_out_until=timed_out_until)


def make_cog() -> Appeals:
    """Bare Appeals instance - skips __init__ (needs a live bot + DB)."""
    return object.__new__(Appeals)


def test_active_timeout_returns_none():
    record = make_record(timeout_expires_at=NOW + timedelta(hours=1))
    member = make_member(NOW + timedelta(hours=1))
    assert make_cog()._timeout_already_expired_reason(record, member) is None


def test_member_left_server_is_expired():
    record = make_record(timeout_expires_at=NOW + timedelta(hours=1))
    reason = make_cog()._timeout_already_expired_reason(record, None)
    assert reason is not None
    assert "no longer in the server" in reason


def test_timeout_already_removed_is_expired():
    record = make_record(timeout_expires_at=NOW + timedelta(hours=1))
    member = make_member(None)
    reason = make_cog()._timeout_already_expired_reason(record, member)
    assert reason is not None
    assert "no longer timed out" in reason


def test_naturally_expired_timeout_is_expired():
    record = make_record(timeout_expires_at=NOW - timedelta(minutes=5))
    member = make_member(NOW - timedelta(minutes=1))
    reason = make_cog()._timeout_already_expired_reason(record, member)
    assert reason is not None
    assert "expired" in reason


def test_record_expiry_in_past_falls_back_to_expired():
    # Member state is stale (still reports an active timeout) but the recorded
    # expiry has passed - the guard must still treat it as expired.
    record = make_record(timeout_expires_at=NOW - timedelta(days=1))
    member = make_member(NOW + timedelta(hours=1))
    reason = make_cog()._timeout_already_expired_reason(record, member)
    assert reason is not None
    assert "expired" in reason
