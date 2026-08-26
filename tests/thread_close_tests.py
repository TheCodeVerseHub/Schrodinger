"""Tests for the legacy thread-based ticket close fallback."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from commands.thread import ThreadCloser


def run(coro):
    return asyncio.run(coro)


class FakeAttachment:
    def __init__(self, url: str):
        self.url = url


class FakeAuthor:
    def __init__(self, name: str):
        self.display_name = name


class FakeMessage:
    def __init__(self, content: str, author: str = "user", attachments=None):
        self.created_at = datetime.now(timezone.utc)
        self.content = content
        self.author = FakeAuthor(author)
        self.attachments = attachments or []


class FakeThread:
    def __init__(self, messages):
        self.id = 55
        self.name = "ticket-thread"
        self.guild = None
        self._messages = messages

    async def history(self, limit=None, oldest_first=True):
        for message in self._messages:
            yield message


class FakeLogChannel:
    def __init__(self):
        self.sent = []

    async def send(self, **kwargs):
        self.sent.append(kwargs)


def test_legacy_thread_transcript_is_sent_to_ticket_log_channel():
    thread = FakeThread(
        [
            FakeMessage("hello"),
            FakeMessage("with file", attachments=[FakeAttachment("https://example.com/file.txt")]),
        ]
    )
    log_channel = FakeLogChannel()
    guild = SimpleNamespace(
        id=123,
        get_channel=lambda cid: log_channel if cid == 999 else None,
        text_channels=[],
    )
    thread.guild = guild

    closer = ThreadCloser(bot=SimpleNamespace())
    closer._get_ticket_log_channel = lambda g: log_channel

    transcript = run(closer._generate_thread_transcript(thread, ticket_id=7))

    assert transcript is not None
    assert "Ticket #7 Transcript" in transcript
    assert "hello" in transcript
    assert "https://example.com/file.txt" in transcript
    assert log_channel.sent
    sent = log_channel.sent[0]
    assert sent["embed"].title == "Ticket #7 Transcript"
    assert sent["file"].filename == "ticket-7-transcript.txt"

