
import discord
from discord.ext import commands
from discord import ui, Interaction
import os
import logging
from dotenv import load_dotenv
from openai import OpenAI
import spacy
from spacy.matcher import Matcher
import re
from typing import Optional
from datetime import timezone, datetime, timedelta
import pytz
import sqlite3
import json
import aiohttp
import tempfile
# xAI SDK for all API interactions
from xai_sdk import AsyncClient as XAIAsyncClient
from xai_sdk.chat import user as xai_user, file as xai_file, system as xai_system, assistant as xai_assistant, text as xai_text, image as xai_image
from xai_sdk.tools import web_search as xai_web_search, x_search as xai_x_search, code_execution as xai_code_execution
from xai_sdk.search import SearchParameters

bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

async def generate_image(message, prompt: str):
    """
    Generate an image from a text prompt using Grok image generation API.
    Called via natural language detection (e.g., "generate an image of...")
    """
    try:
        XAI_KEY = os.getenv('XAI_API_KEY')
        GROK_IMAGE_MODEL = os.getenv('GROK_IMAGE_MODEL', 'grok-2-image-latest')
        GROK_IMAGE_OUTPUT_COST = float(os.getenv('GROK_IMAGE_OUTPUT_COST', '0.50'))  # $/image default, update as needed
        if not XAI_KEY:
            await message.reply("❌ XAI_API_KEY not set in environment.")
            return
        async with message.channel.typing():
            # Call Grok image generation API
            url = "https://api.x.ai/v1/images/generations"
            headers = {"Authorization": f"Bearer {XAI_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": GROK_IMAGE_MODEL,
                "prompt": prompt,
                "response_format": "url"
            }
            image_url = None
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # Per docs, always use data[0].url for the first image
                        if isinstance(data, dict) and 'data' in data and isinstance(data['data'], list) and data['data']:
                            image_url = data['data'][0].get('url')
                        else:
                            image_url = None
                        if not image_url:
                            await message.reply("❌ No image URL returned by Grok.")
                            return
                    else:
                        err = await resp.text()
                        await message.reply(f"❌ Grok image API error: {resp.status} {err}")
                        return
        # Pricing info (update as needed)
        usage_text = f"💵 ${GROK_IMAGE_OUTPUT_COST:.2f} (est.)"
        embed = discord.Embed(
            title="🖼️ Grok AI Generated Image",
            description=f'**Prompt:** {prompt}',
            color=discord.Color.purple(),
            timestamp=message.created_at
        )
        embed.set_image(url=image_url)
        embed.set_footer(text=f"Requested by {message.author.display_name} • {usage_text}", icon_url=message.author.avatar.url if message.author.avatar else None)

        class MoreVersionsView(ui.View):
            def __init__(self, prompt):
                super().__init__(timeout=120)
                self.prompt = prompt

            @ui.button(label="Generate More Versions", style=discord.ButtonStyle.primary, custom_id="more_versions")
            async def more_versions(self, interaction: Interaction, button: ui.Button):
                await interaction.response.defer(thinking=True)
                try:
                    XAI_KEY = os.getenv('XAI_API_KEY')
                    GROK_IMAGE_MODEL = os.getenv('GROK_IMAGE_MODEL', 'grok-2-image-latest')
                    url = "https://api.x.ai/v1/images/generations"
                    headers = {"Authorization": f"Bearer {XAI_KEY}", "Content-Type": "application/json"}
                    payload = {
                        "model": GROK_IMAGE_MODEL,
                        "prompt": self.prompt,
                        "response_format": "url",
                        "n": 4
                    }
                    async with aiohttp.ClientSession() as session:
                        async with session.post(url, headers=headers, json=payload) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                if isinstance(data, dict) and 'data' in data and isinstance(data['data'], list) and data['data']:
                                    image_urls = [img.get('url') for img in data['data'] if img.get('url')]
                                else:
                                    image_urls = []
                            else:
                                await interaction.followup.send(f"❌ Grok image API error: {resp.status}", ephemeral=True)
                                return
                    if not image_urls:
                        await interaction.followup.send("❌ No image URLs returned by Grok.", ephemeral=True)
                        return
                    # Show all 4 images as separate embeds in a single message (Discord best practice)
                    embeds = []
                    bot_url = "https://astrixbot.cf"  # Example URL, replace with your bot's site if desired
                    for idx, url in enumerate(image_urls):
                        if idx == 0:
                            embed = discord.Embed(
                                title="🖼️ Grok AI Generated Images (4 Versions)",
                                description=f'**Prompt:** {self.prompt}',
                                color=discord.Color.purple(),
                                timestamp=interaction.message.created_at if interaction.message else None
                            )
                            embed.set_image(url=url)
                            embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
                            embed.url = bot_url
                        else:
                            embed = discord.Embed()
                            embed.set_image(url=url)
                            embed.url = bot_url
                        embeds.append(embed)
                    await interaction.followup.send(embeds=embeds, ephemeral=False)
                except Exception as e:
                    await interaction.followup.send(f"❌ Error generating image: {e}", ephemeral=True)

        view = MoreVersionsView(prompt)
        await message.reply(embed=embed, view=view)
    except Exception as e:
        await message.reply(f"❌ Error generating image: {e}")

# Load spaCy model for lightweight NLP (entity/topic extraction only)
# Note: We use pattern-based intent detection instead of heavy ML models for performance
try:
    nlp_spacy = spacy.load('en_core_web_sm')
except OSError:
    import subprocess
    subprocess.run(['python', '-m', 'spacy', 'download', 'en_core_web_sm'])
    nlp_spacy = spacy.load('en_core_web_sm')

# Intent patterns for lightweight detection (no ML models needed)
INTENT_PATTERNS = {
    'image_generation': [
        r'\b(generate|create|make|draw|paint|sketch|render|illustrate|visualize)\b.*\b(image|picture|art|artwork|illustration|visual)\b',
        r'\b(image|picture|art|artwork|illustration)\b.*\b(of|for|with|showing)\b',
        r'\bshow me (an? )?(image|picture|art)\b',
        r'\b(grok|bot),?\s*(make|create|generate|draw)\b',
    ],
    'discord_history': [
        r'\b(who|what|how many)\b.*\b(talked|said|mentioned|posted|discussed)\b',
        r'\b(summarize|summary|overview)\b.*\b(chat|discord|server|channel|conversation)\b',
        r'\bin (this|the) (server|channel|discord|chat)\b',
        r'\b(we|our|us)\b.*\b(discuss|talk|mention|chat)\b',
    ],
    'general_query': [
        r'\b(what is|who is|how does|why does|when did|where is)\b',
        r'\b(explain|tell me about|describe)\b',
    ]
}

def detect_intent_pattern(text):
    """
    Lightweight pattern-based intent detection.
    Returns the detected intent or None.
    """
    text_lower = text.lower()
    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return intent
    return None

def advanced_nlp_parse(text):
    """
    Lightweight NLP using spaCy for entity/topic extraction and regex for intent.
    Returns dict with entities, topics, and intent.
    Memory-efficient: No heavy ML models loaded.
    """
    doc = nlp_spacy(text)
    entities = [(ent.text, ent.label_) for ent in doc.ents]
    # Extract noun chunks as potential topics
    topics = [chunk.text for chunk in doc.noun_chunks]
    # Use lightweight pattern-based intent detection
    intent = detect_intent_pattern(text)
    
    return {
        'entities': entities,
        'topics': topics,
        'intent': intent
    }
import json
import aiohttp
import tempfile

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('GrokBot')

# Load environment variables from .env file (looks in current directory)
# In Docker, this will be /app/.env
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    logger.info(f'Loading environment from {dotenv_path}')
    load_dotenv(dotenv_path)
else:
    logger.info('.env file not found, using environment variables')
    load_dotenv()  # Fallback to default behavior

TOKEN = os.getenv('DISCORD_TOKEN')
XAI_KEY = os.getenv('XAI_API_KEY')

# Log if tokens are loaded (without revealing the actual values)
if TOKEN:
    logger.info(f'DISCORD_TOKEN loaded (length: {len(TOKEN)})')
else:
    logger.error('DISCORD_TOKEN not found in environment!')
    
if XAI_KEY:
    logger.info(f'XAI_API_KEY loaded (length: {len(XAI_KEY)})')
else:
    logger.error('XAI_API_KEY not found in environment!')

# Timezone for display (configurable, defaults to Central Time)
TIMEZONE = pytz.timezone(os.getenv('TIMEZONE', 'America/Chicago'))

