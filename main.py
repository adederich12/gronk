import discord
from discord.ext import commands
import logging
import re

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

    if message.author == bot.user:
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
    previous_xai_response_id = None  # For xAI Chat Responses API continuation

    if message.reference:
        try:
            replied_msg = await message.channel.fetch_message(message.reference.message_id)
            is_replying_to_bot = replied_msg.author == bot.user

            # Check if we have a stored xAI response ID for this conversation
            if is_replying_to_bot:
                stored_convo = get_conversation(replied_msg.id)
                if stored_convo and stored_convo.get('xai_response_id'):
                    previous_xai_response_id = stored_convo['xai_response_id']
                    logger.info(f'Found previous xAI response ID: {previous_xai_response_id}')
        except:
            pass

    if not (is_bot_mentioned or is_replying_to_bot):
        await bot.process_commands(message)
        return

    if is_replying_to_bot:
        logger.info(f'Bot reply detected from {message.author} in #{message.channel}')
    else:
        logger.info(f'Bot mentioned by {message.author} in #{message.channel}')

    # Normalize prompt: remove all bot mentions and extra whitespace
    prompt = message.content
    prompt = re.sub(r'<@!?' + str(bot.user.id) + r'>', '', prompt)
    prompt = prompt.strip()
    logger.info(f'Normalized prompt for intent detection: "{prompt}"')

    # --- PERSONA HANDLING ---
    if is_persona_request(prompt):
        await handle_persona_request(message, prompt)
        return
    if is_replying_to_bot and replied_msg and replied_msg.embeds:
        if any(embed.title and "Persona" in embed.title for embed in replied_msg.embeds):
            await handle_persona_request(message, f"refine current persona: {prompt}")
            return

    # --- DISCORD HISTORY SEARCH ---
    # Skip if we're replying to a bot message with stored conversation context
    if ENABLE_NL_HISTORY_SEARCH and not previous_xai_response_id:
        target_user = message.mentions[0] if message.mentions and message.mentions[0] != bot.user else None
        should_search, time_limit, keywords = await should_search_discord_history(prompt, target_user is not None)
        logger.info(f'should_search_discord_history result: should_search={should_search}, time_limit={time_limit}, keywords={keywords}')
        if should_search:
            logger.info(f'Discord history search triggered for query: {prompt}')
            await perform_discord_history_search(
                message=message,
                query=prompt,
                time_limit=time_limit,
                keywords=keywords,
                target_user=target_user
            )
            return
    elif previous_xai_response_id:
        logger.info(f'Skipping Discord history search check - using stored conversation context (xAI response ID: {previous_xai_response_id})')

    # --- IMAGE REVISION DETECTION ---
    # If replying to a bot-generated image, treat as a revision request
    if is_replying_to_bot and replied_msg and replied_msg.embeds:
        for embed in replied_msg.embeds:
            if embed.title and "Grok AI Generated Image" in embed.title and embed.description:
                original_prompt_match = re.search(r'\*\*Prompt:\*\*\s*(.+)', embed.description)
                if original_prompt_match:
                    original_prompt = original_prompt_match.group(1).strip()
                    revised_prompt = f"{original_prompt}. Revision: {prompt}"
                    logger.info(f'Detected image revision request. Original: "{original_prompt}", Revision: "{prompt}"')
                    await generate_image(message, revised_prompt)
                    return

    # --- IMAGE GENERATION DETECTION ---
    nlp_result = advanced_nlp_parse(prompt)
    is_image_request = nlp_result.get('intent') == 'image_generation'
    if is_image_request:
        logger.info('Detected image generation intent in natural language')
        await generate_image(message, prompt)
        return

    # --- COLLECT MEDIA ---
    collect_attachment_media(
        message,
        image_urls,
        document_attachments=document_attachments,
        unsupported_images=unsupported_images,
        unsupported_docs=unsupported_docs,
    )
    collect_image_urls_from_text(message.content, image_urls)
    collect_embed_media(message.embeds, image_urls)

    prompt = await add_reply_context(message, prompt, image_urls, previous_xai_response_id)

    if not prompt and not image_urls and not document_attachments:
        logger.warning('No prompt, images, or documents found')
        await message.reply("Please provide a question, image, or document after mentioning me.")
        return

    # Notify user about unsupported images if any
    if unsupported_images and not image_urls:
        await message.reply(f"Found unsupported image format(s): {', '.join(unsupported_images)}\n\nGrok only supports: JPEG, PNG, and WebP images.")
        return
    elif unsupported_images:
        logger.info(f'Proceeding with {len(image_urls)} supported images, ignoring {len(unsupported_images)} unsupported')

    await handle_grok_query(
        message=message,
        bot=bot,
        prompt=prompt,
        image_urls=image_urls,
        document_attachments=document_attachments,
        conversation_messages=conversation_messages,
        previous_xai_response_id=previous_xai_response_id,
    )

if __name__ == "__main__":
    bot.run(TOKEN)
