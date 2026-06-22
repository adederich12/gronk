"""End-to-end tests for the Grok query pipeline (grok_responder.handle_grok_query).

These drive the real handler with fake Discord I/O and a synthetic xAI SDK,
asserting on what the bot replies and what it stores.
"""

import grok_responder
from conftest import FakeAttachment


async def test_text_path_replies_and_stores(monkeypatch, bot, make_message):
    """Smoke test: the text path renders an answer and chains via response_id."""
    captured = {}
    monkeypatch.setattr(grok_responder, "store_conversation", lambda **kw: captured.update(kw))

    message = make_message(content="<@42> hello")
    await grok_responder.handle_grok_query(
        message=message,
        bot=bot,
        prompt="hello",
        image_urls=[],
        document_attachments=[],
        conversation_messages=[],
        previous_xai_response_id=None,
    )

    assert message.channel.sent, "bot did not reply"
    embed = message.channel.sent[-1]["embed"]
    assert embed is not None and embed.description, "no answer rendered"
    # The text path uses the xAI SDK and already chains conversations.
    assert captured.get("xai_response_id") == "resp_test_1"


async def test_vision_reply_captures_response_id(monkeypatch, bot, make_message):
    """Bug A: replying to a vision answer must continue the thread.

    The vision path must capture an xAI response id so main.py can chain the
    next reply via previous_response_id.
    """
    captured = {}
    monkeypatch.setattr(grok_responder, "store_conversation", lambda **kw: captured.update(kw))

    message = make_message(content="<@42> what is in this image?")
    await grok_responder.handle_grok_query(
        message=message,
        bot=bot,
        prompt="what is in this image?",
        image_urls=["https://example.com/cat.png"],
        document_attachments=[],
        conversation_messages=[],
        previous_xai_response_id=None,
    )

    assert message.channel.sent, "bot did not reply"
    assert captured.get("xai_response_id"), "vision path did not capture xai_response_id"


async def test_vision_cost_indicator_shown(monkeypatch, bot, make_message):
    """Bug B: the cost footer must reflect the vision pricing path."""
    monkeypatch.setattr(grok_responder, "store_conversation", lambda **kw: None)

    message = make_message(content="<@42> describe this")
    await grok_responder.handle_grok_query(
        message=message,
        bot=bot,
        prompt="describe this",
        image_urls=["https://example.com/cat.png"],
        document_attachments=[],
        conversation_messages=[],
        previous_xai_response_id=None,
    )

    embed = message.channel.sent[-1]["embed"]
    footer = (embed.footer.text or "").lower()
    assert "vision" in footer, f"vision cost indicator missing from footer: {embed.footer.text!r}"


async def test_vision_appends_image_part(monkeypatch, bot, make_message):
    """Bug A (mechanism): the vision request must send an image content part via the SDK."""
    import xai_sdk

    monkeypatch.setattr(grok_responder, "store_conversation", lambda **kw: None)

    message = make_message(content="<@42> describe this")
    await grok_responder.handle_grok_query(
        message=message,
        bot=bot,
        prompt="describe this",
        image_urls=["https://example.com/cat.png"],
        document_attachments=[],
        conversation_messages=[],
        previous_xai_response_id=None,
    )

    # An ("image", url, detail) part should have been appended to the SDK chat.
    image_parts = [
        part
        for entry in xai_sdk.control.appended
        if isinstance(entry, tuple) and entry[0] == "user"
        for part in entry[2]
        if isinstance(part, tuple) and part[0] == "image"
    ]
    assert image_parts, "vision path did not append an image part to the xAI SDK chat"
    assert image_parts[0][1] == "https://example.com/cat.png"


async def test_document_path_uploads_chains_and_cleans_up(monkeypatch, bot, make_message):
    """The document path uploads files, chains via response_id, and deletes them."""
    import xai_sdk

    captured = {}
    monkeypatch.setattr(grok_responder, "store_conversation", lambda **kw: captured.update(kw))

    message = make_message(content="<@42> summarize this")
    await grok_responder.handle_grok_query(
        message=message,
        bot=bot,
        prompt="summarize this",
        image_urls=[],
        document_attachments=[FakeAttachment("report.pdf")],
        conversation_messages=[],
        previous_xai_response_id=None,
    )

    assert message.channel.sent, "bot did not reply"
    assert captured.get("xai_response_id") == "resp_test_1"
    assert xai_sdk.control.files_uploaded, "no document was uploaded to xAI"
    assert xai_sdk.control.files_deleted, "uploaded document was not cleaned up"
