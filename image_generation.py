import asyncio
import logging

import aiohttp
import discord
from discord import Interaction, ui

from config import GROK_IMAGE_MODEL, GROK_IMAGE_OUTPUT_COST, XAI_KEY


logger = logging.getLogger('GrokBot')

IMAGE_API_URL = "https://api.x.ai/v1/images/generations"
MORE_VERSIONS_CUSTOM_ID = "more_versions"


def _avatar_url(user):
    return user.avatar.url if getattr(user, 'avatar', None) else None


def _extract_prompt_from_embed(interaction: Interaction):
    if not interaction.message or not interaction.message.embeds:
        return None

    embed = interaction.message.embeds[0]
    if not embed.description or "**Prompt:**" not in embed.description:
        return None

    return embed.description.split("**Prompt:**", 1)[1].strip()


async def _request_single_image(prompt: str, session: aiohttp.ClientSession):
    """Request a single image from the Grok API. Returns URL or None on failure."""
    headers = {
        "Authorization": f"Bearer {XAI_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROK_IMAGE_MODEL,
        "prompt": prompt,
        "response_format": "url",
    }

    try:
        async with session.post(IMAGE_API_URL, headers=headers, json=payload) as resp:
            body = await resp.text()
            if resp.status not in (200, 201):
                logger.warning(f'Grok image API error {resp.status}: {body}')
                return None

            try:
                data = await resp.json()
            except Exception as exc:
                logger.warning(f'Grok image API returned non-JSON body: {body[:200]}')
                return None

        if isinstance(data, dict) and isinstance(data.get('data'), list):
            for img in data['data']:
                if isinstance(img, dict) and img.get('url'):
                    return img['url']

        logger.warning(f'No image URL in response: {data}')
        return None

    except Exception as e:
        logger.warning(f'Exception during image request: {e}')
        return None


async def _request_generated_images(prompt: str, count: int = 1):
    """
    Request `count` images concurrently, each as an individual API call.
    Returns a list of URLs for whichever requests succeeded.
    Raises RuntimeError if no images could be generated at all.
    """
    async with aiohttp.ClientSession() as session:
        tasks = [_request_single_image(prompt, session) for _ in range(count)]
        results = await asyncio.gather(*tasks)

    image_urls = [url for url in results if url is not None]

    if not image_urls:
        raise RuntimeError("All image generation attempts failed — no images returned by Grok")

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

            image_urls = await _request_generated_images(prompt, count=4)
            failed_count = 4 - len(image_urls)

            embeds = []
            bot_url = "https://astrixbot.cf"

            for idx, image_url in enumerate(image_urls):
                if idx == 0:
                    title = f"Grok AI Generated Images ({len(image_urls)} Version{'s' if len(image_urls) != 1 else ''})"
                    description = f"**Prompt:** {prompt}"
                    if failed_count > 0:
                        description += f"\n⚠️ {failed_count} of 4 generation{'s' if failed_count != 1 else ''} failed and were skipped."
                    embed = discord.Embed(
                        title=title,
                        description=description,
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
            image_url = (await _request_generated_images(prompt, count=1))[0]

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
