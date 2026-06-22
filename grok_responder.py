import json
import logging
import re

import discord
from xai_sdk.chat import file as xai_file
from xai_sdk.chat import system as xai_system
from xai_sdk.chat import user as xai_user

from config import (
    ENABLE_WEB_SEARCH,
    GROK_DOCUMENT_MODEL,
    GROK_ANALYSIS_REASONING_EFFORT,
    GROK_REASONING_EFFORT,
    GROK_TEXT_CACHED_COST,
    GROK_TEXT_INPUT_COST,
    GROK_TEXT_MODEL,
    GROK_TEXT_OUTPUT_COST,
    GROK_TOOL_COST,
    GROK_VISION_INPUT_COST,
    GROK_VISION_MODEL,
    GROK_VISION_OUTPUT_COST,
)
from conversation_store import store_conversation
from document_utils import delete_grok_files, upload_documents_to_grok
from grok_client import (
    build_cache_conversation_id,
    client,
    normalize_openai_reasoning_effort,
    normalize_sdk_reasoning_effort,
    sdk_chat_request,
)
from grok_schemas import GrokAnswer, json_schema_response_format
from persona_manager import get_active_persona


logger = logging.getLogger('GrokBot')


class MockMessage:
    def __init__(self, content):
        self.content = content


class MockChoice:
    def __init__(self, message):
        self.message = message


class DocumentMockUsage:
    def __init__(self, usage_data):
        self.prompt_tokens = usage_data.total_tokens // 2 if usage_data else 0
        self.completion_tokens = usage_data.total_tokens // 2 if usage_data else 0
        self.total_tokens = usage_data.total_tokens if usage_data else 0
        self.prompt_tokens_details = None
        self.num_sources_used = 0


class SdkMockUsage:
    def __init__(self, usage_dict):
        self.prompt_tokens = usage_dict.get('prompt_tokens', 0)
        self.completion_tokens = usage_dict.get('completion_tokens', 0)
        self.total_tokens = usage_dict.get('total_tokens', 0)
        self.prompt_tokens_details = None
        self.num_sources_used = usage_dict.get('num_sources_used', 0)
        self.tool_invocations = usage_dict.get('tool_invocations', 0)


class MockCompletion:
    def __init__(self, content, model_name, usage=None):
        self.model = model_name
        self.usage = usage
        self.choices = [MockChoice(MockMessage(content))]


def _usage_text(completion):
    if not hasattr(completion, 'usage') or not completion.usage:
        return ""

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

    tool_invocations = getattr(completion.usage, 'tool_invocations', 0)
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
    return f"{cost_str} • {completion.usage.prompt_tokens} in / {completion.usage.completion_tokens} out"


def _extract_answer_and_sources(response):
    json_response = response.strip()
    json_match = re.match(r'^```(?:json)?\s*\n?([\s\S]*?)\n?```$', json_response, re.DOTALL)
    if json_match:
        json_response = json_match.group(1).strip()

    try:
        grok_json = json.loads(json_response)
    except json.JSONDecodeError:
        logger.warning('Grok returned non-JSON content; using raw response text')
        return response.strip(), []

    return grok_json.get("answer", "(No answer)"), grok_json.get("sources", [])


def _add_sources(embed, sources):
    if not sources:
        return

    formatted_sources = []
    for src in sources:
        if re.match(r'^(post:\d+|X User Result \d+|x_\w+|web_search|code_execution)', src, re.IGNORECASE):
            continue
        match = re.match(r"\[.*?\]\((https?://[^)]+)\)", src)
        if match:
            formatted_sources.append(match.group(1))
        elif re.match(r"https?://", src):
            formatted_sources.append(src)
        else:
            url_match = re.search(r"(https?://\S+)", src)
            if url_match:
                formatted_sources.append(url_match.group(1))

    if formatted_sources:
        embed.add_field(name="Sources", value="\n".join(formatted_sources), inline=False)


