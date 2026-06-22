import logging
import os

import pytz
from dotenv import load_dotenv


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('GrokBot')


dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    logger.info(f'Loading environment from {dotenv_path}')
    load_dotenv(dotenv_path)
else:
    logger.info('.env file not found, using environment variables')
    load_dotenv()


TOKEN = os.getenv('DISCORD_TOKEN')
XAI_KEY = os.getenv('XAI_API_KEY')

if TOKEN:
    logger.info(f'DISCORD_TOKEN loaded (length: {len(TOKEN)})')
else:
    logger.error('DISCORD_TOKEN not found in environment!')

if XAI_KEY:
    logger.info(f'XAI_API_KEY loaded (length: {len(XAI_KEY)})')
else:
    logger.error('XAI_API_KEY not found in environment!')


TIMEZONE = pytz.timezone(os.getenv('TIMEZONE', 'America/Chicago'))

GROK_TEXT_MODEL = os.getenv('GROK_TEXT_MODEL', 'grok-4.3')
GROK_VISION_MODEL = os.getenv('GROK_VISION_MODEL', 'grok-4.3')
GROK_DOCUMENT_MODEL = os.getenv('GROK_DOCUMENT_MODEL', 'grok-4.3')
GROK_IMAGE_MODEL = os.getenv('GROK_IMAGE_MODEL', 'grok-imagine-image-quality')

ENABLE_WEB_SEARCH = os.getenv('ENABLE_WEB_SEARCH', 'true').lower() == 'true'
ENABLE_X_SEARCH = os.getenv('ENABLE_X_SEARCH', 'false').lower() == 'true'
ENABLE_CODE_EXECUTION = os.getenv('ENABLE_CODE_EXECUTION', 'false').lower() == 'true'
ENABLE_NL_HISTORY_SEARCH = os.getenv('ENABLE_NL_HISTORY_SEARCH', 'true').lower() == 'true'
ENABLE_COMEDY_DIRECTOR = os.getenv('ENABLE_COMEDY_DIRECTOR', 'true').lower() == 'true'
ENABLE_PROMPT_CACHE_HINTS = os.getenv('ENABLE_PROMPT_CACHE_HINTS', 'true').lower() == 'true'

GROK_REASONING_EFFORT = os.getenv('GROK_REASONING_EFFORT', 'low').lower()
GROK_ANALYSIS_REASONING_EFFORT = os.getenv('GROK_ANALYSIS_REASONING_EFFORT', 'high').lower()

MAX_KEYWORD_SCAN = int(os.getenv('MAX_KEYWORD_SCAN', '10000'))
MAX_MESSAGES_ANALYZED = int(os.getenv('MAX_MESSAGES_ANALYZED', '500'))
DEFAULT_SEARCH_LIMIT = int(os.getenv('DEFAULT_SEARCH_LIMIT', '5000'))

GROK_TEXT_INPUT_COST = float(os.getenv('GROK_TEXT_INPUT_COST', '1.25'))
GROK_TEXT_OUTPUT_COST = float(os.getenv('GROK_TEXT_OUTPUT_COST', '2.50'))
GROK_TEXT_CACHED_COST = float(os.getenv('GROK_TEXT_CACHED_COST', '0.20'))
GROK_VISION_INPUT_COST = float(os.getenv('GROK_VISION_INPUT_COST', '1.25'))
GROK_VISION_OUTPUT_COST = float(os.getenv('GROK_VISION_OUTPUT_COST', '2.50'))
GROK_IMAGE_OUTPUT_COST = float(os.getenv('GROK_IMAGE_OUTPUT_COST', '0.05'))
GROK_TOOL_COST = float(os.getenv('GROK_TOOL_COST', '5.00'))

DB_PATH = os.getenv('CONVERSATION_DB_PATH', 'data/conversation_history.db')
CONVERSATION_RETENTION_HOURS = int(os.getenv('CONVERSATION_RETENTION_HOURS', '24'))
PERSONA_STORE_PATH = os.getenv('PERSONA_STORE_PATH', 'data/personas.json')
