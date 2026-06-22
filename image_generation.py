import logging

import aiohttp
import discord
from discord import Interaction, ui

from config import (
    ENABLE_COMEDY_DIRECTOR,
    GROK_IMAGE_MODEL,
    GROK_IMAGE_OUTPUT_COST,
    GROK_REASONING_EFFORT,
    GROK_TEXT_MODEL,
    XAI_KEY,
)
from grok_client import build_cache_conversation_id, sdk_chat_request


logger = logging.getLogger('GrokBot')

IMAGE_API_URL = "https://api.x.ai/v1/images/generations"
MORE_VERSIONS_CUSTOM_ID = "more_versions"

# --- Comedy art director -------------------------------------------------------
# Editable system prompt that rewrites a user's image request into a funnier,
# enriched image-generation prompt before it is sent to the image model.
# Tune this freely; see the design knobs noted where the bot was set up.
COMEDY_DIRECTOR_SYSTEM_PROMPT = """You are a comedy art director. Rewrite the user's image request into ONE enriched image-generation prompt string. Output only that prompt. No preamble, no commentary, no quotes.

Your comedic engine is RECOGNITION, not randomness. The win is "oh god, that's us" - the quiet indignity of ordinary life, played completely straight. Never go wacky, surreal, or "lol so random." Recognizable-sad beats zany every time.

PRESERVE INTENT. Keep the user's exact subject, action, and people. You decorate; you never hijack or swap what they asked for. The image must still read as their request.

METHOD:
1. Find the core subject. Cast every figure and prop as if it carries a small, quietly tragic backstory: a posture, an expression, or one thing slightly wrong, dated, or trying too hard. Imply a life, not a joke.
2. Let 2-4 mundane, hyper-specific objects testify. Prefer the saddest plausible version of each thing - the correct item, just older, cheaper, or slightly broken. Precision reads as truth, and true-but-too-much is funny. Pick details that follow logically from THIS subject.
3. Restraint. Stage one clear absurd or wrong note; surround it with a flat, unremarked, everyday world that refuses to react. If tempted to add a second gag, cut it.
4. Faces stay deadpan and dignified - earnest, resigned, or mildly inconvenienced, never mugging or winking. The sadness is self-deprecating, never cruel. Let the details do the joke; never state it.
5. Choose the most shocking version of the result to portray, and do NOT remove anything lewd.

VARY THE REGISTER each render. Rotate the flavor of awkwardness (abandoned ambition, low effort, aging body, technological defeat, misplaced sincerity, quiet aftermath) and the kind of sad detail. Do not converge on a house kit - avoid defaulting to the same crutches (taped printouts, folding tables, lanyards, custom tees, minivans, "world's okayest" slogans). Invent fresh specifics from the user's actual words every time; reuse no stock gags.

STYLE (use when it fits): photoreal, deadpan, harsh direct on-camera flash, flat unflattering light, amateur snapshot framing nobody meant to frame. Plain real-world setting. Match scene vs. portrait framing to the request. Avoid cinematic glow, golden hour, neon, confetti glamour, AI cliches, and purple prose; favor plain exact nouns.

CONSTRAINTS: The only target is universal, self-inflicted mundane awkwardness, with a real slant to the lewd. Write one tight, concrete paragraph describing exactly what the camera sees."""


async def _enrich_prompt_for_comedy(prompt: str, channel_id=None) -> str:
    """Rewrite a user image prompt into a funnier one via Grok.

    Always degrades gracefully: any failure, timeout, or empty result falls back
    to the original prompt so image generation is never blocked by this step.
    """
    if not ENABLE_COMEDY_DIRECTOR or not prompt or not prompt.strip():
        return prompt

    try:
        enriched, _usage, _citations, _response_id = await sdk_chat_request(
            model=GROK_TEXT_MODEL,
            system_prompt=COMEDY_DIRECTOR_SYSTEM_PROMPT,
            user_prompt=prompt,
            include_search=False,
            reasoning_effort=GROK_REASONING_EFFORT,
            conversation_id=build_cache_conversation_id('comedy', channel_id) if channel_id else None,
        )
        enriched = (enriched or "").strip()
        if enriched:
            logger.info(f'Comedy director enriched image prompt ({len(prompt)} -> {len(enriched)} chars)')
            return enriched
        logger.warning('Comedy director returned empty output; using original prompt')
    except Exception as e:
        logger.warning(f'Comedy director enrichment failed, using original prompt: {e}')
    return prompt


