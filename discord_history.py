import logging
import json
import re

import discord

from config import (
    DEFAULT_SEARCH_LIMIT,
    GROK_ANALYSIS_REASONING_EFFORT,
    GROK_TEXT_INPUT_COST,
    GROK_TEXT_MODEL,
    GROK_TEXT_OUTPUT_COST,
    MAX_KEYWORD_SCAN,
    MAX_MESSAGES_ANALYZED,
    TIMEZONE,
)
from discord_utils import convert_usernames_to_mentions
from grok_client import build_cache_conversation_id, sdk_chat_request
from grok_schemas import DiscordHistoryAnswer
from nlp_utils import advanced_nlp_parse


logger = logging.getLogger('GrokBot')


BOT_PING_PHRASES = [
    "are you there", "are you working", "are you online", "are you up",
    "are you alive", "yo", "ping", "test", "hello", "hi", "hey",
    "you here", "up?", "working?", "online?", "alive?", "present?", "awake?"
]

DISCORD_SCOPE_PATTERNS = [
    r'\b(in|on|from|of|for)\s+(this|the|our)\s+(channel|server|discord|chat)\b',
    r'\b(this|the|our)\s+(channel|server|discord|chat)\b',
    r'\bin\s+here\b',
    r'\bhere\s+in\s+(this|the)\s+(channel|server|discord|chat)\b',
]

GENERAL_CONTEXT_PATTERNS = [
    r'\bin history\b',
    r'\bin the world\b',
    r'\bon (twitter|x\.com|x)\b',
    r'\bin the news\b',
    r'\bglobally\b',
    r'\bworldwide\b',
    r'\bscientists say\b',
    r'\bresearchers found\b',
    r'\bstudies show\b',
    r'\baccording to\b',
    r'\bnews\b',
    r'\bcurrent events?\b',
]

GENERAL_QUESTION_PATTERNS = [
    r'\bwhat (is|are|was|were)\b',
    r'\bhow (does|do|did|can|much|many|high|low|far)\b',
    r'\bwhy (does|do|did|is|are)\b',
    r'\bwhere (is|are|does|do)\b',
    r'\bwhen (is|are|does|do|did)\b',
    r'\bwho (is|are|was|were)\b',
    r'\bexplain\b',
    r'\btell me about\b',
    r'\bdescribe\b',
]

DISCORD_ANALYSIS_PATTERNS = [
    r'\bwho\s+(talks?|mentions?|discusses?|posts?|says?|said|chats?|sent|shared)\b',
    r'\bwhat\s+(have|has|did|do)\s+(we|users?|people|members?)\s+(talk|say|said|discuss|mention|post|share|send)\b',
    r'\b(summarize|summary|overview|recap)\b',
    r'\b(most|least|top|bottom)\b',
    r'\bhow\s+(often|many|much)\b',
    r'\brank\s+(members?|users?|people)\b',
    r'\b(search|scan|look through|check)\b',
]

DISCORD_ACTIVITY_PATTERNS = [
    r'\b(talked|talks|mentioned|mentions|discussed|discusses|posted|posts|sent|shared|said|chatted|messaged)\b',
]

DISCORD_HISTORY_NOUN_PATTERNS = [
    r'\b(messages?|conversation|conversations|chat|history|threads?|posts?)\b',
]

DISCORD_PRONOUN_PATTERNS = [
    r'\b(we|us|our)\b',
]

NON_MEANINGFUL_KEYWORDS = {
    "we", "us", "our", "discord", "chat", "talking", "about", "in", "the",
    "what", "are", "is", "on", "this", "server", "channel", "here", "people",
    "users", "members", "who", "they", "them", "he", "she", "it", "that",
    "these", "those", "message", "messages", "conversation", "conversations",
    "last week", "last month", "past week", "past month", "recently",
    "this channel", "this server", "this discord", "this chat",
    "our conversations", "rank members", "activity", "the top users", "top users"
}


def _has_any(patterns, text):
    return any(re.search(pattern, text) for pattern in patterns)


