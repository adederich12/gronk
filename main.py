import asyncio
import logging
import re
import time

import discord
from discord.ext import commands

from config import (
    ENABLE_NL_HISTORY_SEARCH,
    TOKEN,
)
from conversation_store import (
    cleanup_old_conversations,
    get_conversation,
    init_conversation_db,
    periodic_cleanup,
)
from discord_history import perform_discord_history_search, should_search_discord_history
from grok_responder import handle_grok_query
from image_generation import MoreVersionsView, generate_image
from media_utils import collect_attachment_media, collect_embed_media, collect_image_urls_from_text
from nlp_utils import advanced_nlp_parse
from persona_manager import handle_persona_request, is_persona_request
from reply_context import add_reply_context

bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

logger = logging.getLogger('GrokBot')

# Initialize database on startup
init_conversation_db()

# Per-user cooldown tracking: {user_id: last_request_timestamp}
USER_COOLDOWNS = {}
COOLDOWN_SECONDS = 20


def _is_on_cooldown(user_id: int) -> float:
    """Returns seconds remaining on cooldown, or 0 if not on cooldown."""
    last = USER_COOLDOWNS.get(user_id, 0)
    elapsed = time.monotonic() - last
    remaining = COOLDOWN_SECONDS - elapsed
    return remaining if remaining > 0 else 0


def _set_cooldown(user_id: int):
    USER_COOLDOWNS[user_id] = time.monotonic()


@bot.event
async def on_ready():
    logger.info(f'Bot logged in as {bot.user} (ID: {bot.user.id})')
    logger.info(f'Connected to {len(bot.guilds)} server(s)')
    bot.add_view(MoreVersionsView())

    # Clean up old conversations on startup
    cleanup_old_conversations()

    # Schedule periodic cleanup (every 6 hours)
    bot.loop.create_task(periodic_cleanup())