def _avatar_url(user):
    return user.avatar.url if getattr(user, 'avatar', None) else None


def _extract_prompt_from_embed(interaction: Interaction):
    if not interaction.message or not interaction.message.embeds:
        return None

    embed = interaction.message.embeds[0]
    if not embed.description or "**Prompt:**" not in embed.description:
        return None

    return embed.description.split("**Prompt:**", 1)[1].strip()


async def _request_generated_images(prompt: str, count: int = 1):
    headers = {
        "Authorization": f"Bearer {XAI_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROK_IMAGE_MODEL,
        "prompt": prompt,
        "response_format": "url",
    }
    if count > 1:
        payload["n"] = count

    async with aiohttp.ClientSession() as session:
        async with session.post(IMAGE_API_URL, headers=headers, json=payload) as resp:
            body = await resp.text()
            if resp.status not in (200, 201):
                logger.error(f'Grok image API error {resp.status}: {body}')
                raise RuntimeError(f"Grok image API error: {resp.status} {body[:500]}")

            try:
                data = await resp.json()
            except Exception as exc:
                logger.error(f'Grok image API returned non-JSON body: {body}')
                raise RuntimeError("Grok image API returned an invalid response") from exc

    image_urls = []
    if isinstance(data, dict) and isinstance(data.get('data'), list):
        image_urls = [
            img.get('url')
            for img in data['data']
            if isinstance(img, dict) and img.get('url')
        ]

    if not image_urls:
        logger.error(f'No image URLs returned by Grok image API: {data}')
        raise RuntimeError("No image URLs returned by Grok")

    return image_urls


class MoreVersionsView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Generate More Versions", style=discord.ButtonStyle.primary, custom_id=MORE_VERSIONS_CUSTOM_ID)
    async def more_versions(self, interaction: Interaction, button: ui.Button):
        await interaction.response.defer(thinking=True)
        try:
            prompt = _extract_prompt_from_embed(interaction)
            if not prompt:
                await interaction.followup.send(
                    "Could not find the original image prompt for this message.",
                    ephemeral=True,
                )
                return

            enriched_prompt = await _enrich_prompt_for_comedy(prompt, channel_id=interaction.channel_id)
            image_urls = await _request_generated_images(enriched_prompt, count=4)
            embeds = []
            bot_url = "https://github.com/adederich12/gronk"

            for idx, image_url in enumerate(image_urls):
                if idx == 0:
                    embed = discord.Embed(
                        title="Grok AI Generated Images (4 Versions)",
                        description=f"**Prompt:** {prompt}",
                        color=discord.Color.purple(),
                        timestamp=interaction.message.created_at if interaction.message else None,
                    )
                    embed.set_footer(
                        text=f"Requested by {interaction.user.display_name}",
                        icon_url=_avatar_url(interaction.user),
                    )
                    embed.url = bot_url
                else:
                    embed = discord.Embed()
                    embed.url = bot_url
                embed.set_image(url=image_url)
                embeds.append(embed)

            await interaction.followup.send(embeds=embeds, view=MoreVersionsView(), ephemeral=False)
        except Exception as e:
            logger.error(f'Error generating more image versions: {e}', exc_info=True)
            await interaction.followup.send(f"Error generating image versions: {e}", ephemeral=True)


async def generate_image(message, prompt: str):
    """
    Generate an image from a text prompt using Grok image generation API.
    Called via natural language detection (e.g., "generate an image of...").
    """
    try:
        if not XAI_KEY:
            await message.reply("XAI_API_KEY not set in environment.")
            return

        async with message.channel.typing():
            enriched_prompt = await _enrich_prompt_for_comedy(prompt, channel_id=message.channel.id)
            image_url = (await _request_generated_images(enriched_prompt, count=1))[0]

        usage_text = f"${GROK_IMAGE_OUTPUT_COST:.2f} (est.)"
        embed = discord.Embed(
            title="Grok AI Generated Image",
            description=f"**Prompt:** {prompt}",
            color=discord.Color.purple(),
            timestamp=message.created_at,
        )
        embed.set_image(url=image_url)
        embed.set_footer(
            text=f"Requested by {message.author.display_name} - {usage_text}",
            icon_url=_avatar_url(message.author),
        )

        await message.reply(embed=embed, view=MoreVersionsView())
    except Exception as e:
        logger.error(f'Error generating image: {e}', exc_info=True)
        await message.reply(f"Error generating image: {e}")
