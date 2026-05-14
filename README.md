# Grok Discord Bot

A Discord bot that integrates with xAI's Grok API to answer questions, with advanced message search, image support, live web search, and conversation memory.

> **⚠️ Important:** This bot requires an xAI Grok API key, which is a **paid service**. You will be charged based on token usage and web search requests. See the [Cost Information](#cost-information) section below for pricing details.

> **🎨 Vibecoded Notice:** This project was developed entirely through AI-assisted coding (even this readme). No formal testing, validation, or quality assurance was performed. Features may break unexpectedly, edge cases are probably unhandled, and bugs are likely lurking. Use at your own risk and expect the occasional chaos. PRs welcome if you find something broken! 🚀

## Features

- 🤖 **AI Responses**: Powered by Grok 4.3 for text, image understanding, and document analysis (using official xAI SDK)
- 🔎 **Advanced Message Search**: Search and analyze message history with inline citations
  - Search by user or entire channel
  - Keyword filtering for targeted searches
  - Clickable citations linking directly to referenced messages
  - Real-time progress updates for large scans
- 🧠 **Natural Language History Analysis**: Ask questions about Discord history naturally
  - "who talks about Python the most in the past month?"
  - "what have we discussed about AI recently?"
  - "summarize our conversations from last week"
  - Automatically detects when to search Discord vs. general questions
- 🖼️ **Image Analysis**: Upload images or paste image URLs for vision analysis
- 📄 **Document Analysis**: Upload PDFs, TXT, code files for Grok-powered answers (using xAI SDK file upload)
- 🔍 **Live Web Search**: Real-time web searches with xAI SDK agent tools and citations
- 🐦 **X/Twitter Search** (Optional): Search X/Twitter for real-time social context
- 💻 **Code Execution** (Optional): Let Grok run Python code for calculations and data analysis
- 💬 **Conversation Memory (Memory Bank)**: Persistent SQLite storage remembers full conversation threads and acts as a memory bank
  - Stores every user query and bot response for context and follow-up
  - Automatic cleanup of old conversations (configurable retention period)
  - Survives bot restarts
  - Thread-aware context tracking
  - Used for follow-up questions and context-aware responses
- 💵 **Cost Transparency**: Shows exact cost per request including search
- 🌍 **Timezone Support**: Configurable timezone for accurate timestamps

## Requirements

### System Requirements
- **Python 3.11 or higher** (tested on 3.11+)
- **pip** (Python package manager)
- **Internet connection** (for API calls to xAI and Discord)

### API Keys Required
- **Discord Bot Token** (free - from Discord Developer Portal)
- **xAI API Key** (paid - from https://x.ai/api)

### Python Dependencies
All dependencies are listed in `requirements.txt`:
- `discord.py` - Discord bot framework
- `openai` - OpenAI-compatible client (used for vision API)
- `xai-sdk` - Official xAI SDK for chat, file uploads, web search, X search, and code execution
- `aiohttp` - Async HTTP client for image generation API
- `python-dotenv` - Environment variable management
- `pytz` - Timezone handling for accurate timestamps
- `spacy` - Advanced NLP for entity and topic extraction
- `torch` - Required for transformer-based intent classification
- `transformers` - Hugging Face zero-shot intent classification

### Optional
- **Docker** - For containerized deployment (includes all NLP dependencies and spaCy model)
- **Git** - For cloning the repository and version control

## Advanced NLP Features (NEW!)
-
## Document Support (NEW!)

You can now upload documents as Discord attachments when mentioning the bot or replying to it. The bot uses the official xAI SDK to upload files and analyze them with Grok. This enables:

- 📄 **Multiple file formats**: PDF, TXT, MD, CSV, JSON, and code files (.py, .js, .java, .c, .cpp, .ts, .go, .rs, .rb, .php)
- 🔗 **Multi-file support**: Attach multiple supported documents in a single message
- 🧹 **Automatic cleanup**: Files are deleted from xAI servers after analysis
- 🚫 **Unsupported files**: Other file types are ignored (user is notified if only unsupported files are attached)

**Example Usage:**
```
@Gronk summarize the attached PDF
@Gronk what are the main points in this document?
@Gronk extract all TODOs from the attached code file
@Gronk analyze this CSV data
```

**Supported file types:**
- PDF (.pdf)
- Plain Text (.txt)
- Markdown (.md)
- CSV (.csv)
- JSON (.json)
- Code files: .py, .js, .java, .c, .cpp, .h, .ts, .go, .rs, .rb, .php

**How it works:**
- The bot detects supported document attachments
- Files are uploaded to xAI via the official SDK (gRPC-based for proper file handling)
- The file references are included in the Grok chat using the SDK's `file()` helper
- Grok analyzes the document content and responds
- Files are automatically cleaned up after analysis

The bot now uses state-of-the-art NLP for deeper understanding of queries:

- 🏷️ **Entity Extraction**: Uses spaCy to extract people, dates, organizations, and topics from queries
- 🧠 **Topic Detection**: Identifies key topics and noun phrases for more accurate search and filtering
- 🎯 **Intent Classification**: Uses Hugging Face transformers (zero-shot) to classify query intent (e.g., Discord history, general knowledge, user search, topic summary)
- 🔬 **Multi-word & Contextual Keywords**: Supports complex queries like "What did @john say about crypto between January and March?"
- 🌐 **Multilingual Ready**: spaCy and transformers can be extended for other languages

**Example Queries:**
```
Who mentioned Python and AI the most in the last year?
What did @john say about crypto between January and March?
Summarize our discussions about machine learning in this channel.
Who are the most active users here in the past week?
What topics did @role members talk about last Friday?
Who is the most famous AI researcher in the world?
Summarize news from last week.
```

**Testing Advanced NLP:**
Run the test script to see entity, topic, and intent extraction:
```powershell
python test_advanced_nlp.py "Who talked about AI and crypto in the last year?"
```
Output will show extracted entities, topics, and intent.

## Setup

### 1. Create a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **"New Application"** and give it a name (e.g., "Gronk")
3. Go to the **"Bot"** tab in the left sidebar
4. Click **"Add Bot"** and confirm
5. Under the bot's username, click **"Reset Token"** and copy your bot token (save this for later)
6. Scroll down to **"Privileged Gateway Intents"** and enable:
   - ✅ Presence Intent
   - ✅ Server Members Intent
   - ✅ Message Content Intent
7. Click **"Save Changes"**

### 2. Invite the Bot to Your Server

1. In the Discord Developer Portal, go to the **"OAuth2"** tab
2. Click on **"URL Generator"** in the left sidebar
3. Under **"Scopes"**, select:
   - ✅ `bot`
4. Under **"Bot Permissions"**, select:
   - ✅ Read Messages/View Channels
   - ✅ Send Messages
   - ✅ Send Messages in Threads
   - ✅ Embed Links
   - ✅ Attach Files
   - ✅ Read Message History
   - ✅ Mention Everyone (optional, for @mentions)
   - ✅ Add Reactions (optional)
   - ✅ Use Slash Commands (optional)
5. Copy the generated URL at the bottom and open it in your browser
6. Select the server you want to add the bot to and click **"Authorize"**

### 3. Get an xAI API Key

1. Go to https://x.ai/api
2. Sign up or log in to your xAI account
3. Navigate to the API Keys section
4. Create a new API key and copy it (save this for later)

### 4. Configure the Bot

1. Copy `.env.example` to `.env`:
   ```powershell
   cp .env.example .env
   ```
2. Edit `.env` and add your tokens:
   ```
   DISCORD_TOKEN=your_discord_token_here
   XAI_API_KEY=your_xai_api_key_here
   ```
3. **(Optional)** Customize model, search, timezone, and pricing settings:
   ```
   # Model Configuration (Optional - defaults shown)
  GROK_TEXT_MODEL=grok-4.3
  GROK_VISION_MODEL=grok-4.3
  GROK_IMAGE_MODEL=grok-imagine-image-quality
  GROK_DOCUMENT_MODEL=grok-4.3
   
   # Timezone Configuration (Optional - defaults to America/Chicago)
   # Use IANA timezone names: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
   # Examples: America/New_York, America/Los_Angeles, Europe/London, Asia/Tokyo
   TIMEZONE=America/Chicago
   
   # Search Configuration (Optional - defaults shown)
   ENABLE_WEB_SEARCH=true
   ENABLE_X_SEARCH=false
   ENABLE_CODE_EXECUTION=false
   ENABLE_PROMPT_CACHE_HINTS=true
   GROK_REASONING_EFFORT=low
   GROK_ANALYSIS_REASONING_EFFORT=high
   MAX_KEYWORD_SCAN=10000
   MAX_MESSAGES_ANALYZED=500
   ENABLE_NL_HISTORY_SEARCH=true
   PERSONA_STORE_PATH=data/personas.json
   
  # Pricing Configuration (Optional - defaults based on current xAI Grok 4.3 pricing)
  GROK_TEXT_INPUT_COST=1.25
  GROK_TEXT_OUTPUT_COST=2.50
  GROK_TEXT_CACHED_COST=0.20
  GROK_VISION_INPUT_COST=1.25
  GROK_VISION_OUTPUT_COST=2.50
  GROK_IMAGE_OUTPUT_COST=0.05
  GROK_TOOL_COST=5.00
   ```
   
   **Configuration Options:**
   - **GROK_TEXT_MODEL**: Model used for text-only responses (default: grok-4.3)
  - **GROK_VISION_MODEL**: Model used when analyzing images (default: grok-4.3)
  - **GROK_DOCUMENT_MODEL**: Model used when analyzing uploaded documents (default: grok-4.3)
  - **GROK_IMAGE_MODEL**: Model used for image generation (default: grok-imagine-image-quality)
   - **TIMEZONE**: Timezone for message timestamps (default: America/Chicago)
   - **ENABLE_WEB_SEARCH**: Enable/disable live web search (default: true)
   - **ENABLE_X_SEARCH**: Enable X/Twitter search (default: false)
   - **ENABLE_CODE_EXECUTION**: Enable Python code execution (default: false)
   - **ENABLE_PROMPT_CACHE_HINTS**: Send stable conversation/cache IDs to improve prompt cache hits (default: true)
   - **GROK_REASONING_EFFORT**: Reasoning effort for normal chat, one of `none`, `low`, `medium`, `high` (default: low)
   - **GROK_ANALYSIS_REASONING_EFFORT**: Reasoning effort for document, image, and Discord history analysis (default: high)
   - **MAX_KEYWORD_SCAN**: Maximum messages to scan for keyword searches (default: 10,000)
   - **MAX_MESSAGES_ANALYZED**: Maximum messages sent to Grok for analysis (default: 500, higher = better analysis but more cost)
   - **ENABLE_NL_HISTORY_SEARCH**: Enable natural language history detection (default: true)
   - **PERSONA_STORE_PATH**: JSON file for generated personas and active channel selections (default: data/personas.json)
  - **Pricing variables**: Cost per 1M tokens (text/vision input/output, cached), per image, and per 1K tool invocations

### 5. Install and Run

1. Install dependencies:
  ```powershell
  pip install -r requirements.txt
  ```
  This will install all required NLP libraries (spaCy, torch, transformers). The first run will download the spaCy English model automatically.

2. Run the bot:
  ```powershell
  python main.py
  ```
  The bot will be online in your Discord server.

3. (Optional) Test advanced NLP extraction:
  ```powershell
  python test_advanced_nlp.py "Who talked about AI and crypto in the last year?"
  ```
  This will print extracted entities, topics, and intent for your query.

### Docker Support

The Docker image now includes all advanced NLP dependencies and downloads the spaCy English model at build time. To build and run:
```sh
docker build -t gronk-bot .
docker run --env-file .env gronk-bot
```
This ensures all NLP features work out of the box in containers.

## Usage


### Image Generation

Gronk can generate AI images directly in Discord using natural language:

**Examples:**
```
@Gronk generate an image of a futuristic city skyline at sunset
@Gronk draw me a picture of a cat wearing a space helmet
@Gronk create an image of a serene mountain landscape
```

**Trigger Phrases:**
- "generate an image of..."
- "draw a picture of..."
- "create an image..."
- "show me an image of..."
- "visualize..."
- "illustrate..."

- The bot will reply with an AI-generated image based on your prompt.
- Click "Generate More Versions" to get 4 new variations of your prompt (costs scale per image).
- To adjust or iterate, reply to the image embed with a new prompt or additional details—the bot will combine your new text with the original prompt for the next generation.

**Cost:** Each generated image is billed at the rate set in your `.env` (`GROK_IMAGE_OUTPUT_COST`, default: $0.05 per 1K image). Generating more versions multiplies the cost (e.g., 4 images = $0.20).

**Supported Models:** Uses the model set in `GROK_IMAGE_MODEL` (default: `grok-imagine-image-quality`).

**Note:** Image generation requires an xAI API key with image generation enabled. See the [Cost Information](#cost-information) section for details.

---

### Personas

Gronk can ask Grok to create reusable assistant personas, save them locally, and let you select the active persona for each Discord channel.

**Examples:**
```
@Gronk create a persona for a concise senior Python reviewer
@Gronk generate a personality that explains NAS issues like a patient sysadmin
@Gronk refine current persona to be less sarcastic and more concise
@Gronk clone default persona as Patient Grok
@Gronk list personas
@Gronk select persona
@Gronk clear persona
```

- New personas are saved to `PERSONA_STORE_PATH` and selected for the current channel immediately.
- Refine/edit requests update the selected persona and keep a short local edit history.
- Persona generation and refinement embeds include an estimated Grok token cost in the footer.
- The built-in `default` persona is protected. Refining it automatically creates and edits a clone instead.
- Clone requests copy the active persona by default, or `default` / a persona ID if specified.
- Listing/selecting personas shows a Discord dropdown with the saved choices.
- The active persona is channel-scoped, so one channel can use a code-reviewer persona while another keeps the default Grok style.

---

### Basic Interaction
- **Mention the bot**: `@Gronk what's the weather?`
- **Reply to Gronk**: Reply to any of Gronk's messages without mentioning (conversation memory)
- **Upload images**: Attach images or paste image URLs for visual analysis
- **Reply chains**: Gronk sees full conversation context in reply threads

### Natural Language History Analysis

Gronk can answer questions about recent Discord history when the prompt clearly asks about this server/channel/chat.

- **Conservative Routing**: Uses explicit Discord/history cues so normal questions do not accidentally scan chat history
- **Time Recognition**: Recognizes temporal phrases like "past month", "last week", "recently"
- **Topic Extraction**: Detects topics like "about Python" or "regarding AI" for filtering
- **Cited Analysis**: Includes clickable message links for cited Discord messages
- **Efficient Scanning**: Automatically scans only `MAX_MESSAGES_ANALYZED` for broad history queries

**What triggers Discord search:**
- Discord scope plus history/action wording: "who mentioned crypto in this channel?"
- Discord pronouns plus discussion/history wording: "what have we discussed about AI recently?"
- User mentions plus message/activity wording: "@john what has he said about Python?"
- Explicit summaries/rankings of server/channel activity

**What stays as general queries:**
- User mentions without history wording: `@Gronk @john what are his opinions?`
- General knowledge: `@Gronk who invented Python?`
- World/news context: `@Gronk summarize news from last week`
- No Discord history indicators: `@Gronk explain quantum computing`

**Configuration:**
- Set `ENABLE_NL_HISTORY_SEARCH=false` in `.env` to disable this feature

### Advanced History Search

For more advanced searches, you can include additional context in your natural language queries:

**Examples:**
```
@Gronk @john what has he said about Python?        # Search specific user
@Gronk what did people say about AI in here?      # Search all users
@Gronk summarize our discussions about bots       # Topic-focused search
```

**Features:**
- 🔗 **Inline Citations**: Grok cites specific messages as `[#5]` which become clickable links
- 📊 **Progress Updates**: Real-time scan progress for large searches (updates every 2000 messages)
- 🔄 **Follow-up Queries**: Reply to search results to ask follow-up questions with same context
- 🎯 **Range Citations**: Supports ranges like `[#58-59]` or `[#68-70]` for multiple messages
- 😀 **Emoji Support**: Custom Discord emojis are preserved and rendered correctly
- 🕐 **Smart Timestamps**: All timestamps converted to your configured timezone

**Search Behavior:**
- **General search**: Scans up to `MAX_MESSAGES_ANALYZED` (default: 500-1000)
  - Fast and efficient since we only scan what can be analyzed
  - Perfect for recent history analysis
- **Keyword search**: Scans up to `MAX_KEYWORD_SCAN` (default: 10,000) to find matching messages
  - ⚠️ **Performance Warning**: Keyword searches can take 10-30+ seconds depending on `MAX_KEYWORD_SCAN` value
  - With `MAX_KEYWORD_SCAN=10000`: ~10-20 seconds
  - With `MAX_KEYWORD_SCAN=25000`: ~30-60 seconds
  - With `MAX_KEYWORD_SCAN=50000`: ~60-120+ seconds
  - Progress updates shown every 2000 messages to indicate the bot is still working
  - Reduce `MAX_KEYWORD_SCAN` in `.env` for faster searches at the cost of less history coverage
- **Analysis limit**: Only the most recent `MAX_MESSAGES_ANALYZED` messages are sent to Grok (default: 500)
  - Increase for deeper analysis: `MAX_MESSAGES_ANALYZED=1000` or even higher
  - 100 msgs ≈ $0.002-0.005, 500 msgs ≈ $0.01-0.025, 1000 msgs ≈ $0.02-0.05
  - This is the actual limit on what Grok sees, not what we scan
- **Message length**: Each message truncated to 300 characters in analysis
- **Bot filtering**: Bot messages excluded from channel-wide searches
- **Response splitting**: Automatic splitting for long responses with citation preservation

### Cost Information

**Token-Based Pricing:**
- **Grok 4.3**: $1.25/1M input tokens, $2.50/1M output tokens
- **Grok 4.3 cached input tokens**: $0.20/1M
- **Higher context pricing**: xAI applies different rates to requests that exceed the 200K context window

**Server-Side Tool Pricing:**
Tool-enabled requests are billed as Grok 4.3 token usage plus tool invocations. The agent decides how many tools to call, so search-heavy questions can cost more.
- **Web Search (`web_search`)**: $5.00 per 1,000 calls
- **X/Twitter Search (`x_search`)**: $5.00 per 1,000 calls (requires `ENABLE_X_SEARCH=true`)
- **Code Execution (`code_execution`)**: $5.00 per 1,000 calls (requires `ENABLE_CODE_EXECUTION=true`)
- **File attachment search (`attachment_search`)**: $10.00 per 1,000 calls, if xAI invokes attachment search for uploaded files
- **Image understanding during Web/X Search (`view_image`)**: token-based, not a separate tool invocation fee

**Image Generation:**
- **Grok Imagine image generation**: Configurable via `GROK_IMAGE_OUTPUT_COST` (default: $0.05 per 1K image; 2K is currently $0.07)

> **Note:** Pricing and models are subject to change by xAI. Check [x.ai/api](https://x.ai/api) for current pricing. To update models, edit `GROK_TEXT_MODEL`, `GROK_VISION_MODEL`, `GROK_DOCUMENT_MODEL`, and `GROK_IMAGE_MODEL` in your `.env` file.

> **Cost Calculations:** The bot displays estimated costs on each response card based on pricing values configured in your `.env` file. Web/X/code tool calls use `GROK_TOOL_COST=5.00` per 1,000 invocations. If xAI changes pricing, update the `GROK_*_COST` variables in your `.env` file.

## Architecture

- **Models**: Grok 4.3 for text, image understanding, and document analysis; image generation remains configured separately with `GROK_IMAGE_MODEL`
- **Code Layout**:
  - `main.py`: Discord bot wiring, message routing, and response orchestration
  - `config.py`: environment loading and runtime configuration
  - `grok_client.py`: OpenAI-compatible xAI client and SDK chat helper
  - `grok_responder.py`: Grok request routing, response embeds, cost display, and conversation storage
  - `image_generation.py`: image generation and revision flow
  - `persona_manager.py`: persona generation, JSON persistence, and Discord selection UI
  - `discord_history.py`: Discord-history intent detection, scanning, and analysis
  - `document_utils.py`: document upload and xAI file cleanup helpers
  - `media_utils.py`: image/document attachment and embed media collection
  - `reply_context.py`: reply-chain context gathering for follow-up questions
  - `conversation_store.py`: SQLite conversation memory helpers
  - `nlp_utils.py`: spaCy loading, intent patterns, and NLP parsing
  - `discord_utils.py`: Discord-specific formatting helpers
- **xAI SDK Integration**: Uses official xAI SDK with `store_messages=True` for server-side conversation memory
  - xAI stores conversation history on their servers
  - Each response includes a `response_id` that chains to the next request via `previous_response_id`
  - Enables Grok to remember context without resending full history
  - Response IDs stored in SQLite alongside local conversation history
  - Stable conversation IDs are sent when `ENABLE_PROMPT_CACHE_HINTS=true` to improve prompt cache reuse
  - Structured output schemas are used for bot answers, document answers, and Discord history citations
  - Grok 4.3 reasoning effort is configurable separately for normal chat and heavier analysis
- **Web Search**: xAI SDK agent web search tool, enabled by default
- **X/Twitter Search**: Real-time social search via xAI's `x_search` tool (optional)
- **Code Execution**: Python sandbox via xAI's `code_execution` tool (optional)
- **Personas**: Grok-generated reusable system prompts with per-channel selection stored in `PERSONA_STORE_PATH`
- **Natural Language Detection**: Conservative rule-based routing for Discord history queries
- **Message Search**: Optimized scanning with progress tracking, citation linking, and timezone conversion
- **Memory (Memory Bank)**: SQLite persistent storage with thread-aware context
  - Stores every user query, bot response, and xAI response ID for conversation chaining
  - Used for follow-up questions, context-aware responses, and persistent memory
  - Traverses full reply chains (up to 10 messages deep) to build complete thread context
  - Automatic cleanup of conversations older than 24 hours (configurable)
  - Survives bot restarts and container rebuilds
  - Database persisted via volume mounts in Docker deployments
  - No semantic search or vector memory (yet) – all memory is message-based
- **Image Support**: JPEG, PNG, WebP (attachments, URLs, embeds)
- **Context**: Reply chain traversal + time-aware message history (2-minute window)
- **Citation System**: Selective citations (3-6 per response) with individual message linking `[#N]` (no ranges)
- **Timezone**: pytz-based timezone conversion with automatic DST handling
- **Query Routing**: Conservative local rule-based detection for Discord history queries

## Troubleshooting

### General Issues
- **Bot doesn't respond**: Check that Message Content Intent is enabled in Discord Developer Portal
- **Image errors**: Only JPEG, PNG, and WebP formats are supported
- **High costs**: Reduce `MAX_MESSAGES_ANALYZED`, lower search/history limits, or disable `ENABLE_WEB_SEARCH` in `.env`
- **Slow keyword searches**: Reduce `MAX_KEYWORD_SCAN` in `.env` (default: 10,000)
- **Wrong timestamps**: Set correct `TIMEZONE` in `.env` using IANA timezone names
- **Citations not linking**: Ensure messages are in the analyzed set (limited by `MAX_MESSAGES_ANALYZED`)
- **Embed size errors**: Automatically handled by splitting into multiple embeds
- **Want more detailed analysis**: Increase `MAX_MESSAGES_ANALYZED` in `.env` (costs scale linearly)

### Natural Language History Analysis
- **Bot searches Discord when I ask general questions**: 
  - Check your phrasing for Discord indicators ("we", "here", "this channel")
  - Add world context: "in history", "globally", "in the world"
  - Example: Change "who is the smartest?" to "who is the smartest in history?"
  
- **Bot doesn't search Discord when I want it to**:
  - Add Discord indicators: "here", "in this channel", "what have WE discussed"
  - Mention a user: `@Gronk @john what did he say?`
  - Be explicit: "search this channel for..."
  
- **Disable natural language detection**:
  - Set `ENABLE_NL_HISTORY_SEARCH=false` in `.env`
  - History searches will be treated as general queries

### Testing
Run the test script to verify natural language detection:
```powershell
python test_nl_detection.py
```