@bot.event
async def on_message(message):
    logger.info(f'[MSG] Received message from {message.author} in #{message.channel}: "{message.content[:100]}"')

    if message.author == bot.user:
        logger.info('[MSG] Ignoring message from self')
        return

    # Initialize variables to avoid NameError
    image_urls = []
    unsupported_images = []
    document_attachments = []
    unsupported_docs = []
    conversation_messages = []

    # Check if bot is mentioned OR if user is replying to bot's message
    is_bot_mentioned = bot.user in message.mentions
    is_replying_to_bot = False
    replied_msg = None
    previous_xai_response_id = None

    logger.info(f'[MSG] is_bot_mentioned={is_bot_mentioned}, has_reference={message.reference is not None}')

    if message.reference:
        try:
            replied_msg = await message.channel.fetch_message(message.reference.message_id)
            is_replying_to_bot = replied_msg.author == bot.user
            logger.info(f'[MSG] Reply to message by {replied_msg.author}, is_replying_to_bot={is_replying_to_bot}')

            if is_replying_to_bot:
                stored_convo = get_conversation(replied_msg.id)
                if stored_convo and stored_convo.get('xai_response_id'):
                    previous_xai_response_id = stored_convo['xai_response_id']
                    logger.info(f'[MSG] Found previous xAI response ID: {previous_xai_response_id}')
                else:
                    logger.info('[MSG] No stored xAI response ID found for replied message')
        except Exception as e:
            logger.warning(f'[MSG] Failed to fetch replied message: {e}')

    if not (is_bot_mentioned or is_replying_to_bot):
        logger.info('[MSG] Bot not mentioned and not a reply to bot — ignoring')
        await bot.process_commands(message)
        return

    # --- COOLDOWN CHECK ---
    user_id = message.author.id
    remaining = _is_on_cooldown(user_id)
    if remaining > 0:
        logger.info(f'[COOLDOWN] User {message.author} is on cooldown for {remaining:.1f}s more')
        await message.reply(
            f"⏳ Please wait {remaining:.0f} more second{'s' if remaining >= 2 else ''} before sending another request.",
            delete_after=5,
        )
        return
    _set_cooldown(user_id)
    logger.info(f'[COOLDOWN] Cooldown set for user {message.author}')

    if is_replying_to_bot:
        logger.info(f'[FLOW] Bot reply detected from {message.author} in #{message.channel}')
    else:
        logger.info(f'[FLOW] Bot mentioned by {message.author} in #{message.channel}')

    # Normalize prompt
    prompt = message.content
    prompt = re.sub(r'<@!?' + str(bot.user.id) + r'>', '', prompt)
    prompt = prompt.strip()
    logger.info(f'[FLOW] Normalized prompt: "{prompt}"')

    # --- PERSONA HANDLING ---
    persona_check = is_persona_request(prompt)
    logger.info(f'[FLOW] is_persona_request={persona_check}')
    if persona_check:
        logger.info('[FLOW] Routing to persona handler')
        await handle_persona_request(message, prompt)
        return

    if is_replying_to_bot and replied_msg and replied_msg.embeds:
        has_persona_embed = any(embed.title and "Persona" in embed.title for embed in replied_msg.embeds)
        logger.info(f'[FLOW] Replied to bot embed, has_persona_embed={has_persona_embed}')
        if has_persona_embed:
            logger.info('[FLOW] Routing to persona refinement handler')
            await handle_persona_request(message, f"refine current persona: {prompt}")
            return

    # --- DISCORD HISTORY SEARCH ---
    logger.info(f'[FLOW] ENABLE_NL_HISTORY_SEARCH={ENABLE_NL_HISTORY_SEARCH}, previous_xai_response_id={previous_xai_response_id}')
    if ENABLE_NL_HISTORY_SEARCH and not previous_xai_response_id:
        target_user = message.mentions[0] if message.mentions and message.mentions[0] != bot.user else None
        logger.info(f'[FLOW] Checking Discord history search, target_user={target_user}')
        should_search, time_limit, keywords = await should_search_discord_history(prompt, target_user is not None)
        logger.info(f'[FLOW] should_search={should_search}, time_limit={time_limit}, keywords={keywords}')
        if should_search:
            logger.info('[FLOW] Routing to Discord history search')
            await perform_discord_history_search(
                message=message,
                query=prompt,
                time_limit=time_limit,
                keywords=keywords,
                target_user=target_user
            )
            return
    elif previous_xai_response_id:
        logger.info('[FLOW] Skipping Discord history search — using stored conversation context')

    # --- IMAGE REVISION DETECTION ---
    if is_replying_to_bot and replied_msg and replied_msg.embeds:
        logger.info('[FLOW] Checking for image revision in replied embeds')
        for embed in replied_msg.embeds:
            if embed.title and "Grok AI Generated Image" in embed.title and embed.description:
                original_prompt_match = re.search(r'\*\*Prompt:\*\*\s*(.+)', embed.description)
                if original_prompt_match:
                    original_prompt = original_prompt_match.group(1).strip()
                    revised_prompt = f"{original_prompt}. Revision: {prompt}"
                    logger.info(f'[FLOW] Image revision detected. Revised prompt: "{revised_prompt}"')
                    await generate_image(message, revised_prompt)
                    return
        logger.info('[FLOW] No image revision detected in embeds')

    # --- IMAGE GENERATION DETECTION ---
    logger.info('[FLOW] Running NLP intent detection for image generation')
    nlp_result = advanced_nlp_parse(prompt)
    is_image_request = nlp_result.get('intent') == 'image_generation'
    logger.info(f'[FLOW] NLP result: {nlp_result}, is_image_request={is_image_request}')
    if is_image_request:
        logger.info('[FLOW] Routing to image generation')
        await generate_image(message, prompt)
        return

    # --- COLLECT MEDIA ---
    logger.info('[FLOW] Collecting media attachments')
    collect_attachment_media(
        message,
        image_urls,
        document_attachments=document_attachments,
        unsupported_images=unsupported_images,
        unsupported_docs=unsupported_docs,
    )
    collect_image_urls_from_text(message.content, image_urls)
    collect_embed_media(message.embeds, image_urls)
    logger.info(f'[FLOW] Media collected: image_urls={len(image_urls)}, documents={len(document_attachments)}, unsupported_images={len(unsupported_images)}')

    prompt = await add_reply_context(message, prompt, image_urls, previous_xai_response_id)
    logger.info(f'[FLOW] Prompt after reply context: "{str(prompt)[:200]}"')

    if not prompt and not image_urls and not document_attachments:
        logger.warning('[FLOW] No prompt, images, or documents found — sending help message')
        await message.reply("Please provide a question, image, or document after mentioning me.")
        return

    if unsupported_images and not image_urls:
        logger.info(f'[FLOW] Only unsupported images found: {unsupported_images}')
        await message.reply(f"Found unsupported image format(s): {', '.join(unsupported_images)}\n\nGrok only supports: JPEG, PNG, and WebP images.")
        return
    elif unsupported_images:
        logger.info(f'[FLOW] Proceeding with {len(image_urls)} supported images, ignoring {len(unsupported_images)} unsupported')

    logger.info('[FLOW] Routing to handle_grok_query')
    await handle_grok_query(
        message=message,
        bot=bot,
        prompt=prompt,
        image_urls=image_urls,
        document_attachments=document_attachments,
        conversation_messages=conversation_messages,
        previous_xai_response_id=previous_xai_response_id,
    )
    logger.info('[FLOW] handle_grok_query completed')

if __name__ == "__main__":
    bot.run(TOKEN)
