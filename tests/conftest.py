"""Synthetic test harness for the Grok Discord bot.

Drives the real internal pipeline (routing, schemas, embed building, timezone
formatting) while faking only the external boundaries: the xAI SDK, the
OpenAI-compatible client, and Discord I/O. The real ``discord`` and ``pydantic``
libraries are used so embed validation and schema parsing are exercised for real.
"""

import os
import sys
import tempfile
from datetime import datetime, timezone

# --- Wire up import paths BEFORE any app module is imported ---------------------
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TESTS_DIR)
_FAKES_DIR = os.path.join(_TESTS_DIR, "fakes")
# Fakes first so xai_sdk/openai/spacy resolve to the synthetic ones; repo root so
# the bot modules import; real discord/pydantic/pytz come from the venv site-packages.
for path in (_FAKES_DIR, _REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

# --- Point persistent state at throwaway temp paths ----------------------------
_TMP = tempfile.mkdtemp(prefix="gronk-tests-")
os.environ.setdefault("CONVERSATION_DB_PATH", os.path.join(_TMP, "conversation_history.db"))
os.environ.setdefault("PERSONA_STORE_PATH", os.path.join(_TMP, "personas.json"))
os.environ.setdefault("DISCORD_TOKEN", "test-discord-token")
os.environ.setdefault("XAI_API_KEY", "test-xai-key")

import discord  # noqa: E402  (real library, after sys.path is set)
import pytest  # noqa: E402

import xai_sdk  # noqa: E402  (synthetic)
import openai  # noqa: E402  (synthetic)


# --- Fake Discord objects ------------------------------------------------------
class FakeUser:
    def __init__(self, user_id=1001, name="alice", display_name="Alice", bot=False):
        self.id = user_id
        self.name = name
        self.display_name = display_name
        self.bot = bot
        self.avatar = None

    @property
    def mention(self):
        return f"<@{self.id}>"

    def __eq__(self, other):
        return isinstance(other, FakeUser) and other.id == self.id

    def __hash__(self):
        return hash(self.id)


class _Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeChannel:
    def __init__(self, channel_id=2002):
        self.id = channel_id
        self.sent = []          # messages produced via message.reply()
        self._history = []      # messages returned by history()
        self._fetchable = {}    # id -> message for fetch_message()

    def typing(self):
        return _Typing()

    async def fetch_message(self, message_id):
        return self._fetchable[message_id]

    async def history(self, limit=100, **kwargs):
        for msg in self._history[:limit]:
            yield msg


_msg_counter = [9000]


class FakeMessage:
    def __init__(self, content="", author=None, channel=None, mentions=None,
                 attachments=None, embeds=None, reference=None, guild=None):
        _msg_counter[0] += 1
        self.id = _msg_counter[0]
        self.content = content
        self.author = author or FakeUser()
        self.channel = channel or FakeChannel()
        self.mentions = mentions or []
        self.attachments = attachments or []
        self.embeds = embeds or []
        self.reference = reference
        self.guild = guild
        self.created_at = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)

    async def reply(self, content=None, embed=None, embeds=None, view=None):
        reply_msg = FakeMessage(content=content or "", author=FakeUser(user_id=42, name="gronk"),
                                channel=self.channel)
        reply_msg.embeds = ([embed] if embed else []) + (embeds or [])
        record = {"content": content, "embed": embed, "embeds": reply_msg.embeds, "view": view}
        self.channel.sent.append(record)
        return reply_msg


class FakeAttachment:
    def __init__(self, filename="report.pdf", content=b"%PDF-1.4 synthetic", content_type=None):
        self.filename = filename
        self.url = f"https://cdn.discord.test/{filename}"
        self.content_type = content_type
        self._content = content

    async def save(self, path):
        with open(path, "wb") as fh:
            fh.write(self._content)


class FakeBot:
    def __init__(self, user_id=42):
        self.user = FakeUser(user_id=user_id, name="gronk", display_name="Gronk", bot=True)


# --- Fixtures ------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _init_db():
    """Create the conversation DB schema in the temp location once per run."""
    import conversation_store
    conversation_store.init_conversation_db()
    yield


@pytest.fixture(autouse=True)
def reset_fakes():
    """Reset synthetic SDK/OpenAI state before every test."""
    xai_sdk.control.reset()
    openai.control.reset()
    yield


@pytest.fixture
def bot():
    return FakeBot()


@pytest.fixture
def channel():
    return FakeChannel()


@pytest.fixture
def user():
    return FakeUser()


@pytest.fixture
def make_message():
    def _make(**kwargs):
        return FakeMessage(**kwargs)
    return _make