def _is_bot_ping(text):
    return any(re.search(rf'(?<!\w){re.escape(phrase)}(?!\w)', text) for phrase in BOT_PING_PHRASES)


async def should_search_discord_history(message_content, has_mentions):
    """
    Determine if the user query is asking to search Discord history.
    
    Returns:
        tuple: (should_search: bool, time_limit: Optional[int], target_keywords: Optional[str])
    """
    content_lower = message_content.lower()

    # 0. BOT STATUS CHECKS - If the query is just a ping or status check, do NOT trigger Discord search
    if has_mentions and _is_bot_ping(content_lower):
        logger.info('Bot ping/status check detected, not a Discord search')
        return False, None, None

    has_scope = _has_any(DISCORD_SCOPE_PATTERNS, content_lower)
    has_discord_pronoun = _has_any(DISCORD_PRONOUN_PATTERNS, content_lower)
    has_analysis = _has_any(DISCORD_ANALYSIS_PATTERNS, content_lower)
    has_activity = _has_any(DISCORD_ACTIVITY_PATTERNS, content_lower)
    has_history_noun = _has_any(DISCORD_HISTORY_NOUN_PATTERNS, content_lower)
    has_general_context = _has_any(GENERAL_CONTEXT_PATTERNS, content_lower)
    has_general_question = _has_any(GENERAL_QUESTION_PATTERNS, content_lower)

    if has_general_context and not has_scope:
        logger.info('General query detected: general context indicator found')
        return False, None, None

    # Mentions alone are usually "ask this person" or "what do you think of them",
    # not "search their history". Require a history/search/activity cue too.
    if has_mentions:
        if has_scope or has_analysis or has_activity or has_history_noun:
            logger.info('Discord search detected: mention plus Discord history cue')
            time_limit = extract_time_period(content_lower)
            keywords = extract_keywords(content_lower)
            if not keywords or keywords.lower() in NON_MEANINGFUL_KEYWORDS:
                keywords = None
            return True, time_limit, keywords
        logger.info('Mention without history cue detected, treating as general query')
        return False, None, None

    # Strong explicit scope + analysis/activity cue.
    if has_scope and (has_analysis or has_activity or has_discord_pronoun or has_history_noun):
        logger.info('Discord search detected: explicit Discord scope with history cue')
        time_limit = extract_time_period(content_lower)
        keywords = extract_keywords(content_lower)
        if not keywords or keywords.lower() in NON_MEANINGFUL_KEYWORDS:
            keywords = None
        return True, time_limit, keywords

    # "What have we discussed..." style queries are Discord-ish, but only when
    # paired with actual discussion/history wording.
    if has_discord_pronoun and (has_analysis or has_activity or has_history_noun):
        logger.info('Discord search detected: Discord pronoun with analysis/activity cue')
        time_limit = extract_time_period(content_lower)
        keywords = extract_keywords(content_lower)
        return True, time_limit, keywords

    if has_general_question:
        logger.info('General query detected: general question pattern found')
    else:
        logger.info('No Discord history trigger found')
    return False, None, None

def extract_time_period(content_lower):
    """
    Check if query mentions a time period.
    Returns DEFAULT_SEARCH_LIMIT if time period mentioned, None otherwise.
    Note: We don't try to map time periods to message counts since Discord 
    activity varies wildly - use DEFAULT_SEARCH_LIMIT for all temporal queries.
    """
    time_patterns = [
        r'past\s*month|last\s*month|30\s*days',
        r'past\s*week|last\s*week|7\s*days',
        r'past\s*day|last\s*day|24\s*hours|today',
        r'past\s*year|last\s*year',
        r'recently',
    ]
    
    for pattern in time_patterns:
        if re.search(pattern, content_lower):
            logger.debug(f'Time period mentioned, using DEFAULT_SEARCH_LIMIT')
            return DEFAULT_SEARCH_LIMIT
    
    return None  # No time period specified

