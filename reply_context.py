import logging

from media_utils import collect_attachment_media, collect_embed_media, collect_image_urls_from_text


logger = logging.getLogger('GrokBot')


async def add_reply_context(message, prompt, image_urls, previous_xai_response_id):
    """Fetch nearby reply-chain context and append it to the prompt."""
    if not message.reference:
        return prompt

    if previous_xai_response_id:
        logger.info(f'Skipping context fetch - using xAI server-side conversation history (response ID: {previous_xai_response_id})')
        return prompt

    logger.info('Message is a reply, fetching conversation context...')
    try:
        reply_chain = []
        current_message = message
        max_depth = 10
        depth = 0

        while current_message.reference and depth < max_depth:
            try:
                replied_message = await message.channel.fetch_message(current_message.reference.message_id)
                reply_chain.insert(0, replied_message)
                current_message = replied_message
                depth += 1
            except Exception:
                break

        logger.info(f'Found {len(reply_chain)} messages in reply chain')

        context_messages = []
        time_window_seconds = 120

        if reply_chain:
            oldest_msg = reply_chain[0]

            try:
                before_messages = []
                async for msg in message.channel.history(limit=10, before=oldest_msg.created_at):
                    if msg.id != oldest_msg.id and not msg.author.bot:
                        time_diff = (oldest_msg.created_at - msg.created_at).total_seconds()
                        if time_diff <= time_window_seconds:
                            before_messages.append(msg)
                        else:
                            break
                before_messages.reverse()
                context_messages.extend(before_messages)
                logger.info(f'Found {len(before_messages)} recent messages before reply chain (within 2 min)')
            except Exception:
                pass

            context_messages.extend(reply_chain)

            try:
                newest_msg = reply_chain[-1]
                after_messages = []
                async for msg in message.channel.history(limit=10, after=newest_msg.created_at, oldest_first=True):
                    if msg.id != newest_msg.id and msg.id != message.id and not msg.author.bot:
                        time_diff = (msg.created_at - newest_msg.created_at).total_seconds()
                        if time_diff <= time_window_seconds:
                            after_messages.append(msg)
                        else:
                            break
                context_messages.extend(after_messages)
                logger.info(f'Found {len(after_messages)} messages after reply chain (within 2 min)')
            except Exception:
                pass

        for msg in context_messages:
            collect_attachment_media(msg, image_urls, context_label='context')
            collect_image_urls_from_text(msg.content, image_urls, context_label='context')
            collect_embed_media(msg.embeds, image_urls, context_label='context')

        if context_messages:
            context_parts = ["Here is the conversation context:\n"]
            for i, msg in enumerate(context_messages, 1):
                content = msg.content[:500] + "..." if len(msg.content) > 500 else msg.content
                context_parts.append(f"[{i}] {msg.author.name}: {content}")
            context_parts.append(f"\nUser's question: {prompt}")
            logger.info(f'Built context with {len(context_messages)} total messages')
            return "\n".join(context_parts)
    except Exception as e:
        logger.warning(f'Could not fetch conversation context: {e}')

    return prompt
