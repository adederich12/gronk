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

            image_urls = await _request_generated_images(prompt, count=4)
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
