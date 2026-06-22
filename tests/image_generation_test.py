"""Tests for the comedy art director enrichment in image_generation."""

import image_generation
import xai_sdk


async def test_enrich_returns_enriched_prompt():
    xai_sdk.control.content = "a deadpan flash-lit photo of four men failing to start a band"
    out = await image_generation._enrich_prompt_for_comedy("us starting a band", channel_id=1)
    assert out == "a deadpan flash-lit photo of four men failing to start a band"


async def test_enrich_falls_back_to_original_on_error(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("xAI down")
    monkeypatch.setattr(image_generation, "sdk_chat_request", boom)

    out = await image_generation._enrich_prompt_for_comedy("us starting a band", channel_id=1)
    assert out == "us starting a band"


async def test_enrich_passthrough_when_disabled(monkeypatch):
    monkeypatch.setattr(image_generation, "ENABLE_COMEDY_DIRECTOR", False)
    out = await image_generation._enrich_prompt_for_comedy("us starting a band", channel_id=1)
    assert out == "us starting a band"


async def test_enrich_falls_back_on_empty_output():
    xai_sdk.control.content = "   "
    out = await image_generation._enrich_prompt_for_comedy("us starting a band", channel_id=1)
    assert out == "us starting a band"


async def test_generate_image_sends_enriched_but_shows_original(monkeypatch, make_message):
    """The image API gets the enriched prompt; the embed shows the user's original."""
    captured = {}

    async def fake_request(prompt, count=1):
        captured["prompt"] = prompt
        captured["count"] = count
        return ["https://img.test/1.png"]

    monkeypatch.setattr(image_generation, "_request_generated_images", fake_request)
    xai_sdk.control.content = "enriched: a sad garage band photo under harsh flash"

    message = make_message(content="<@42> generate an image of us starting a band")
    await image_generation.generate_image(message, "us starting a band")

    # Enriched prompt reached the image model.
    assert captured["prompt"] == "enriched: a sad garage band photo under harsh flash"
    # The embed still shows the user's original request (so the button/revision
    # flows re-enrich fresh rather than double-enriching).
    embed = message.channel.sent[-1]["embed"]
    assert "us starting a band" in embed.description
    assert "enriched:" not in embed.description
