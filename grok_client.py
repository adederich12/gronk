import logging

from openai import OpenAI
from xai_sdk import AsyncClient as XAIAsyncClient
from xai_sdk.chat import assistant as xai_assistant
from xai_sdk.chat import system as xai_system
from xai_sdk.chat import user as xai_user
from xai_sdk.tools import code_execution as xai_code_execution
from xai_sdk.tools import web_search as xai_web_search
from xai_sdk.tools import x_search as xai_x_search

from config import (
    ENABLE_CODE_EXECUTION,
    ENABLE_PROMPT_CACHE_HINTS,
    ENABLE_WEB_SEARCH,
    ENABLE_X_SEARCH,
    GROK_REASONING_EFFORT,
    XAI_KEY,
)


logger = logging.getLogger('GrokBot')

client = OpenAI(api_key=XAI_KEY, base_url="https://api.x.ai/v1")
_xai_client = None


def normalize_openai_reasoning_effort(effort=None):
    effort = (effort or GROK_REASONING_EFFORT or '').lower().strip()
    if effort in {'none', 'low', 'medium', 'high'}:
        return effort
    logger.warning(f'Unsupported GROK reasoning effort "{effort}", falling back to low')
    return 'low'


def normalize_sdk_reasoning_effort(effort=None):
    effort = normalize_openai_reasoning_effort(effort)
    if effort == 'none':
        return None
    if effort in {'medium', 'high'}:
        return 'high'
    return 'low'


def build_cache_conversation_id(*parts):
    if not ENABLE_PROMPT_CACHE_HINTS:
        return None
    cleaned = [str(part).strip() for part in parts if part is not None and str(part).strip()]
    if not cleaned:
        return None
    return 'gronk-' + '-'.join(cleaned)[:96]


def _count_server_side_tool_usage(usage):
    """Best-effort count for SDK server-side tool usage shapes."""
    if not usage:
        return 0
    if isinstance(usage, int):
        return usage
    if isinstance(usage, (list, tuple, set)):
        return len(usage)
    if isinstance(usage, dict):
        total = 0
        for value in usage.values():
            if isinstance(value, int):
                total += value
            elif isinstance(value, dict):
                for key in ('calls', 'count', 'invocations', 'num_calls'):
                    if isinstance(value.get(key), int):
                        total += value[key]
                        break
            elif isinstance(value, (list, tuple, set)):
                total += len(value)
        return total
    return 0


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
                           previous_response_id: str = None, response_format=None,
                           reasoning_effort: str = None, conversation_id: str = None) -> tuple:
    """
    Make a chat request using the xAI SDK Agent Tools API.

    Returns: (response_content: str, usage_dict: dict, citations: list, response_id: str)
    """
    xai_client = get_xai_client()
    tools = build_sdk_tools() if include_search else None
    sdk_reasoning_effort = normalize_sdk_reasoning_effort(reasoning_effort)

    chat_kwargs = {
        'model': model,
        'store_messages': True,
        'tools': tools,
        'include': ["inline_citations"],
    }
    if conversation_id:
        chat_kwargs['conversation_id'] = conversation_id
    if sdk_reasoning_effort:
        chat_kwargs['reasoning_effort'] = sdk_reasoning_effort
    if response_format:
        chat_kwargs['response_format'] = response_format

    if previous_response_id:
        logger.info(f'Continuing conversation from xAI response ID: {previous_response_id}')
        chat_kwargs['previous_response_id'] = previous_response_id
        chat = xai_client.chat.create(**chat_kwargs)
    else:
        messages = [xai_system(system_prompt)]

        if conversation_history:
            for msg in conversation_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    messages.append(xai_user(content))
                elif role == "assistant":
                    messages.append(xai_assistant(content))

        chat_kwargs['messages'] = messages
        chat = xai_client.chat.create(**chat_kwargs)

    chat.append(xai_user(user_prompt))
    if response_format:
        response, parsed = await chat.parse(response_format)
        content = parsed.model_dump_json() if hasattr(parsed, 'model_dump_json') else parsed.json()
    else:
        response = await chat.sample()
        content = response.content if response else ""

    citations = response.citations if response and hasattr(response, 'citations') else []
    response_id = response.id if response and hasattr(response, 'id') else None

    if citations:
        logger.info(f'Got {len(citations)} citations (sources examined)')

    if response and hasattr(response, 'tool_calls') and response.tool_calls:
        logger.info(f'Tool invocations: {len(response.tool_calls)} calls')
        for tool_call in response.tool_calls:
            if hasattr(tool_call, 'function'):
                logger.info(f'  - {tool_call.function.name}')
    if response and hasattr(response, 'server_side_tool_usage') and response.server_side_tool_usage:
        logger.info(f'Server-side tool usage: {response.server_side_tool_usage}')

    if response_id:
        logger.info(f'Got xAI response ID: {response_id}')

    usage = {}
    tool_invocations = 0

    if response and hasattr(response, 'tool_calls') and response.tool_calls:
        tool_invocations = len(response.tool_calls)
    if response and hasattr(response, 'server_side_tool_usage') and response.server_side_tool_usage:
        tool_invocations = max(tool_invocations, _count_server_side_tool_usage(response.server_side_tool_usage))

    if response and hasattr(response, 'usage') and response.usage:
        usage = {
            'prompt_tokens': getattr(response.usage, 'prompt_tokens', 0) or (response.usage.total_tokens // 2),
            'completion_tokens': getattr(response.usage, 'completion_tokens', 0) or (response.usage.total_tokens // 2),
            'total_tokens': response.usage.total_tokens if hasattr(response.usage, 'total_tokens') else 0,
            'tool_invocations': tool_invocations,
            'num_citations': len(citations) if citations else 0
        }

    return content, usage, citations, response_id