# Model configuration (with defaults)
GROK_TEXT_MODEL = os.getenv('GROK_TEXT_MODEL', 'grok-4-fast')
GROK_VISION_MODEL = os.getenv('GROK_VISION_MODEL', 'grok-2-vision-1212')
GROK_DOCUMENT_MODEL = os.getenv('GROK_DOCUMENT_MODEL', 'grok-4-fast')  # Must be agentic-capable for document search

# Search configuration (with defaults)
ENABLE_WEB_SEARCH = os.getenv('ENABLE_WEB_SEARCH', 'true').lower() == 'true'
ENABLE_X_SEARCH = os.getenv('ENABLE_X_SEARCH', 'false').lower() == 'true'  # X/Twitter search (disabled by default)
ENABLE_CODE_EXECUTION = os.getenv('ENABLE_CODE_EXECUTION', 'false').lower() == 'true'  # Code execution tool (disabled by default)
MAX_SEARCH_RESULTS = int(os.getenv('MAX_SEARCH_RESULTS', '3'))
MAX_KEYWORD_SCAN = int(os.getenv('MAX_KEYWORD_SCAN', '10000'))
ENABLE_NL_HISTORY_SEARCH = os.getenv('ENABLE_NL_HISTORY_SEARCH', 'true').lower() == 'true'
MAX_MESSAGES_ANALYZED = int(os.getenv('MAX_MESSAGES_ANALYZED', '500'))  # Max messages sent to Grok for analysis
DEFAULT_SEARCH_LIMIT = int(os.getenv('DEFAULT_SEARCH_LIMIT', '5000'))  # Default messages to scan when no limit specified

# Pricing configuration (with defaults based on current xAI pricing)
GROK_TEXT_INPUT_COST = float(os.getenv('GROK_TEXT_INPUT_COST', '0.20'))
GROK_TEXT_OUTPUT_COST = float(os.getenv('GROK_TEXT_OUTPUT_COST', '0.50'))
GROK_TEXT_CACHED_COST = float(os.getenv('GROK_TEXT_CACHED_COST', '0.05'))
GROK_VISION_INPUT_COST = float(os.getenv('GROK_VISION_INPUT_COST', '2.00'))
GROK_VISION_OUTPUT_COST = float(os.getenv('GROK_VISION_OUTPUT_COST', '10.00'))
# Tool pricing (per 1,000 invocations) - new model as of 2025
GROK_TOOL_COST = float(os.getenv('GROK_TOOL_COST', '5.00'))  # $5/1000 calls for web_search, x_search, code_execution

# OpenAI-compatible client (still used for some operations like vision)
client = OpenAI(api_key=XAI_KEY, base_url="https://api.x.ai/v1")

# Global xAI SDK async client (initialized lazily)
_xai_client = None

def get_xai_client():
    """Get or create the global xAI async client."""
    global _xai_client
    if _xai_client is None:
        _xai_client = XAIAsyncClient()
    return _xai_client

def build_sdk_tools():
    """Build list of tools for SDK chat based on configuration."""
    tools = []
    if ENABLE_WEB_SEARCH:
        tools.append(xai_web_search())
    if ENABLE_X_SEARCH:
        tools.append(xai_x_search())
    if ENABLE_CODE_EXECUTION:
        tools.append(xai_code_execution())
    return tools if tools else None

async def sdk_chat_request(model: str, system_prompt: str, user_prompt: str, 
                           conversation_history: list = None, include_search: bool = True,
                           max_search_results: int = None,
                           previous_response_id: str = None) -> tuple:
    """
    Make a chat request using the xAI SDK Chat Responses API.
    
    Args:
        model: The model to use
        system_prompt: System prompt for the conversation
        user_prompt: The user's message
        conversation_history: Optional list of previous messages (used if no previous_response_id)
        include_search: Whether to enable search tools
        max_search_results: Maximum number of search results
        previous_response_id: xAI response ID to continue a conversation (uses server-side history)
    
    Returns: (response_content: str, usage_dict: dict, citations: list, response_id: str)
    """
    xai_client = get_xai_client()
    
    # Build tools
    tools = build_sdk_tools() if include_search else None
    
    # Build search parameters
    search_params = None
    if include_search and ENABLE_WEB_SEARCH:
        search_params = SearchParameters(
            mode="auto",
            max_search_results=max_search_results or MAX_SEARCH_RESULTS,
            return_citations=True
        )
    
    # Create chat - use previous_response_id if available for conversation chaining
    if previous_response_id:
        # Continue from previous conversation (xAI stores the history)
        logger.info(f'Continuing conversation from xAI response ID: {previous_response_id}')
        chat = xai_client.chat.create(
            model=model,
            previous_response_id=previous_response_id,
            store_messages=True,
            tools=tools,
            search_parameters=search_params,
            include=["inline_citations"]  # Get citations embedded in response text
        )
    else:
        # New conversation - build messages from scratch
        messages = [xai_system(system_prompt)]
        
        # Add conversation history if provided (fallback when no response ID)
        if conversation_history:
            for msg in conversation_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    messages.append(xai_user(content))
                elif role == "assistant":
                    messages.append(xai_assistant(content))
        
        chat = xai_client.chat.create(
            model=model,
            messages=messages,
            store_messages=True,
            tools=tools,
            search_parameters=search_params,
            include=["inline_citations"]  # Get citations embedded in response text
        )
    
    # Add user message
    chat.append(xai_user(user_prompt))
    
    # Get response
    response = await chat.sample()
    
    # Extract data
    content = response.content if response else ""
    citations = response.citations if response and hasattr(response, 'citations') else []
    response_id = response.id if response and hasattr(response, 'id') else None
    
    # Note: With inline_citations enabled, URLs are already properly formatted as [[N]](url)
    # Skip URL post-processing to avoid double-wrapping like [[1]]([post](url))
    
    # Debug: log citation info
    if citations:
        logger.info(f'Got {len(citations)} citations (sources examined)')
    
    # Log actual tool invocations (this is what costs $5/1000)
    if response and hasattr(response, 'tool_calls') and response.tool_calls:
        logger.info(f'Tool invocations: {len(response.tool_calls)} calls')
        for tc in response.tool_calls:
            if hasattr(tc, 'function'):
                logger.info(f'  - {tc.function.name}')
    if response and hasattr(response, 'server_side_tool_usage') and response.server_side_tool_usage:
        logger.info(f'Server-side tool usage: {response.server_side_tool_usage}')
    
    if response_id:
        logger.info(f'Got xAI response ID: {response_id}')
    
    # Build usage dict
    usage = {}
    tool_invocations = 0
    
    # Count tool invocations from response.tool_calls (the actual calls made)
    if response and hasattr(response, 'tool_calls') and response.tool_calls:
        tool_invocations = len(response.tool_calls)
    
    if response and hasattr(response, 'usage') and response.usage:
        usage = {
            'prompt_tokens': getattr(response.usage, 'prompt_tokens', 0) or (response.usage.total_tokens // 2),
            'completion_tokens': getattr(response.usage, 'completion_tokens', 0) or (response.usage.total_tokens // 2),
            'total_tokens': response.usage.total_tokens if hasattr(response.usage, 'total_tokens') else 0,
            'tool_invocations': tool_invocations,
            'num_citations': len(citations) if citations else 0
        }
    
    return content, usage, citations, response_id

search_context = {}  # {channel_id: {user_id: {searched_user: User, messages: [...], query: str}}}

# SQLite database for conversation history
DB_PATH = os.getenv('CONVERSATION_DB_PATH', 'data/conversation_history.db')
CONVERSATION_RETENTION_HOURS = int(os.getenv('CONVERSATION_RETENTION_HOURS', '24'))


# --- Only start the bot if running as main script ---
# Place at the very end of the file to ensure all functions are defined

def init_conversation_db():
    """Initialize SQLite database for conversation history"""
    # Ensure data directory exists
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)
        logger.info(f'Created database directory: {db_dir}')
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create conversations table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            message_id INTEGER PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            user_query TEXT NOT NULL,
            bot_response TEXT NOT NULL,
            model_used TEXT NOT NULL,
            xai_response_id TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    ''')
    
    # Add xai_response_id column if it doesn't exist (for existing databases)
    try:
        cursor.execute('ALTER TABLE conversations ADD COLUMN xai_response_id TEXT')
        logger.info('Added xai_response_id column to conversations table')
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # Create index for faster lookups
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_message_id ON conversations(message_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_created_at ON conversations(created_at)
    ''')
    
    conn.commit()
    conn.close()
    logger.info(f'Conversation database initialized at {DB_PATH}')