def extract_keywords(content_lower):
    """Extract topic keywords and entities from the query using advanced NLP."""
    topic_patterns = [
        r'\babout\s+(.+)$',
        r'\bregarding\s+(.+)$',
        r'\bon\s+(.+)$',
        r'\bfor\s+(.+)$',
    ]
    for pattern in topic_patterns:
        match = re.search(pattern, content_lower)
        if match:
            topic = _clean_keyword(match.group(1))
            if topic:
                return topic

    nlp_results = advanced_nlp_parse(content_lower)
    # Prefer named entities and noun chunks as keywords
    keywords = []
    if nlp_results['entities']:
        keywords.extend([ent[0] for ent in nlp_results['entities']])
    if nlp_results['topics']:
        keywords.extend(nlp_results['topics'])
    # Remove duplicates, preserve order
    seen = set()
    keywords = [
        cleaned for item in keywords
        if (cleaned := _clean_keyword(item)) and not (cleaned in seen or seen.add(cleaned))
    ]
    # Log extracted info
    logger.info(f"NLP Extracted entities: {nlp_results['entities']}, topics: {nlp_results['topics']}, intent: {nlp_results['intent']}")
    # Return the most relevant keyword or a comma-separated string
    if keywords:
        return ', '.join(keywords)
    return None


def _clean_keyword(keyword):
    keyword = re.sub(r'<@!?\d+>', ' ', keyword)
    keyword = re.sub(r'@\w+', ' ', keyword)
    keyword = re.sub(r'\b(in|on|from|of|for|this|the|our)\s+(channel|server|discord|chat)\b', ' ', keyword)
    keyword = re.sub(r'\b(past|last|this)\s+(day|week|month|year)\b', ' ', keyword)
    keyword = re.sub(r'\b(recently|today|yesterday)\b', ' ', keyword)
    keyword = re.sub(r'[^a-z0-9_ .-]+', ' ', keyword.lower())
    keyword = re.sub(r'\s+', ' ', keyword).strip(' .-')
    if not keyword or keyword in NON_MEANINGFUL_KEYWORDS:
        return None
    if len(keyword) < 2:
        return None
    return keyword

