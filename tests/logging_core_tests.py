"""Tests for legacy log-channel routing in the logging cog."""

import asyncio
import sqlite3
from types import SimpleNamespace

from commands.logging.core import LoggingCog


def run(coro):
    return asyncio.run(coro)


def test_legacy_role_update_member_routes_to_member_log_channel(tmp_path, monkeypatch):
    db_path = tmp_path / "logs.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE guild_log_channels (
            guild_id INTEGER PRIMARY KEY,
            message_log_channel_id INTEGER,
            member_log_channel_id INTEGER,
            server_log_channel_id INTEGER,
            ticket_log_channel_id INTEGER,
            mod_log_channel_id INTEGER,
            other_log_channel_id INTEGER
        )
        """
    )
    conn.execute(
        """
        INSERT INTO guild_log_channels (
            guild_id, message_log_channel_id, member_log_channel_id,
            server_log_channel_id, ticket_log_channel_id, mod_log_channel_id, other_log_channel_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (123, 1, 222, 3, 4, 5, 6),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr("commands.logging.core.DATABASE_NAME", str(db_path))

    cog = object.__new__(LoggingCog)

    result = run(cog._get_legacy_log_channel(123, "ROLE_UPDATE_MEMBER"))

    assert result == 222