def store_conversation(message_id: int, channel_id: int, author_id: int, 
                       user_query: str, bot_response: str, model_used: str,
                       xai_response_id: str = None):
    """Store conversation in SQLite database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        cursor.execute('''
            INSERT OR REPLACE INTO conversations 
            (message_id, channel_id, author_id, user_query, bot_response, model_used, xai_response_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (message_id, channel_id, author_id, user_query, bot_response, model_used, xai_response_id, now_iso))
        
        conn.commit()
        conn.close()
        logger.debug(f'Stored conversation for message {message_id}' + (f' with xAI response ID {xai_response_id}' if xai_response_id else ''))
    except Exception as e:
        logger.error(f'Error storing conversation: {e}')

def get_conversation(message_id: int) -> Optional[dict]:
    """Retrieve conversation from SQLite database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT author_id, user_query, bot_response, model_used, created_at, xai_response_id
            FROM conversations
            WHERE message_id = ?
        ''', (message_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'author_id': row[0],
                'user_query': row[1],
                'bot_response': row[2],
                'model_used': row[3],
                'created_at': row[4],
                'xai_response_id': row[5]
            }
        return None
    except Exception as e:
        logger.error(f'Error retrieving conversation: {e}')
        return None

def cleanup_old_conversations():
    """Remove conversations older than CONVERSATION_RETENTION_HOURS"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cutoff_time = (datetime.now(timezone.utc) - timedelta(hours=CONVERSATION_RETENTION_HOURS)).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        cursor.execute('''
            DELETE FROM conversations
            WHERE created_at < ?
        ''', (cutoff_time,))
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        if deleted_count > 0:
            logger.info(f'Cleaned up {deleted_count} old conversations (older than {CONVERSATION_RETENTION_HOURS}h)')
    except Exception as e:
        logger.error(f'Error cleaning up conversations: {e}')

async def periodic_cleanup():
    """Periodically clean up old conversations"""
    import asyncio
    while True:
        await asyncio.sleep(6 * 3600)  # Sleep for 6 hours
        cleanup_old_conversations()

# Initialize database on startup
init_conversation_db()

def convert_usernames_to_mentions(text: str, guild: discord.Guild) -> str:
    """
    Convert Discord usernames in text to proper mentions.
    Handles patterns like: username, @username, "username"
    """
    if not guild:
        return text
    
    # Get all members in the guild
    members = guild.members
    
    # Create a mapping of lowercase usernames/display names to member objects
    username_map = {}
    for member in members:
        # Map both username and display name (case-insensitive)
        username_map[member.name.lower()] = member
        username_map[member.display_name.lower()] = member
        # Also map without discriminator if present
        if '#' in member.name:
            base_name = member.name.split('#')[0].lower()
            username_map[base_name] = member
    
    # Pattern to match potential usernames
    # Matches: @username, "username", username (with word boundaries)
    # But avoid matching if already in a mention format <@123456>
    patterns_to_try = [
        # Match @username (but not already formatted mentions)
        (r'(?<!<)@([a-zA-Z0-9_]{2,32})(?!>)', lambda m: f"<@{username_map[m.group(1).lower()].id}>" if m.group(1).lower() in username_map else m.group(0)),
        # Match "username" in quotes
        (r'"([a-zA-Z0-9_]{2,32})"', lambda m: f"<@{username_map[m.group(1).lower()].id}>" if m.group(1).lower() in username_map else m.group(0)),
        # Match username at word boundaries (but be conservative - only at start of sentence or after punctuation)
        (r'(?<=\s)([A-Z][a-zA-Z0-9_]{1,31})(?=[\s,.\'])', lambda m: f"<@{username_map[m.group(1).lower()].id}>" if m.group(1).lower() in username_map else m.group(0)),
    ]
    
    result = text
    for pattern, replacement in patterns_to_try:
        try:
            result = re.sub(pattern, replacement, result)
        except Exception as e:
            logger.warning(f'Error applying username pattern {pattern}: {e}')
            continue
    
    return result

@bot.event
async def on_ready():
    logger.info(f'Bot logged in as {bot.user} (ID: {bot.user.id})')
    logger.info(f'Connected to {len(bot.guilds)} server(s)')
    
    # Clean up old conversations on startup
    cleanup_old_conversations()
    
    # Schedule periodic cleanup (every 6 hours)
    bot.loop.create_task(periodic_cleanup())

async def should_search_discord_history(message_content, has_mentions):
    """
    Determine if the user query is asking to search Discord history.
    
    Returns:
        tuple: (should_search: bool, time_limit: Optional[int], target_keywords: Optional[str])
    """
    content_lower = message_content.lower()
    

    # 0. BOT STATUS CHECKS - If the query is just a ping or status check, do NOT trigger Discord search
    bot_ping_phrases = [
        "are you there", "are you working", "are you online", "are you up", "are you alive", "yo", "ping", "test", "hello", "hi", "hey", "you here", "up?", "working?", "online?", "alive?", "present?", "awake?"
    ]
    if has_mentions and any(phrase in content_lower for phrase in bot_ping_phrases):
        logger.info('Bot ping/status check detected, not a Discord search')
        return False, None, None

    # 1. STRONGEST SIGNALS - Instant match (no API call needed)
    if has_mentions:
        logger.info('Discord search detected: user mention found')
        # Extract time period if present
        time_limit = extract_time_period(content_lower)
        # Extract keywords, but only use for filtering if they are meaningful
        keywords = extract_keywords(content_lower)
        # Define a set of non-meaningful keywords (stopwords, pronouns, etc.)
        non_meaningful = {"we", "us", "our", "discord", "chat", "talking", "about", "in", "the", "what", "are", "is", "on", "this", "server", "channel"}
        if not keywords or keywords.lower() in non_meaningful:
            keywords = None  # Don't use for filtering
        return True, time_limit, keywords
    
    # Check for explicit Discord scope indicators, but avoid false positives for pings/status checks
    discord_scope_keywords = [
        "in here", "this channel", "this server", 
        "on this server", "in this chat", "in chat",
        "this discord", "on this discord", "in this discord", "in the discord", "in discord",
        "of this discord", "of this server", "of this channel",
        "the discord", "the server", "the channel"
    ]
    # Only match 'here' as a scope keyword if not part of a ping/status check
    ping_phrases_with_here = [
        "you here", "are you here", "yo here", "here?", "here .", "here!", "here "
    ]
    is_ping_with_here = any(phrase in content_lower for phrase in ping_phrases_with_here)
    if any(scope in content_lower for scope in discord_scope_keywords) or ("here" in content_lower and not is_ping_with_here):
        logger.info('Discord search detected: explicit scope keyword')
        time_limit = extract_time_period(content_lower)
        keywords = extract_keywords(content_lower)
        return True, time_limit, keywords
    
    # Check for Discord-specific pronouns (we/us/our)
    discord_pronouns = [" we ", " us ", " our "]
    has_discord_pronoun = any(pronoun in " " + content_lower + " " for pronoun in discord_pronouns)
    
    # 2. OBVIOUS GENERAL QUERIES - Skip API call
    general_indicators = [
        "in history", "in the world", "on twitter", "on x.com",
        "in the news", "globally", "worldwide", "scientists say",
        "researchers found", "studies show", "according to",
        "what is", "what are", "what was", "what were",
        "how does", "how do", "how did", "how can", "how much", "how many", "how high", "how low", "how far",
        "why does", "why do", "why did", "why is", "why are",
        "where is", "where are", "where does", "where do",
        "when is", "when are", "when does", "when do", "when did"
    ]
    if any(indicator in content_lower for indicator in general_indicators):
        logger.info('General query detected: general indicator found')
        return False, None, None
    
    # 3. PATTERN DETECTION for ambiguous cases
    # Check for temporal patterns
    time_patterns = [
        r'(past|last|over the|in the|during the)\s*(month|week|day|year|30 days)',
        r'recently',
        r'this\s*(week|month|year)',
    ]
    has_temporal = any(re.search(pattern, content_lower) for pattern in time_patterns)
    
    # Check for analysis patterns
    analysis_patterns = [
        r'who\s+(talks?|mentions?|discusses?|posts?|says?|chats?)',
        r'what\s+(have|has|did|do)\s+(we|users?|people)',
        r'(summarize|summary|overview)',
        r'(most|least|top|bottom)\s+',
        r'how (often|many|much)',
        r'rank\s+(members?|users?|people)',  # Added rank pattern
    ]
    has_analysis = any(re.search(pattern, content_lower) for pattern in analysis_patterns)
    
    # Score-based decision for ambiguous cases
    discord_score = 0
    
    if has_discord_pronoun:
        discord_score += 2
        logger.debug('Discord pronoun detected (+2)')
    
    if has_temporal and has_analysis:
        discord_score += 2
        logger.debug('Temporal + analysis pattern detected (+2)')
    
    # Check for activity verbs (Discord-specific actions)
    activity_verbs = ["posted", "sent", "messaged", "said here", "mentioned in", "talked in"]
    if any(verb in content_lower for verb in activity_verbs):
        discord_score += 1
        logger.debug('Discord activity verb detected (+1)')
    
    # Decision based on score
    if discord_score >= 3:
        logger.info(f'Discord search detected: score {discord_score} >= 3')
        time_limit = extract_time_period(content_lower)
        keywords = extract_keywords(content_lower)
        return True, time_limit, keywords
    elif discord_score >= 1:
        # Ambiguous case - use Grok to classify
        logger.info(f'Ambiguous query (score {discord_score}), using Grok classification...')
        try:
            is_discord = await classify_with_grok(message_content)
            if is_discord:
                time_limit = extract_time_period(content_lower)
                keywords = extract_keywords(content_lower)
                return True, time_limit, keywords
            else:
                return False, None, None
        except Exception as e:
            logger.warning(f'Grok classification failed: {e}, defaulting to general query')
            return False, None, None
    else:
        logger.info(f'General query detected: score {discord_score} < 1')
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
    nlp_results = advanced_nlp_parse(content_lower)
    # Prefer named entities and noun chunks as keywords
    keywords = []
    if nlp_results['entities']:
        keywords.extend([ent[0] for ent in nlp_results['entities']])
    if nlp_results['topics']:
        keywords.extend(nlp_results['topics'])
    # Remove duplicates, preserve order
    seen = set()
    keywords = [x for x in keywords if not (x in seen or seen.add(x))]
    # Log extracted info
    logger.info(f"NLP Extracted entities: {nlp_results['entities']}, topics: {nlp_results['topics']}, intent: {nlp_results['intent']}")
    # Return the most relevant keyword or a comma-separated string
    if keywords:
        return ', '.join(keywords)
    return None

async def classify_with_grok(message_content):
    """Use Grok to classify if query is about Discord or general knowledge"""
    classification_prompt = f"""You are analyzing a Discord bot query. Determine if the user is asking about:

A) DISCORD: The Discord server's chat history, messages, or users in THIS server
B) GENERAL: General knowledge, news, history, or topics outside this Discord server

Examples of DISCORD queries:
- "who talks about Python the most?"
- "what have we discussed about AI recently?"
- "summarize our conversations from last week"
- "who mentions crypto the most?"
- "what are the main topics discussed here?"

Examples of GENERAL queries:
- "who was the smartest person in history?"
- "what have scientists discussed about climate change?"
- "summarize news from last week"
- "what did Elon Musk say recently?"
- "who is the best programmer in the world?"

User query: "{message_content}"

Respond with ONLY one word: "DISCORD" or "GENERAL"
"""
    
    try:
        # Use SDK for quick classification (no search needed)
        response, usage, _, _ = await sdk_chat_request(
            model=GROK_TEXT_MODEL,
            system_prompt="You are a query classifier. Respond with exactly one word.",
            user_prompt=classification_prompt,
            include_search=False
        )
        
        result = response.strip().upper()
        logger.info(f'Grok classification result: {result}')
        
        return "DISCORD" in result
    except Exception as e:
        logger.error(f'Error in Grok classification: {e}')
        return False

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
                include_search=False  # Don't web search for Discord history
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

@bot.event
async def on_message(message):

    if message.author == bot.user:
        return

    # Initialize variables to avoid NameError
    image_urls = []
    unsupported_images = []
    document_attachments = []
    unsupported_docs = []
    use_conversation_history = False
    conversation_messages = []

    # Helper: check if image URL/filename is supported
    def is_supported_image(url_or_filename):
        url = url_or_filename.lower()
        return url.endswith('.jpg') or url.endswith('.jpeg') or url.endswith('.png') or url.endswith('.webp')

    # Helper: check if document filename is supported (per xAI docs)
    def is_supported_document(filename):
        filename = filename.lower()
        supported_extensions = ('.pdf', '.txt', '.md', '.csv', '.json', '.py', '.js', '.java', '.c', '.cpp', '.h', '.ts', '.go', '.rs', '.rb', '.php')
        return filename.endswith(supported_extensions)

    # Check if bot is mentioned OR if user is replying to bot's message
    is_bot_mentioned = bot.user in message.mentions
    is_replying_to_bot = False
    previous_xai_response_id = None  # For xAI Chat Responses API continuation
    current_xai_response_id = None  # Will be set after SDK response for storage

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

    if is_bot_mentioned or is_replying_to_bot:
        if is_replying_to_bot:
            logger.info(f'Bot reply detected from {message.author} in #{message.channel}')
        else:
            logger.info(f'Bot mentioned by {message.author} in #{message.channel}')

        # Normalize prompt: remove all bot mentions and extra whitespace
        import re
        prompt = message.content
        prompt = re.sub(r'<@!?'+str(bot.user.id)+r'>', '', prompt)
        prompt = prompt.strip()
        logger.info(f'Normalized prompt for intent detection: "{prompt}"')

        # Check if this is a Discord history analysis query (if feature enabled)
        # Skip this check if we're replying to a bot message with stored conversation context
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
                return  # Don't process as normal query
        elif previous_xai_response_id:
            logger.info(f'Skipping Discord history search check - using stored conversation context (xAI response ID: {previous_xai_response_id})')
        
        # Check if this is a follow-up to a previous conversation
        is_search_followup = False
        conversation_context = []
        

        if is_bot_mentioned or is_replying_to_bot:
            if is_replying_to_bot:
                logger.info(f'Bot reply detected from {message.author} in #{message.channel}')
            else:
                logger.info(f'Bot mentioned by {message.author} in #{message.channel}')

            # Normalize prompt: remove all bot mentions and extra whitespace
            prompt = message.content
            prompt = re.sub(r'<@!?'+str(bot.user.id)+r'>', '', prompt)
            prompt = prompt.strip()
            logger.info(f'Normalized prompt for intent detection: "{prompt}"')

            # --- IMAGE REVISION DETECTION ---
            # If replying to a bot-generated image, treat as a revision request
            if is_replying_to_bot and message.reference:
                try:
                    replied_msg = await message.channel.fetch_message(message.reference.message_id)
                    # Check if the replied message has an image embed with our format
                    if replied_msg.embeds:
                        for embed in replied_msg.embeds:
                            if embed.title and "Grok AI Generated Image" in embed.title and embed.description:
                                # Extract the original prompt from the embed description
                                original_prompt_match = re.search(r'\*\*Prompt:\*\*\s*(.+)', embed.description)
                                if original_prompt_match:
                                    original_prompt = original_prompt_match.group(1).strip()
                                    logger.info(f'Detected image revision request. Original prompt: "{original_prompt}"')
                                    logger.info(f'Revision request: "{prompt}"')
                                    # Combine original prompt with revision instructions
                                    revised_prompt = f"{original_prompt}. Revision: {prompt}"
                                    logger.info(f'Combined revised prompt: "{revised_prompt}"')
                                    await generate_image(message, revised_prompt)
                                    return
                except Exception as e:
                    logger.warning(f'Error checking for image revision: {e}')

            # --- IMAGE GENERATION NATURAL LANGUAGE DETECTION ---
            # Use lightweight pattern-based intent detection
            nlp_result = advanced_nlp_parse(prompt)
            is_image_request = nlp_result.get('intent') == 'image_generation'
            # If detected, call image generation directly
            if is_image_request:
                logger.info('Detected image generation intent in natural language')
                await generate_image(message, prompt)
                return

            # --- END IMAGE GENERATION DETECTION ---

            # Existing natural language Discord history detection and follow-up logic...
            # ...existing code...
            for attachment in message.attachments:
                if is_supported_image(attachment.url) or (attachment.content_type and attachment.content_type in ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']):
                    image_urls.append(attachment.url)
                    logger.info(f'Found image attachment: {attachment.filename}')
                elif is_supported_document(attachment.filename):
                    document_attachments.append(attachment)
                    logger.info(f'Found document attachment: {attachment.filename}')
                else:
                    if not attachment.content_type or not attachment.content_type.startswith('image/'):
                        unsupported_docs.append(attachment.filename)
                        logger.warning(f'Unsupported document type: {attachment.filename} ({attachment.content_type})')
                    else:
                        unsupported_images.append(attachment.filename)
                        logger.warning(f'Unsupported image type: {attachment.filename} ({attachment.content_type})')

            # Check for image URLs in message content (links to images)
            image_url_pattern = r'https?://(?:[a-zA-Z0-9\-]+\.)+[a-zA-Z]{2,}(?:/[^\s]*)?\.(?:jpg|jpeg|png|webp)(?:\?[^\s]*)?'
            found_urls = re.findall(image_url_pattern, message.content, re.IGNORECASE)
            for url in found_urls:
                if url not in image_urls:
                    image_urls.append(url)
                    logger.info(f'Found image URL in message: {url}')
        
        # Check for Discord CDN embeds (when links auto-embed like Tenor, Giphy, etc.)
        for embed in message.embeds:
            # For gif/video embeds (Tenor, Giphy), prefer video/image in this order
            if embed.type in ['gifv', 'video', 'image', 'rich']:
                # Try to get the actual media URL
                media_url = None
                
                if embed.image and embed.image.url:
                    media_url = embed.image.url
                elif embed.video and embed.video.url:
                    media_url = embed.video.url
                elif embed.thumbnail and embed.thumbnail.url:
                    media_url = embed.thumbnail.url
                elif embed.url:
                    media_url = embed.url
                
                if media_url and media_url not in image_urls:
                    # Only add if it's a supported format
                    if is_supported_image(media_url):
                        image_urls.append(media_url)
                        logger.info(f'Found media in embed ({embed.type}): {media_url}')
                    else:
                        logger.warning(f'Skipping unsupported media format: {media_url}')
        
        # If replying to another message, get full context (unless using conversation history OR we have server-side context)
        if message.reference and not use_conversation_history and not previous_xai_response_id:
            logger.info('Message is a reply, fetching conversation context...')
            try:
                # First, traverse the reply chain
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
                    except:
                        break
                
                logger.info(f'Found {len(reply_chain)} messages in reply chain')
                
                # Now get surrounding messages for additional context
                # Only include messages within 2 minutes of each other to stay relevant
                context_messages = []
                time_window_seconds = 120  # 2 minutes
                
                if reply_chain:
                    oldest_msg = reply_chain[0]
                    
                    # Get messages before the oldest message, but only if they're recent
                    try:
                        before_messages = []
                        async for msg in message.channel.history(limit=10, before=oldest_msg.created_at):
                            if msg.id != oldest_msg.id and not msg.author.bot:
                                # Check time difference
                                time_diff = (oldest_msg.created_at - msg.created_at).total_seconds()
                                if time_diff <= time_window_seconds:
                                    before_messages.append(msg)
                                else:
                                    # Stop when we hit a message too old
                                    break
                        before_messages.reverse()  # Chronological order
                        context_messages.extend(before_messages)
                        logger.info(f'Found {len(before_messages)} recent messages before reply chain (within 2 min)')
                    except:
                        pass
                    
                    # Add the reply chain
                    context_messages.extend(reply_chain)
                    
                    # Get messages after the last message in chain (if not the current message)
                    try:
                        newest_msg = reply_chain[-1]
                        after_messages = []
                        async for msg in message.channel.history(limit=10, after=newest_msg.created_at, oldest_first=True):
                            if msg.id != newest_msg.id and msg.id != message.id and not msg.author.bot:
                                # Check time difference
                                time_diff = (msg.created_at - newest_msg.created_at).total_seconds()
                                if time_diff <= time_window_seconds:
                                    after_messages.append(msg)
                                else:
                                    # Stop when we hit a message too far in the future
                                    break
                        context_messages.extend(after_messages)
                        logger.info(f'Found {len(after_messages)} messages after reply chain (within 2 min)')
                    except:
                        pass
                
                # Collect images from all context messages
                for msg in context_messages:
                    # Collect images from attachments
                    for attachment in msg.attachments:
                        if attachment.content_type and attachment.content_type.startswith('image/'):
                            if attachment.url not in image_urls:
                                if is_supported_image(attachment.url) or attachment.content_type in ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']:
                                    image_urls.append(attachment.url)
                                    logger.info(f'Found image in context: {attachment.filename}')
                                else:
                                    logger.warning(f'Skipping unsupported image in context: {attachment.filename}')
                    
                    # Collect image URLs from message content
                    found_urls = re.findall(image_url_pattern, msg.content, re.IGNORECASE)
                    for url in found_urls:
                        if url not in image_urls:
                            image_urls.append(url)
                            logger.info(f'Found image URL in context: {url}')
                    
                    # Collect images from embeds
                    for embed in msg.embeds:
                        if embed.type in ['gifv', 'video', 'image', 'rich']:
                            media_url = None
                            
                            if embed.image and embed.image.url:
                                media_url = embed.image.url
                            elif embed.video and embed.video.url:
                                media_url = embed.video.url
                            elif embed.thumbnail and embed.thumbnail.url:
                                media_url = embed.thumbnail.url
                            elif embed.url:
                                media_url = embed.url
                            
                            if media_url and media_url not in image_urls:
                                if is_supported_image(media_url):
                                    image_urls.append(media_url)
                                    logger.info(f'Found media in context embed ({embed.type}): {media_url}')
                                else:
                                    logger.warning(f'Skipping unsupported media in context: {media_url}')
                
                # Build context from all messages
                if context_messages:
                    context_parts = ["Here is the conversation context:\n"]
                    for i, msg in enumerate(context_messages, 1):
                        # Truncate very long messages to avoid token limits
                        content = msg.content[:500] + "..." if len(msg.content) > 500 else msg.content
                        context_parts.append(f"[{i}] {msg.author.name}: {content}")
                    context_parts.append(f"\nUser's question: {prompt}")
                    prompt = "\n".join(context_parts)
                    logger.info(f'Built context with {len(context_messages)} total messages')
                
            except Exception as e:
                logger.warning(f'Could not fetch conversation context: {e}')
        elif message.reference and previous_xai_response_id:
            logger.info(f'Skipping context fetch - using xAI server-side conversation history (response ID: {previous_xai_response_id})')
        
        if not prompt and not image_urls and not document_attachments:
            logger.warning('No prompt, images, or documents found')
            await message.reply("Please provide a question, image, or document after mentioning me.")
            return
        
        # Notify user about unsupported images if any
        if unsupported_images and not image_urls:
            await message.reply(f"⚠️ Found unsupported image format(s): {', '.join(unsupported_images)}\n\nGrok only supports: JPEG, PNG, and WebP images.")
            return
        elif unsupported_images:
            logger.info(f'Proceeding with {len(image_urls)} supported images, ignoring {len(unsupported_images)} unsupported')
        
        # Query Grok
        try:
            usage_text = ""
            async with message.channel.typing():
                # Upload document files to Grok if present using xAI SDK
                grok_file_ids = []
                failed_uploads = []
                xai_client = None
                if document_attachments:
                    xai_client = XAIAsyncClient()
                    for attachment in document_attachments:
                        tmp_path = None
                        try:
                            # Use delete=False for Windows compatibility
                            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(attachment.filename)[1]) as tmp:
                                tmp_path = tmp.name
                                await attachment.save(tmp_path)
                            
                            # Upload using xAI SDK
                            uploaded_file = await xai_client.files.upload(tmp_path)
                            grok_file_ids.append(uploaded_file.id)
                            logger.info(f'Uploaded {attachment.filename} to Grok via SDK, file_id={uploaded_file.id}')
                        except Exception as upload_error:
                            logger.error(f'Error uploading {attachment.filename}: {upload_error}')
                            failed_uploads.append(attachment.filename)
                        finally:
                            # Clean up temp file
                            if tmp_path and os.path.exists(tmp_path):
                                try:
                                    os.unlink(tmp_path)
                                except:
                                    pass
                    
                    # Notify user if some uploads failed
                    if failed_uploads and not grok_file_ids:
                        await message.reply(f"❌ Failed to upload document(s): {', '.join(failed_uploads)}\n\nSupported formats: PDF, TXT, MD, CSV, JSON, and code files.")
                        return
                    elif failed_uploads:
                        logger.warning(f'Some documents failed to upload: {failed_uploads}, proceeding with {len(grok_file_ids)} successful uploads')

                # Determine model based on content type
                # Document analysis requires agentic-capable models (grok-4-fast, grok-4)
                if image_urls:
                    model = GROK_VISION_MODEL
                elif grok_file_ids:
                    model = GROK_DOCUMENT_MODEL  # Use agentic model for document search
                else:
                    model = GROK_TEXT_MODEL
                logger.info(f'Using model: {model} (images: {len(image_urls)}, docs: {len(grok_file_ids)})')

                # JSON instructions for OpenAI client paths (vision, documents)
                json_instructions = (
                    "You must ALWAYS reply in the following strict JSON format, with no extra commentary or markdown. "
                    "Format: {\"answer\": string, \"sources\": [string], \"confidence\": float}. "
                    "If you cite Discord messages, include a 'sources' array with each source as a string. "
                    "If you don't know, use an empty array for sources and 0.0 for confidence."
                )

                # System prompt for OpenAI client (vision/documents) - requires JSON
                openai_system_prompt = (
                    "You are Grok, a witty and uncensored AI assistant. Be direct, honest, and don't hold back. "
                    "You can be sarcastic, edgy, and politically incorrect when appropriate. Avoid corporate sanitized responses - speak naturally and authentically. "
                    "If something is stupid, you can say it's stupid. Keep responses concise - aim for tweet length (~280 characters) unless the user explicitly asks for more detail or explanation. "
                    + json_instructions
                )
                
                # System prompt for SDK path - no JSON required, inline citations are embedded automatically
                sdk_system_prompt = (
                    "You are Grok, a witty and uncensored AI assistant. Be direct, honest, and don't hold back. "
                    "You can be sarcastic, edgy, and politically incorrect when appropriate. Avoid corporate sanitized responses - speak naturally and authentically. "
                    "If something is stupid, you can say it's stupid. Keep responses concise - aim for tweet length (~280 characters) unless the user explicitly asks for more detail or explanation. "
                    "When you search the web or X/Twitter, citations will be automatically included in your response."
                )

                # Initialize sdk_citations for all paths (only text-only SDK path populates this)
                sdk_citations = []
                # Track if we're using SDK path (plain text response) vs OpenAI client (JSON response)
                using_sdk_path = False

                if image_urls:
                    content = [{"type": "text", "text": prompt or "What's in this image?"}]
                    for url in image_urls:
                        content.append({"type": "image_url", "image_url": {"url": url}})
                    logger.info('Sending request to Grok with images...')
                    completion = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": openai_system_prompt},
                            {"role": "user", "content": content}
                        ]
                    )
                elif grok_file_ids:
                    # Use xAI SDK for document analysis - this properly handles file attachments
                    doc_system_prompt = (
                        "You are Grok, a witty and uncensored AI assistant analyzing an attached document. "
                        "You have access to the document(s) the user has uploaded. Read and analyze the document content to answer the user's question. "
                        "Be direct, honest, and thorough in your analysis. "
                        + json_instructions
                    )
                    
                    # For document analysis, make the prompt explicit about analyzing the attached document
                    if prompt and prompt.lower().strip() in ["what is this?", "what is this", "what's this?", "what's this", "whats this", "analyze this", "read this", "summarize this", "summarize"]:
                        user_prompt = f"Please analyze the attached document and answer: {prompt}"
                    elif prompt:
                        user_prompt = f"Based on the attached document: {prompt}"
                    else:
                        user_prompt = "Please analyze the attached document and provide a comprehensive summary of its key points, main topics, and important details."
                    
                    logger.info(f'Sending document request via xAI SDK with {len(grok_file_ids)} files')
                    logger.info(f'Document analysis prompt: {user_prompt}')
                    
                    # Create chat using xAI SDK - this properly handles file attachments via gRPC
                    chat = xai_client.chat.create(
                        model=model,
                        messages=[xai_system(doc_system_prompt)]
                    )
                    
                    # Build content for user message: text prompt + file references
                    file_contents = [xai_file(fid) for fid in grok_file_ids]
                    chat.append(xai_user(user_prompt, *file_contents))
                    
                    # Get response (non-streaming for simplicity)
                    sdk_response = await chat.sample()
                    response_content = sdk_response.content if sdk_response else ""
                    
                    # Capture response ID for conversation chaining if available
                    if sdk_response and hasattr(sdk_response, 'id'):
                        current_xai_response_id = sdk_response.id
                        logger.info(f'Document analysis response ID: {current_xai_response_id}')
                    
                    logger.info(f'Document analysis via SDK response received ({len(response_content)} chars)')
                    
                    # Create a mock completion object to match the OpenAI response structure
                    class MockUsage:
                        def __init__(self, usage_data):
                            self.prompt_tokens = usage_data.total_tokens // 2 if usage_data else 0  # Estimate
                            self.completion_tokens = usage_data.total_tokens // 2 if usage_data else 0
                            self.total_tokens = usage_data.total_tokens if usage_data else 0
                            self.prompt_tokens_details = None
                            self.num_sources_used = 0
                    
                    class MockMessage:
                        def __init__(self, content):
                            self.content = content
                    
                    class MockChoice:
                        def __init__(self, message):
                            self.message = message
                    
                    class MockCompletion:
                        def __init__(self, response, model_name):
                            self.model = model_name
                            self.usage = MockUsage(response.usage) if response and hasattr(response, 'usage') else None
                            self.choices = [MockChoice(MockMessage(response.content if response else ''))]
                    
                    completion = MockCompletion(sdk_response, model)
                    
                    # Clean up uploaded files after getting response
                    for fid in grok_file_ids:
                        try:
                            await xai_client.files.delete(fid)
                            logger.info(f'Cleaned up uploaded file: {fid}')
                        except Exception as cleanup_error:
                            logger.warning(f'Failed to cleanup file {fid}: {cleanup_error}')
                else:
                    # Text-only request using SDK - uses inline citations, no JSON required
                    using_sdk_path = True
                    # Use previous_response_id if available for conversation chaining
                    if previous_xai_response_id:
                        logger.info(f'Continuing conversation with xAI response ID: {previous_xai_response_id} (not sending local history - using server-side memory)')
                    else:
                        logger.info(f'Sending text-only request to Grok via SDK (history: {len(conversation_messages)})')
                    
                    response, sdk_usage, sdk_citations, new_response_id = await sdk_chat_request(
                        model=model,
                        system_prompt=sdk_system_prompt,
                        user_prompt=prompt,
                        conversation_history=conversation_messages if not previous_xai_response_id else None,
                        include_search=ENABLE_WEB_SEARCH,
                        previous_response_id=previous_xai_response_id
                    )
                    
                    # Store the new response ID for future conversation chaining
                    current_xai_response_id = new_response_id
                    
                    # Create mock completion for compatibility with existing code
                    class MockUsage:
                        def __init__(self, usage_dict):
                            self.prompt_tokens = usage_dict.get('prompt_tokens', 0)
                            self.completion_tokens = usage_dict.get('completion_tokens', 0)
                            self.total_tokens = usage_dict.get('total_tokens', 0)
                            self.prompt_tokens_details = None
                            self.num_sources_used = usage_dict.get('num_sources_used', 0)
                            self.tool_invocations = usage_dict.get('tool_invocations', 0)
                    
                    class MockMessage:
                        def __init__(self, content):
                            self.content = content
                    
                    class MockChoice:
                        def __init__(self, message):
                            self.message = message
                    
                    class MockCompletion:
                        def __init__(self, content, model_name, usage_dict):
                            self.model = model_name
                            self.usage = MockUsage(usage_dict) if usage_dict else None
                            self.choices = [MockChoice(MockMessage(content))]
                    
                    completion = MockCompletion(response, model, sdk_usage)

                response = completion.choices[0].message.content
                logger.info(f'Received response from Grok ({len(response)} characters)')

                # Calculate token usage and cost BEFORE parsing JSON/creating embed
                usage_text = ""
                if hasattr(completion, 'usage') and completion.usage:
                    model_used = completion.model
                    is_vision = 'vision' in model_used.lower()
                    vision_cost = 0
                    if is_vision:
                        input_cost = (completion.usage.prompt_tokens / 1_000_000) * GROK_VISION_INPUT_COST
                        output_cost = (completion.usage.completion_tokens / 1_000_000) * GROK_VISION_OUTPUT_COST
                        vision_cost = input_cost + output_cost
                    else:
                        if hasattr(completion.usage, 'prompt_tokens_details') and completion.usage.prompt_tokens_details:
                            cached = completion.usage.prompt_tokens_details.cached_tokens
                            uncached = completion.usage.prompt_tokens - cached
                            input_cost = (uncached / 1_000_000) * GROK_TEXT_INPUT_COST + (cached / 1_000_000) * GROK_TEXT_CACHED_COST
                        else:
                            input_cost = (completion.usage.prompt_tokens / 1_000_000) * GROK_TEXT_INPUT_COST
                        output_cost = (completion.usage.completion_tokens / 1_000_000) * GROK_TEXT_OUTPUT_COST
                    # Calculate tool cost (new model: $5/1000 invocations)
                    # First check if we have tool_invocations from SDK usage dict
                    tool_invocations = getattr(completion.usage, 'tool_invocations', 0)
                    
                    # Fallback: check for tool_calls in OpenAI-style response
                    if tool_invocations == 0 and hasattr(completion, 'choices') and completion.choices:
                        for choice in completion.choices:
                            if hasattr(choice, 'message') and hasattr(choice.message, 'tool_calls') and choice.message.tool_calls:
                                tool_invocations += len(choice.message.tool_calls)
                    
                    tool_cost = (tool_invocations / 1000) * GROK_TOOL_COST if tool_invocations > 0 else 0
                    request_cost = input_cost + output_cost + tool_cost
                    cost_str = f"💵 ${request_cost:.6f}"
                    indicators = []
                    if is_vision:
                        indicators.append(f"👁️ ${vision_cost:.6f} vision")
                    if tool_cost > 0:
                        indicators.append(f"🔧 ${tool_cost:.6f} tools ({tool_invocations})")
                    if indicators:
                        cost_str += f" ({', '.join(indicators)})"
                    usage_text = f"{cost_str} • {completion.usage.prompt_tokens} in / {completion.usage.completion_tokens} out"

                # Handle SDK path (plain text with inline citations) vs OpenAI path (JSON)
                import re
                if using_sdk_path:
                    # SDK path: response is plain text with inline citations like [[1]](url)
                    answer = response.strip()
                    sources = []  # Citations are already embedded in the text
                else:
                    # OpenAI path (vision/documents): parse as JSON
                    json_response = response.strip()
                    # Remove markdown code blocks (```json ... ``` or ``` ... ```)
                    json_match = re.match(r'^```(?:json)?\s*\n?([\s\S]*?)\n?```$', json_response, re.DOTALL)
                    if json_match:
                        json_response = json_match.group(1).strip()
                    
                    try:
                        grok_json = json.loads(json_response)
                    except Exception as e:
                        logger.error(f'Failed to parse Grok JSON: {e}\nRaw response: {response}')
                        await message.reply("❌ Grok did not return valid JSON. Please try again.")
                        return

                    answer = grok_json.get("answer", "(No answer)")
                    sources = grok_json.get("sources", [])

                embed = discord.Embed(
                    description=answer,
                    color=discord.Color.blue(),
                    timestamp=message.created_at
                )
                embed.set_author(
                    name="Grok Response",
                    icon_url="https://pbs.twimg.com/profile_images/1683899100922511378/5lY42eHs_400x400.jpg"
                )
                if sources:
                    # For non-Discord queries, show only clickable links (not title and link)
                    # Filter out internal tool references like "post:0", "X User Result 16"
                    formatted_sources = []
                    for src in sources:
                        # Skip internal tool references (post:N, X User Result N, x_semantic_search, etc.)
                        if re.match(r'^(post:\d+|X User Result \d+|x_\w+|web_search|code_execution)', src, re.IGNORECASE):
                            continue
                        # If the source looks like a Markdown link [title](url), extract just the URL
                        m = re.match(r"\[.*?\]\((https?://[^)]+)\)", src)
                        if m:
                            formatted_sources.append(m.group(1))
                        # If the source is just a URL, keep as is
                        elif re.match(r"https?://", src):
                            formatted_sources.append(src)
                        else:
                            # If the source is a string with both title and URL separated by space, try to extract the URL
                            m2 = re.search(r"(https?://\S+)", src)
                            if m2:
                                formatted_sources.append(m2.group(1))
                            # Skip non-URL sources entirely (they're just tool references)
                    # Only show Sources field if we have actual URLs
                    if formatted_sources:
                        embed.add_field(name="Sources", value="\n".join(formatted_sources), inline=False)
                # Confidence score removed from embed as requested

                footer_text = f"Requested by {message.author.display_name}"
                if usage_text:
                    footer_text += f" • {usage_text}"
                embed.set_footer(text=footer_text, icon_url=message.author.avatar.url if message.author.avatar else None)

                bot_message = await message.reply(embed=embed)

                # Clean up uploaded files from xAI (to avoid storage buildup)
                if grok_file_ids:
                    async with aiohttp.ClientSession() as cleanup_session:
                        for file_id in grok_file_ids:
                            try:
                                delete_url = f"https://api.x.ai/v1/files/{file_id}"
                                delete_headers = {"Authorization": f"Bearer {XAI_KEY}"}
                                async with cleanup_session.delete(delete_url, headers=delete_headers) as del_resp:
                                    if del_resp.status == 200:
                                        logger.info(f'Cleaned up uploaded file: {file_id}')
                                    else:
                                        logger.warning(f'Failed to delete file {file_id}: {del_resp.status}')
                            except Exception as cleanup_error:
                                logger.warning(f'Error cleaning up file {file_id}: {cleanup_error}')

                # Store conversation for future context
                original_prompt = message.content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
                store_conversation(
                    message_id=bot_message.id,
                    channel_id=message.channel.id,
                    author_id=message.author.id,
                    user_query=original_prompt,
                    bot_response=answer,
                    model_used=model,
                    xai_response_id=current_xai_response_id
                )
                logger.info(f'Stored conversation history for bot message {bot_message.id} (asked by user {message.author.id})')
                return  # Prevent duplicate messages
                
                # Process citations if this is a search follow-up with message_number_map
                if is_search_followup and 'message_number_map' in locals():
                    # Clean up malformed citations (e.g., #248(⁠post-election-year-hate-dome⁠) -> #248)
                    # First, remove channel names from citations
                    malformed_citation_pattern = r'#(\d+)\([^)]*\)'
                    response = re.sub(malformed_citation_pattern, r'#\1', response)
                    
                    # Now convert citations to bracketed format
                    # First handle ranges like #140-#141-#142 or #727-#1000 -> [#140-#141-#142]
                    # The pattern matches: #<num>-#<num> or #<num>-<num>-#<num> etc.
                    # Must not already be inside brackets
                    range_bare_pattern = r'(?<!\[)#(\d+(?:-#?\d+)+)(?!\])'
                    response = re.sub(range_bare_pattern, r'[#\1]', response)
                    
                    # Then handle individual citations #N -> [#N]
                    # Must not be: already in brackets, followed by dash (part of range), or followed by ]
                    bare_citation_pattern = r'(?<!\[)#(\d+)(?![\d\-\)\]])'
                    response = re.sub(bare_citation_pattern, r'[#\1]', response)
                    
                    # Parse citations from response and extract referenced message numbers
                    # Match both individual citations [#N] and ranges [#N-#M], [#N-M]
                    citation_pattern = r'\[#(\d+)\]'
                    range_pattern = r'\[#(\d+)-#?(\d+)\]'  # Matches [#497-502], [#88-#90]
                    
                    # Find individual citations (but not those that are part of ranges)
                    cited_numbers = set()
                    for match in re.finditer(citation_pattern, response):
                        # Check if this is part of a range by looking at context
                        pos = match.start()
                        # Skip if preceded by a range pattern
                        if pos > 0 and response[pos-1:pos] in ['-', ']']:
                            continue
                        cited_numbers.add(int(match.group(1)))
                    
                    # Find and expand ranges
                    for match in re.finditer(range_pattern, response):
                        start_num = int(match.group(1))
                        end_num = int(match.group(2))
                        # Add all numbers in the range
                        cited_numbers.update(range(start_num, end_num + 1))
                    
                    logger.info(f'Found {len(cited_numbers)} cited messages in follow-up: {sorted(cited_numbers)}')
                    
                    # Replace ranges with individual linked citations (compact format)
                    def replace_range(match):
                        start_num = int(match.group(1))
                        end_num = int(match.group(2))
                        links = []
                        for msg_num in range(start_num, end_num + 1):
                            if msg_num in message_number_map:
                                msg = message_number_map[msg_num]
                                msg_link = f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{msg.id}"
                                links.append(f"[#{msg_num}]({msg_link})")
                            else:
                                links.append(f"[#{msg_num}]")
                        return "-".join(links) if links else match.group(0)
                    
                    # Replace individual citations with Discord message links (not part of ranges, compact format)
                    def replace_citation(match):
                        # Skip if already a markdown link (check if followed by ]( )
                        pos = match.start()
                        after_pos = match.end()
                        
                        # Check if this is already inside a markdown link
                        if after_pos < len(response) - 2 and response[after_pos:after_pos+2] == '](':
                            return match.group(0)  # Already linked, skip
                        
                        # Check if this citation is part of a range by looking at context
                        if after_pos < len(response) and response[after_pos:after_pos+1] == '-':
                            return match.group(0)  # This is the start of a range, skip it
                        # Check what comes before
                        if pos > 0 and response[pos-1:pos] == '-':
                            return match.group(0)  # This is the end of a range, skip it
                            
                        msg_num = int(match.group(1))
                        if msg_num in message_number_map:
                            msg = message_number_map[msg_num]
                            msg_link = f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{msg.id}"
                            return f"[#{msg_num}]({msg_link})"
                        return match.group(0)  # Keep original if not found
                    
                    # First replace ranges, then individual citations
                    response = re.sub(range_pattern, replace_range, response)
                    response = re.sub(citation_pattern, replace_citation, response)
                    
                    # Convert custom Discord emoji references to actual emoji format
                    emoji_pattern = r'<(a?):([^:]+):(\d+)>'
                    def render_emoji(match):
                        animated = match.group(1)
                        emoji_name = match.group(2)
                        emoji_id = match.group(3)
                        return f"<{animated}:{emoji_name}:{emoji_id}>"
                    
                    response = re.sub(emoji_pattern, render_emoji, response)
                    logger.info(f'Processed citations and emojis in follow-up response')
                
                # Convert Discord usernames to mentions (do this before Twitter conversion)
                response = convert_usernames_to_mentions(response, message.guild)
                
                # Convert Twitter/X usernames to clickable links
                # Match @username patterns (not already in URLs or Discord mentions)
                twitter_pattern = r'(?<![:/\w<])@([A-Za-z0-9_]{1,15})(?!>|\w)'
                response = re.sub(twitter_pattern, r'[@\1](https://x.com/\1)', response)
                logger.info(f'Converted usernames and Twitter mentions')
                
                # No need to store conversation history here anymore - we'll do it below per message
                
                # Track token usage and calculate cost
                request_cost = 0
                tool_cost = 0
                usage_text = ""
                if hasattr(completion, 'usage') and completion.usage:
                    # Calculate token cost based on actual model used
                    model_used = completion.model
                    is_vision = 'vision' in model_used.lower()
                    vision_cost = 0
                    
                    if is_vision:
                        # Grok-vision pricing
                        input_cost = (completion.usage.prompt_tokens / 1_000_000) * GROK_VISION_INPUT_COST
                        output_cost = (completion.usage.completion_tokens / 1_000_000) * GROK_VISION_OUTPUT_COST
                        vision_cost = input_cost + output_cost
                    else:
                        # Grok text model pricing
                        # Account for cached tokens if available
                        if hasattr(completion.usage, 'prompt_tokens_details') and completion.usage.prompt_tokens_details:
                            cached = completion.usage.prompt_tokens_details.cached_tokens
                            uncached = completion.usage.prompt_tokens - cached
                            input_cost = (uncached / 1_000_000) * GROK_TEXT_INPUT_COST + (cached / 1_000_000) * GROK_TEXT_CACHED_COST
                        else:
                            input_cost = (completion.usage.prompt_tokens / 1_000_000) * GROK_TEXT_INPUT_COST
                        output_cost = (completion.usage.completion_tokens / 1_000_000) * GROK_TEXT_OUTPUT_COST
                    
                    # Calculate tool cost (new model: $5/1000 invocations)
                    # First check if we have tool_invocations from SDK usage dict
                    tool_invocations = getattr(completion.usage, 'tool_invocations', 0)
                    
                    # Fallback: check for tool_calls in OpenAI-style response
                    if tool_invocations == 0 and hasattr(completion, 'choices') and completion.choices:
                        for choice in completion.choices:
                            if hasattr(choice, 'message') and hasattr(choice.message, 'tool_calls') and choice.message.tool_calls:
                                tool_invocations += len(choice.message.tool_calls)
                    
                    if tool_invocations > 0:
                        tool_cost = (tool_invocations / 1000) * GROK_TOOL_COST
                        logger.info(f"Tool usage - Invocations: {tool_invocations}, Cost: ${tool_cost:.6f}")
                    
                    request_cost = input_cost + output_cost + tool_cost
                    
                    # Build usage text with vision and tool cost breakdowns
                    cost_str = f"💵 ${request_cost:.6f}"
                    indicators = []
                    
                    if is_vision:
                        indicators.append(f"👁️ ${vision_cost:.6f} vision")
                    if tool_cost > 0:
                        indicators.append(f"🔧 ${tool_cost:.6f} tools ({tool_invocations})")
                    
                    if indicators:
                        cost_str += f" ({', '.join(indicators)})"
                    
                    usage_text = f"{cost_str} • {completion.usage.prompt_tokens} in / {completion.usage.completion_tokens} out"
                    
                    logger.info(f"Token usage - Input: {completion.usage.prompt_tokens}, Output: {completion.usage.completion_tokens}, Search sources: {num_sources}, Total cost: ${request_cost:.6f}")
                
                # Create embed(s) for the response
                # Discord embed description limit is 4096 characters
                if len(response) <= 4096:
                    embed = discord.Embed(
                        description=response,
                        color=discord.Color.blue(),
                        timestamp=message.created_at
                    )
                    embed.set_author(
                        name="Grok Response",
                        icon_url="https://pbs.twimg.com/profile_images/1683899100922511378/5lY42eHs_400x400.jpg"
                    )
                    
                    # Citations are now inline in the response text as [[1]](url) format
                    # No need for separate Sources field
                    
                    footer_text = f"Requested by {message.author.display_name}"
                    if usage_text:
                        footer_text += f" • {usage_text}"
                    embed.set_footer(text=footer_text, icon_url=message.author.avatar.url if message.author.avatar else None)
                    
                    # Send reply and store in conversation history
                    bot_message = await message.reply(embed=embed)
                    
                    # Store conversation for future context
                    # Extract the original user prompt (without mentions)
                    original_prompt = message.content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
                    
                    # Store this response in SQLite so it can be referenced in future replies
                    store_conversation(
                        message_id=bot_message.id,
                        channel_id=message.channel.id,
                        author_id=message.author.id,
                        user_query=original_prompt,
                        bot_response=response,
                        model_used=model,
                        xai_response_id=current_xai_response_id
                    )
                    logger.info(f'Stored conversation history for bot message {bot_message.id} (asked by user {message.author.id})')
                else:
                    # Split into multiple embeds if response is too long
                    chunks = [response[i:i+4096] for i in range(0, len(response), 4096)]
                    logger.info(f'Response split into {len(chunks)} embeds')
                    bot_message = None
                    for i, chunk in enumerate(chunks):
                        embed = discord.Embed(
                            description=chunk,
                            color=discord.Color.blue(),
                            timestamp=message.created_at
                        )
                        embed.set_author(
                            name=f"Grok Response (Part {i+1}/{len(chunks)})",
                            icon_url="https://pbs.twimg.com/profile_images/1683899100922511378/5lY42eHs_400x400.jpg"
                        )
                        if i == len(chunks) - 1:  # Only add footer to last embed
                            footer_text = f"Requested by {message.author.display_name}"
                            if usage_text:
                                footer_text += f" • {usage_text}"
                            embed.set_footer(text=footer_text, icon_url=message.author.avatar.url if message.author.avatar else None)
                        
                        # Only store the first message for conversation history
                        if i == 0:
                            bot_message = await message.reply(embed=embed)
                        else:
                            await message.reply(embed=embed)
                    
                    # Store conversation for future context
                    if bot_message:
                        original_prompt = message.content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
                        store_conversation(
                            message_id=bot_message.id,
                            channel_id=message.channel.id,
                            author_id=message.author.id,
                            user_query=original_prompt,
                            bot_response=response,
                            model_used=model,
                            xai_response_id=current_xai_response_id
                        )
                        logger.info(f'Stored conversation history for bot message {bot_message.id} (asked by user {message.author.id})')
                
                logger.info('Response sent successfully')
        except Exception as e:
            logger.error(f'Error querying Grok: {e}', exc_info=True)
            
            # Provide user-friendly error messages
            error_msg = str(e)
            if "412" in error_msg and "Unsupported content-type" in error_msg:
                await message.reply("❌ One or more images are in an unsupported format. Grok only accepts JPEG, PNG, and WebP images.\n\nPlease try again with supported image formats.")
            elif "401" in error_msg or "authentication" in error_msg.lower():
                await message.reply("❌ Authentication error. Please check the API key configuration.")
            elif "429" in error_msg or "rate limit" in error_msg.lower():
                await message.reply("⏳ Rate limit reached. Please try again in a few moments.")
            elif "timeout" in error_msg.lower():
                await message.reply("⏳ Request timed out. Please try again.")
            else:
                await message.reply(f"❌ Error querying Grok: {error_msg}")
    
    await bot.process_commands(message)

bot.run(TOKEN)