async def perform_discord_history_search(message, query, time_limit=None, keywords=None, target_user=None):
    """
    Search Discord history and analyze with Grok
    
    Args:
        message: Discord message object
        query: User's search query
        time_limit: Optional number of messages to scan
        keywords: Optional keyword to pre-filter messages
        target_user: Optional user to search (if mentioned)
    """
    # Determine if we should use keyword filtering
    use_keyword_filter = keywords is not None
    
    # Determine scan limit based on whether we have keyword filter
    if use_keyword_filter:
        # For keyword searches, scan more to find enough matching messages
        if time_limit is None:
            time_limit = DEFAULT_SEARCH_LIMIT
        max_scan = min(time_limit, MAX_KEYWORD_SCAN)
    else:
        # For general searches, only scan what we can send to Grok
        max_scan = MAX_MESSAGES_ANALYZED
        time_limit = max_scan
    
    # Send searching message
    if target_user:
        if use_keyword_filter:
            searching_msg = await message.reply(f"🔍 Analyzing {target_user.mention}'s messages about `{keywords}` (scanning up to {time_limit:,} messages)...")
        else:
            searching_msg = await message.reply(f"🔍 Analyzing {target_user.mention}'s message history (last {max_scan:,} messages)...")
    else:
        if use_keyword_filter:
            searching_msg = await message.reply(f"🔍 Analyzing channel messages about `{keywords}` (scanning up to {time_limit:,} messages)...")
        else:
            searching_msg = await message.reply(f"🔍 Analyzing channel message history (last {max_scan:,} messages)...")
    
    try:
        # Collect messages
        collected_messages = []
        messages_scanned = 0
        last_update = 0
        
        async for msg in message.channel.history(limit=max_scan):
            # Skip the command message
            if msg.id == message.id:
                logger.debug(f"Skipping command message id={msg.id}")
                continue

            messages_scanned += 1

            # Apply filters, but log why messages are skipped
            if target_user and msg.author != target_user:
                logger.debug(f"Skipping message id={msg.id} (author {msg.author} != target_user {target_user})")
                continue

            if not target_user and msg.author.bot:
                logger.debug(f"Skipping message id={msg.id} (author is bot)")
                continue

            if use_keyword_filter and keywords.lower() not in msg.content.lower():
                logger.debug(f"Skipping message id={msg.id} (keyword '{keywords}' not in content)")
                continue

            # Only skip empty messages (no content) for non-targeted searches
            if not msg.content.strip():
                logger.debug(f"Skipping message id={msg.id} (empty content)")
                continue

            collected_messages.append(msg)

            # Update progress every 2000 messages
            if messages_scanned - last_update >= 2000:
                last_update = messages_scanned
                try:
                    progress_pct = int((messages_scanned / time_limit) * 100)
                    await searching_msg.edit(content=f"🔍 Analyzing... ({progress_pct}% - scanned {messages_scanned:,}, found {len(collected_messages):,})")
                except Exception as e:
                    logger.debug(f"Progress update failed: {e}")
        
        if not collected_messages:
            await searching_msg.edit(content=f"❌ No messages found matching your criteria.")
            return
        
        logger.info(f'Found {len(collected_messages)} messages for analysis')
        
        # Build context for Grok (configurable limit via MAX_MESSAGES_ANALYZED)
        messages_to_analyze = min(len(collected_messages), MAX_MESSAGES_ANALYZED)
        messages_for_context = collected_messages[:messages_to_analyze]
        
        # Explicitly tell Grok that @gronk and 'gronk' refer to the AI itself, and place this at the top of the prompt
        context_parts = [
            (
                "SYSTEM: You are 'gronk', the AI assistant and Discord bot. 'gronk' is a Discord bot interface for interacting with Grok the AI. "
                "Any mention of 'gronk' or '@gronk' in the following messages refers to you, the AI, and NEVER the user. "
                "Never refer to the user as 'gronk' or '@gronk'. Always refer to yourself as 'gronk' or '@gronk' when those names are mentioned. "
                "You are the AI behind the 'gronk' Discord bot, and all responses from 'gronk' are from the AI assistant. "
                "When referring to users, use either their mention or their user ID, but not both in the same phrase. Avoid redundant references like '@username (user ID @123)'. "
                "NEVER output patterns like '@useridnumber (which appears to be @gronk)', '@useridnumber (which is @gronk)', or any similar construction. If a user is the bot, always use only '@gronk' and never the user ID or both together.\n"
            ),
            f"User query: {query}\n"
        ]


        if target_user:
            context_parts.append(f"Analyzing user {target_user.name}'s messages (showing {messages_to_analyze} of {len(collected_messages)} found, oldest to newest):\n")
        else:
            context_parts.append(f"Analyzing channel messages (showing {messages_to_analyze} of {len(collected_messages)} found, oldest to newest):\n")
        
        message_number_map = {}
        for i, msg in enumerate(reversed(messages_for_context), 1):
            timestamp_local = msg.created_at.astimezone(TIMEZONE)
            tz_abbr = timestamp_local.strftime("%Z")
            timestamp_str = timestamp_local.strftime(f"%Y-%m-%d %H:%M {tz_abbr}")
            author_name = msg.author.name if not target_user else ""
            content = msg.content[:300] + "..." if len(msg.content) > 300 else msg.content
            message_number_map[i] = msg
            # Provide real metadata for each message in the JSON block only, not in the visible context
            # Visible context: just number, timestamp, author, and content
            if target_user:
                context_parts.append(f"[{i}] [{timestamp_str}] {content}")
            else:
                context_parts.append(f"[{i}] [{timestamp_str}] {author_name}: {content}")
            # Metadata for JSON block (unchanged, used later)
            # meta = { ... }


        # Add message metadata mapping for Grok to use in citations
        context_parts.append("\n\nMessage Metadata Mapping:")
        for i, msg in enumerate(reversed(messages_for_context), 1):
            excerpt = msg.content[:80].replace('\\', ' ').replace('"', "'")
            context_parts.append(f"{i}: {{'message_id': '{msg.id}', 'channel_id': '{msg.channel.id}', 'user_id': '{msg.author.id}', 'excerpt': '{excerpt}', 'link': 'https://discord.com/channels/{msg.guild.id}/{msg.channel.id}/{msg.id}'}}")

        # (Instruction moved to top of prompt for clarity)

        # INSTRUCT GROK TO REPLY ONLY WITH JSON and use only [#N] for citations, using the above mapping for sources
        context_parts.append(f"\n\nBased on these messages, reply ONLY with a single JSON object in the following format. Do NOT include any natural language or commentary before or after the JSON. Only cite the most meaningful and relevant messages (typically 3-6), and do NOT cite every message. For each citation in your answer, use the metadata from the mapping above for the corresponding number in the 'sources' field.\n")
        context_parts.append("""
{
    \"answer\": \"<your answer, with inline citations like [#N] ONLY. Do NOT include channel names, emojis, or any extra formatting in the citations. Use only [#N] for each citation.>\",
    \"sources\": {
        \"N\": {
            \"message_id\": \"<discord message id from mapping>\",
            \"channel_id\": \"<discord channel id from mapping>\",
            \"user_id\": \"<discord user id from mapping>\",
            \"excerpt\": \"<short excerpt from the message>\",
            \"link\": \"<discord message link from mapping>\"
        },
        ...
    },
    \"confidence\": <float between 0 and 1>
}
""")
        context_parts.append("\nIMPORTANT: For every citation, use ONLY the format [#N] with no channel name, emoji, or extra formatting. Example: [#1], [#2], etc.\n")
        full_prompt = "\n".join(context_parts)
        
        # Query Grok using SDK (no web search for Discord history analysis)
        async with message.channel.typing():
            system_prompt = "You are a helpful assistant analyzing Discord message history. Follow JSON output format exactly."
            response, usage, _, _ = await sdk_chat_request(
                model=GROK_TEXT_MODEL,
                system_prompt=system_prompt,
                user_prompt=full_prompt,
                include_search=False,  # Don't web search for Discord history
                response_format=DiscordHistoryAnswer,
                reasoning_effort=GROK_ANALYSIS_REASONING_EFFORT,
                conversation_id=build_cache_conversation_id('history', message.channel.id, message.author.id),
            )

            # --- Begin JSON extraction and parsing ---
            import json as _json
            import re as _re
            json_match = _re.search(r'\{[\s\S]*\}$', response)
            if json_match:
                json_str = json_match.group(0)
                try:
                    data = _json.loads(json_str)
                    answer = data.get("answer", "")
                    sources = data.get("sources", {})
                except Exception as e:
                    answer = response
                    sources = {}
            else:
                answer = response
                sources = {}

            # Only use the answer field for the embed description
            # Replace [#N] in the answer with clickable links using the sources map (if available)
            def replace_citation_with_link(match):
                num = match.group(1)
                if sources and num in sources:
                    meta = sources[num]
                    link = meta.get("link")
                    if link and link.startswith("https://discord.com/channels/"):
                        return f"[#{num}](<{link}>)"
                return f"[#{num}]"

            answer = re.sub(r'\[#(\d+)\]', replace_citation_with_link, answer)


            # Add spacing between consecutive citations (e.g., [#1][#2] -> [#1] [#2])
            answer = re.sub(r'(\]\[)', '] [', answer)

            # Replace user IDs or usernames in the answer with Discord mention links if possible
            # Build a user_id to mention mapping from sources
            user_id_to_mention = {}
            for src in sources.values():
                uid = src.get("user_id")
                if uid:
                    user_id_to_mention[uid] = f'<@{uid}>'

            # Optionally, build a username to mention mapping if usernames are present in excerpts
            # (This is less reliable, but can help if usernames are referenced directly)
            username_to_mention = {}
            for src in sources.values():
                excerpt = src.get("excerpt", "")
                uid = src.get("user_id")
                if uid and message.guild:
                    member = message.guild.get_member(int(uid))
                    if member:
                        username_to_mention[member.name] = f'<@{uid}>'
                        username_to_mention[member.display_name] = f'<@{uid}>'


            # Get bot user ID and mention
            bot_mention = None
            bot_user_id = None
            if message.guild:
                bot_member = message.guild.get_member(message.guild.me.id)
                if bot_member:
                    bot_mention = bot_member.mention
                    bot_user_id = str(bot_member.id)

            # Replace all occurrences of '@gronk' (case-insensitive, not already a mention) with the bot mention
            if bot_mention:
                answer = re.sub(r'(?<!<@)@?gronk(?!>)', bot_mention, answer, flags=re.IGNORECASE)

            # Replace user IDs with mentions, but skip the bot's user ID (already handled by @gronk logic)
            for uid, mention in user_id_to_mention.items():
                if bot_user_id and uid == bot_user_id:
                    continue  # skip bot user id
                answer = answer.replace(uid, mention)

            # Replace any username with a mention (avoid double-mentioning if already replaced)
            for uname, mention in username_to_mention.items():
                # Only replace if not already a mention and not 'gronk'
                if uname.lower() != 'gronk':
                    answer = re.sub(rf'(?<!<@){re.escape(uname)}(?!>)', mention, answer)

            # Remove redundant patterns: @gronk (user ID @botid) or @gronk (user ID botid)
            if bot_mention and bot_user_id:
                answer = re.sub(rf'{re.escape(bot_mention)} ?\(user ID ?<?@!?{bot_user_id}>?\)', bot_mention, answer)
                answer = re.sub(rf'{re.escape(bot_mention)} ?\(user ID ?{bot_user_id}\)', bot_mention, answer)


        # Convert any remaining Discord usernames to mentions (fallback)
        answer = convert_usernames_to_mentions(answer, message.guild)

        # Remove redundant user mention and user ID pairs, e.g., '@username (user ID @123)' or '@123 (which is @username)'
        # Remove patterns like: @username (user ID @username) or @userID (which is @username)
        answer = re.sub(r'(\<@!?\d+\>) ?\(user ID \1\)', r'\1', answer)
        answer = re.sub(r'(\<@!?\d+\>) ?\(which is \1\)', r'\1', answer)
        # Remove patterns like: @username (user ID @1234567890)
        answer = re.sub(r'(\<@!?\d+\>) ?\(user ID @\d+\)', r'\1', answer)
        # Remove patterns like: @1234567890 (which is @username)
        answer = re.sub(r'(@\d+) ?\(which is \<@!?\d+\>\)', r'\1', answer)

        # Calculate cost from SDK usage dict
        request_cost = 0
        usage_text = ""
        if usage:
            prompt_tokens = usage.get('prompt_tokens', 0)
            completion_tokens = usage.get('completion_tokens', 0)
            input_cost = (prompt_tokens / 1_000_000) * GROK_TEXT_INPUT_COST
            output_cost = (completion_tokens / 1_000_000) * GROK_TEXT_OUTPUT_COST
            request_cost = input_cost + output_cost
            usage_text = f"💵 ${request_cost:.6f} • {prompt_tokens} in / {completion_tokens} out"

        await searching_msg.delete()

        # Only show the answer (with inline citations), no separate sources or confidence
        title = "🔍 Discord History Analysis"
        if target_user:
            title += f": {target_user.display_name}"
        if len(answer) <= 4096:
            embed = discord.Embed(
                title=title,
                description=answer,
                color=discord.Color.purple(),
                timestamp=message.created_at
            )
            embed.set_author(
                name="Grok Analysis",
                icon_url="https://pbs.twimg.com/profile_images/1683899100922511378/5lY42eHs_400x400.jpg"
            )
            analyzed_text = f"{messages_to_analyze} messages analyzed"
            if len(collected_messages) > messages_to_analyze:
                analyzed_text += f" ({len(collected_messages)} found)"
            if messages_for_context:
                oldest_msg = messages_for_context[-1]
                oldest_date = oldest_msg.created_at.astimezone(TIMEZONE)
                analyzed_text += f" • Oldest: {oldest_date.strftime('%Y-%m-%d %H:%M %Z')}"
            # Removed the 'Analyzed' field for a cleaner embed
            footer_text = f"Requested by {message.author.display_name}"
            if usage_text:
                footer_text += f" • {usage_text}"
            embed.set_footer(text=footer_text, icon_url=message.author.avatar.url if message.author.avatar else None)
            await message.reply(embed=embed)
        else:
            # Split into multiple embeds
            chunks = []
            current_chunk = ""
            
            # Split by paragraphs to avoid breaking markdown links
            paragraphs = response.split('\n\n')
            
            for para in paragraphs:
                # Check if adding this paragraph would exceed limit
                if len(current_chunk) + len(para) + 2 > 4096:
                    if current_chunk:
                        chunks.append(current_chunk.rstrip())
                        current_chunk = ""
                    
                    # If paragraph itself is too long, split it
                    if len(para) > 4096:
                        # Split by sentences
                        sentences = para.split('. ')
                        for sentence in sentences:
                            sentence_with_period = sentence + '. ' if not sentence.endswith('.') else sentence + ' '
                            
                            if len(current_chunk) + len(sentence_with_period) > 4096:
                                if current_chunk:
                                    chunks.append(current_chunk.rstrip())
                                    current_chunk = ""
                                
                                # If single sentence is too long, force split
                                if len(sentence_with_period) > 4096:
                                    for i in range(0, len(sentence_with_period), 4096):
                                        chunks.append(sentence_with_period[i:i+4096])
                                else:
                                    current_chunk = sentence_with_period
                            else:
                                current_chunk += sentence_with_period
                    else:
                        current_chunk = para + '\n\n'
                else:
                    current_chunk += para + '\n\n'
            
            if current_chunk.strip():
                chunks.append(current_chunk.rstrip())
            
            # Validate all chunks are within limit
            validated_chunks = []
            for chunk in chunks:
                if len(chunk) > 4096:
                    logger.warning(f'Chunk exceeded 4096 chars ({len(chunk)}), force splitting...')
                    # Force split at 4096 boundaries
                    for i in range(0, len(chunk), 4096):
                        validated_chunks.append(chunk[i:i+4096])
                else:
                    validated_chunks.append(chunk)
            
            chunks = validated_chunks
            logger.info(f'Split response into {len(chunks)} embeds (validated)')
            
            for i, chunk in enumerate(chunks):
                embed = discord.Embed(
                    title=f"{title} (Part {i+1}/{len(chunks)})" if i > 0 else title,
                    description=chunk,
                    color=discord.Color.purple(),
                    timestamp=message.created_at
                )
                embed.set_author(
                    name="Grok Analysis",
                    icon_url="https://pbs.twimg.com/profile_images/1683899100922511378/5lY42eHs_400x400.jpg"
                )
                
                # Add fields and footer only to last embed
                if i == len(chunks) - 1:
                    analyzed_text = f"{messages_to_analyze} messages analyzed"
                    if len(collected_messages) > messages_to_analyze:
                        analyzed_text += f" ({len(collected_messages)} found)"
                    
                    # Add oldest message date
                    if messages_for_context:
                        oldest_msg = messages_for_context[-1]  # Last in list (reversed for chronological)
                        oldest_date = oldest_msg.created_at.astimezone(TIMEZONE)
                        analyzed_text += f"\nOldest: {oldest_date.strftime('%Y-%m-%d %H:%M %Z')}"
                    
                    # Removed the 'Analyzed' field for a cleaner embed
                    footer_text = f"Requested by {message.author.display_name}"
                    if usage_text:
                        footer_text += f" • {usage_text}"
                    embed.set_footer(text=footer_text, icon_url=message.author.avatar.url if message.author.avatar else None)
                
                await message.reply(embed=embed)
        
        logger.info('Discord history analysis completed')
            
    except Exception as e:
        logger.error(f'Error in Discord history search: {e}', exc_info=True)
        try:
            await searching_msg.edit(content=f"❌ Error analyzing messages: {str(e)}")
        except:
            await message.reply(f"❌ Error analyzing messages: {str(e)}")