def _apply_persona(system_prompt, persona):
    if not persona:
        return system_prompt
    return (
        f"{system_prompt}\n\n"
        f"Active persona for this Discord channel: {persona['name']}.\n"
        f"Persona summary: {persona.get('summary', '')}\n"
        f"Persona system prompt:\n{persona['system_prompt']}"
    )


async def handle_grok_query(message, bot, prompt, image_urls, document_attachments,
                            conversation_messages, previous_xai_response_id):
    """Query Grok, send the Discord response, and store conversation metadata."""
    try:
        async with message.channel.typing():
            xai_client, grok_file_ids, failed_uploads = await upload_documents_to_grok(document_attachments)
            if failed_uploads and not grok_file_ids:
                await message.reply(f"Failed to upload document(s): {', '.join(failed_uploads)}\n\nSupported formats: PDF, TXT, MD, CSV, JSON, and code files.")
                return
            elif failed_uploads:
                logger.warning(f'Some documents failed to upload: {failed_uploads}, proceeding with {len(grok_file_ids)} successful uploads')

            if image_urls:
                model = GROK_VISION_MODEL
            elif grok_file_ids:
                model = GROK_DOCUMENT_MODEL
            else:
                model = GROK_TEXT_MODEL
            logger.info(f'Using model: {model} (images: {len(image_urls)}, docs: {len(grok_file_ids)})')

            json_instructions = (
                "You must ALWAYS reply in the following strict JSON format, with no extra commentary or markdown. "
                "Format: {\"answer\": string, \"sources\": [string], \"confidence\": float}. "
                "If you cite Discord messages, include a 'sources' array with each source as a string. "
                "If you don't know, use an empty array for sources and 0.0 for confidence."
            )
            openai_system_prompt = (
                "You are Grok, a witty and uncensored AI assistant. Be direct, honest, and don't hold back. "
                "You can be sarcastic, edgy, and politically incorrect when appropriate. Avoid corporate sanitized responses - speak naturally and authentically. "
                "If something is stupid, you can say it's stupid. Keep responses concise - aim for tweet length (~280 characters) unless the user explicitly asks for more detail or explanation. "
                + json_instructions
            )
            sdk_system_prompt = (
                "You are Grok, a witty and uncensored AI assistant. Be direct, honest, and don't hold back. "
                "You can be sarcastic, edgy, and politically incorrect when appropriate. Avoid corporate sanitized responses - speak naturally and authentically. "
                "If something is stupid, you can say it's stupid. Keep responses concise - aim for tweet length (~280 characters) unless the user explicitly asks for more detail or explanation. "
                "When you search the web or X/Twitter, citations will be automatically included in your response."
            )

            current_xai_response_id = None
            conversation_id = build_cache_conversation_id(message.channel.id, message.author.id)
            active_persona = get_active_persona(message.channel.id)
            if active_persona:
                logger.info(f"Using active persona for channel {message.channel.id}: {active_persona['name']}")

            if image_urls:
                openai_system_prompt = _apply_persona(openai_system_prompt, active_persona)
                content = [{"type": "text", "text": prompt or "What's in this image?"}]
                for url in image_urls:
                    content.append({"type": "image_url", "image_url": {"url": url}})
                logger.info('Sending request to Grok with images...')
                completion = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": openai_system_prompt},
                        {"role": "user", "content": content}
                    ],
                    response_format=json_schema_response_format(GrokAnswer, "grok_answer"),
                    reasoning_effort=normalize_openai_reasoning_effort(GROK_ANALYSIS_REASONING_EFFORT),
                    extra_headers={"x-grok-conv-id": conversation_id} if conversation_id else None,
                )
            elif grok_file_ids:
                doc_system_prompt = (
                    "You are Grok, a witty and uncensored AI assistant analyzing an attached document. "
                    "You have access to the document(s) the user has uploaded. Read and analyze the document content to answer the user's question. "
                    "Be direct, honest, and thorough in your analysis. "
                    + json_instructions
                )
                doc_system_prompt = _apply_persona(doc_system_prompt, active_persona)
                if prompt and prompt.lower().strip() in ["what is this?", "what is this", "what's this?", "what's this", "whats this", "analyze this", "read this", "summarize this", "summarize"]:
                    user_prompt = f"Please analyze the attached document and answer: {prompt}"
                elif prompt:
                    user_prompt = f"Based on the attached document: {prompt}"
                else:
                    user_prompt = "Please analyze the attached document and provide a comprehensive summary of its key points, main topics, and important details."

                logger.info(f'Sending document request via xAI SDK with {len(grok_file_ids)} files')
                chat = xai_client.chat.create(
                    model=model,
                    messages=[xai_system(doc_system_prompt)],
                    response_format=GrokAnswer,
                    reasoning_effort=normalize_sdk_reasoning_effort(GROK_ANALYSIS_REASONING_EFFORT),
                    conversation_id=conversation_id,
                    store_messages=True,
                )
                chat.append(xai_user(user_prompt, *[xai_file(fid) for fid in grok_file_ids]))
                sdk_response, parsed_response = await chat.parse(GrokAnswer)
                if sdk_response and hasattr(sdk_response, 'id'):
                    current_xai_response_id = sdk_response.id
                    logger.info(f'Document analysis response ID: {current_xai_response_id}')
                completion = MockCompletion(
                    parsed_response.model_dump_json() if hasattr(parsed_response, 'model_dump_json') else parsed_response.json(),
                    model,
                    DocumentMockUsage(sdk_response.usage) if sdk_response and hasattr(sdk_response, 'usage') else None
                )
                await delete_grok_files(xai_client, grok_file_ids)
            else:
                sdk_system_prompt = _apply_persona(sdk_system_prompt, active_persona)
                if previous_xai_response_id:
                    logger.info(f'Continuing conversation with xAI response ID: {previous_xai_response_id} (not sending local history - using server-side memory)')
                else:
                    logger.info(f'Sending text-only request to Grok via SDK (history: {len(conversation_messages)})')

                response, sdk_usage, _, new_response_id = await sdk_chat_request(
                    model=model,
                    system_prompt=sdk_system_prompt,
                    user_prompt=prompt,
                    conversation_history=conversation_messages if not previous_xai_response_id else None,
                    include_search=ENABLE_WEB_SEARCH,
                    previous_response_id=previous_xai_response_id,
                    response_format=GrokAnswer,
                    reasoning_effort=GROK_REASONING_EFFORT,
                    conversation_id=conversation_id,
                )
                current_xai_response_id = new_response_id
                completion = MockCompletion(response, model, SdkMockUsage(sdk_usage) if sdk_usage else None)

            response = completion.choices[0].message.content
            logger.info(f'Received response from Grok ({len(response)} characters)')

            usage_text = _usage_text(completion)
            try:
                answer, sources = _extract_answer_and_sources(response)
            except Exception as e:
                logger.error(f'Failed to parse Grok JSON: {e}\nRaw response: {response}')
                await message.reply("❌ Grok did not return valid JSON. Please try again.")
                return

            embed = discord.Embed(
                description=answer,
                color=discord.Color.blue(),
                timestamp=message.created_at
            )
            embed.set_author(
                name="Grok Response",
                icon_url="https://pbs.twimg.com/profile_images/1683899100922511378/5lY42eHs_400x400.jpg"
            )
            _add_sources(embed, sources)

            footer_text = f"Requested by {message.author.display_name}"
            if usage_text:
                footer_text += f" • {usage_text}"
            if active_persona:
                footer_text += f" • Persona: {active_persona['name']}"
            embed.set_footer(text=footer_text, icon_url=message.author.avatar.url if message.author.avatar else None)

            bot_message = await message.reply(embed=embed)
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
            logger.info('Response sent successfully')
    except Exception as e:
        logger.error(f'Error querying Grok: {e}', exc_info=True)

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
