import json
import logging
import os
import re
from datetime import datetime, timezone

import discord
from discord import Interaction, ui

from config import (
    GROK_ANALYSIS_REASONING_EFFORT,
    GROK_TEXT_CACHED_COST,
    GROK_TEXT_INPUT_COST,
    GROK_TEXT_MODEL,
    GROK_TEXT_OUTPUT_COST,
    GROK_TOOL_COST,
    PERSONA_STORE_PATH,
)
from grok_client import build_cache_conversation_id, sdk_chat_request
from grok_schemas import PersonaDraft


logger = logging.getLogger('GrokBot')

PERSONA_CREATE_PATTERNS = [
    r'\b(create|generate|make|build|write)\b.*\b(persona|personality|system prompt|character)\b',
    r'\bnew\b.*\b(persona|personality|system prompt|character)\b',
]
PERSONA_LIST_PATTERNS = [
    r'\b(list|show|choose|select|switch|change)\b.*\b(personas?|personalities|system prompts?)\b',
    r'\bpersonas?\b\s*$',
]
PERSONA_CLEAR_PATTERNS = [
    r'\b(clear|disable|reset|remove)\b.*\b(persona|personality)\b',
]
PERSONA_CLONE_PATTERNS = [
    r'\b(clone|copy|duplicate)\b.*\b(persona|personality|system prompt|default)\b',
]
PERSONA_REFINE_PATTERNS = [
    r'\b(refine|revise|edit|update|tweak|adjust|improve)\b.*\b(persona|personality|system prompt)\b',
]

DEFAULT_PERSONA_ID = "default"
DEFAULT_PERSONA = {
    "id": DEFAULT_PERSONA_ID,
    "name": "Default Grok",
    "summary": "The built-in default Grok behavior. This persona is protected and cannot be edited.",
    "system_prompt": (
        "You are Grok, a witty and uncensored AI assistant. Be direct, honest, and don't hold back. "
        "You can be sarcastic, edgy, and politically incorrect when appropriate. Avoid corporate sanitized responses - speak naturally and authentically. "
        "If something is stupid, you can say it's stupid. Keep responses concise unless the user explicitly asks for more detail or explanation."
    ),
    "tags": ["default", "protected"],
    "protected": True,
}


def is_persona_request(prompt: str) -> bool:
    text = prompt.lower().strip()
    patterns = (
        PERSONA_CREATE_PATTERNS
        + PERSONA_LIST_PATTERNS
        + PERSONA_CLEAR_PATTERNS
        + PERSONA_CLONE_PATTERNS
        + PERSONA_REFINE_PATTERNS
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _ensure_store_dir():
    store_dir = os.path.dirname(PERSONA_STORE_PATH)
    if store_dir and not os.path.exists(store_dir):
        os.makedirs(store_dir, exist_ok=True)


def _load_store():
    _ensure_store_dir()
    if not os.path.exists(PERSONA_STORE_PATH):
        return {"personas": {}, "active_by_channel": {}}

    try:
        with open(PERSONA_STORE_PATH, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        data.setdefault("personas", {})
        data.setdefault("active_by_channel", {})
        return data
    except Exception as e:
        logger.error(f'Error loading persona store: {e}', exc_info=True)
        return {"personas": {}, "active_by_channel": {}}


def _save_store(data):
    _ensure_store_dir()
    tmp_path = f"{PERSONA_STORE_PATH}.tmp"
    with open(tmp_path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write('\n')
    os.replace(tmp_path, PERSONA_STORE_PATH)


def _slugify(name: str):
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return slug[:48] or 'persona'


def _unique_slug(data, name: str):
    base = _slugify(name)
    slug = base
    idx = 2
    while slug in data["personas"]:
        slug = f"{base}-{idx}"
        idx += 1
    return slug


def list_personas():
    data = _load_store()
    personas = [
        {"id": persona_id, **persona}
        for persona_id, persona in sorted(data["personas"].items(), key=lambda item: item[1].get("name", item[0]).lower())
    ]
    return [DEFAULT_PERSONA.copy()] + personas


def get_persona(persona_id):
    if not persona_id or persona_id == DEFAULT_PERSONA_ID:
        return DEFAULT_PERSONA.copy()

    data = _load_store()
    persona = data["personas"].get(persona_id)
    if not persona:
        return None
    return {"id": persona_id, **persona}


def get_active_persona(channel_id):
    data = _load_store()
    persona_id = data["active_by_channel"].get(str(channel_id))
    if not persona_id:
        return None
    return get_persona(persona_id)


def set_active_persona(channel_id, persona_id):
    data = _load_store()
    if persona_id == DEFAULT_PERSONA_ID:
        data["active_by_channel"].pop(str(channel_id), None)
        _save_store(data)
        return DEFAULT_PERSONA.copy()
    if persona_id not in data["personas"]:
        return None
    data["active_by_channel"][str(channel_id)] = persona_id
    _save_store(data)
    return {"id": persona_id, **data["personas"][persona_id]}


def clear_active_persona(channel_id):
    data = _load_store()
    data["active_by_channel"].pop(str(channel_id), None)
    _save_store(data)


def save_persona(draft: PersonaDraft, created_by, source_prompt: str):
    data = _load_store()
    persona_id = _unique_slug(data, draft.name)
    persona = {
        "name": draft.name.strip()[:80],
        "summary": draft.summary.strip()[:300],
        "system_prompt": draft.system_prompt.strip(),
        "tags": [tag.strip().lower()[:32] for tag in draft.tags[:8] if tag.strip()],
        "created_by": str(created_by),
        "source_prompt": source_prompt.strip(),
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
    }
    data["personas"][persona_id] = persona
    _save_store(data)
    return {"id": persona_id, **persona}


def update_persona(persona_id, draft: PersonaDraft, updated_by, refinement_prompt: str):
    if persona_id == DEFAULT_PERSONA_ID:
        return None

    data = _load_store()
    if persona_id not in data["personas"]:
        return None

    existing = data["personas"][persona_id]
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    history = existing.setdefault("history", [])
    history.append({
        "summary": existing.get("summary", ""),
        "system_prompt": existing.get("system_prompt", ""),
        "updated_at": now_iso,
        "updated_by": str(updated_by),
        "refinement_prompt": refinement_prompt.strip(),
    })
    del history[:-5]

    existing.update({
        "name": draft.name.strip()[:80],
        "summary": draft.summary.strip()[:300],
        "system_prompt": draft.system_prompt.strip(),
        "tags": [tag.strip().lower()[:32] for tag in draft.tags[:8] if tag.strip()],
        "updated_by": str(updated_by),
        "updated_at": now_iso,
    })
    _save_store(data)
    return {"id": persona_id, **existing}


def clone_persona(source_persona_id, created_by, requested_name=None):
    source = get_persona(source_persona_id)
    if not source:
        return None

    data = _load_store()
    clone_name = requested_name or f"{source['name']} Copy"
    persona_id = _unique_slug(data, clone_name)
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    persona = {
        "name": clone_name.strip()[:80],
        "summary": source.get("summary", ""),
        "system_prompt": source.get("system_prompt", ""),
        "tags": [tag for tag in source.get("tags", []) if tag != "protected"][:8],
        "created_by": str(created_by),
        "source_prompt": f"Cloned from {source_persona_id}",
        "parent_id": source_persona_id,
        "created_at": now_iso,
    }
    data["personas"][persona_id] = persona
    _save_store(data)
    return {"id": persona_id, **persona}


def _usage_text(usage):
    if not usage:
        return ""

    prompt_tokens = usage.get('prompt_tokens', 0)
    completion_tokens = usage.get('completion_tokens', 0)
    cached_tokens = usage.get('cached_tokens', 0)
    tool_invocations = usage.get('tool_invocations', 0)
    uncached_tokens = max(prompt_tokens - cached_tokens, 0)

    input_cost = (
        (uncached_tokens / 1_000_000) * GROK_TEXT_INPUT_COST
        + (cached_tokens / 1_000_000) * GROK_TEXT_CACHED_COST
    )
    output_cost = (completion_tokens / 1_000_000) * GROK_TEXT_OUTPUT_COST
    tool_cost = (tool_invocations / 1000) * GROK_TOOL_COST if tool_invocations else 0
    total_cost = input_cost + output_cost + tool_cost

    text = f"${total_cost:.6f} est. ({prompt_tokens} in / {completion_tokens} out)"
    if tool_invocations:
        text += f" + {tool_invocations} tools"
    return text


class PersonaSelect(ui.Select):
    def __init__(self, personas, current_id=None):
        options = []
        for persona in personas[:25]:
            options.append(discord.SelectOption(
                label=persona["name"][:100],
                value=persona["id"],
                description=persona.get("summary", "")[:100] or persona["id"],
                default=persona["id"] == current_id,
            ))
        super().__init__(placeholder="Select an active persona for this channel", options=options)

    async def callback(self, interaction: Interaction):
        persona = set_active_persona(interaction.channel_id, self.values[0])
        if not persona:
            await interaction.response.send_message("That persona no longer exists.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Selected persona for this channel: **{persona['name']}**",
            ephemeral=False,
        )


class PersonaSelectView(ui.View):
    def __init__(self, channel_id):
        super().__init__(timeout=300)
        personas = list_personas()
        current = get_active_persona(channel_id)
        if personas:
            self.add_item(PersonaSelect(personas, current["id"] if current else None))


def _persona_embed(persona, title="Persona Saved", usage_text=None):
    embed = discord.Embed(
        title=title,
        description=persona["summary"],
        color=discord.Color.green(),
    )
    embed.add_field(name="Name", value=persona["name"], inline=True)
    embed.add_field(name="ID", value=f"`{persona['id']}`", inline=True)
    if persona.get("tags"):
        embed.add_field(name="Tags", value=", ".join(persona["tags"]), inline=False)
    if persona.get("protected"):
        embed.add_field(name="Protected", value="Yes. Clone this persona before editing it.", inline=False)
    prompt_preview = persona["system_prompt"][:900]
    if len(persona["system_prompt"]) > 900:
        prompt_preview += "..."
    embed.add_field(name="System Prompt", value=prompt_preview, inline=False)
    if usage_text:
        embed.set_footer(text=f"Estimated Grok cost: {usage_text}")
    return embed


async def _generate_persona(message, prompt):
    system_prompt = (
        "You create reusable Discord bot personas. Produce a strong system prompt that can be used as an active assistant persona. "
        "The system prompt should define voice, behavior, boundaries, and response style. Keep it useful, non-gimmicky, and concise enough to reuse."
    )
    user_prompt = f"Create a new persona from this request:\n{prompt}"

    response, usage, _, _ = await sdk_chat_request(
        model=GROK_TEXT_MODEL,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        include_search=False,
        response_format=PersonaDraft,
        reasoning_effort=GROK_ANALYSIS_REASONING_EFFORT,
        conversation_id=build_cache_conversation_id('persona', message.channel.id, message.author.id),
    )
    draft = PersonaDraft.model_validate_json(response)
    return save_persona(draft, message.author.id, prompt), _usage_text(usage)


async def _refine_persona_with_grok(message, persona, prompt):
    system_prompt = (
        "You refine reusable Discord bot personas. Preserve what works, apply the user's requested changes, "
        "and return a complete improved persona with a full system prompt."
    )
    user_prompt = (
        f"Current persona name: {persona['name']}\n"
        f"Current summary: {persona.get('summary', '')}\n"
        f"Current tags: {', '.join(persona.get('tags', []))}\n"
        f"Current system prompt:\n{persona['system_prompt']}\n\n"
        f"User refinement request:\n{prompt}"
    )

    response, usage, _, _ = await sdk_chat_request(
        model=GROK_TEXT_MODEL,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        include_search=False,
        response_format=PersonaDraft,
        reasoning_effort=GROK_ANALYSIS_REASONING_EFFORT,
        conversation_id=build_cache_conversation_id('persona-refine', message.channel.id, message.author.id),
    )
    return PersonaDraft.model_validate_json(response), _usage_text(usage)


def _extract_persona_id(text):
    match = re.search(r'\bpersona\s+`?([a-z0-9][a-z0-9-]{1,80}|default)`?', text.lower())
    if match:
        return match.group(1)
    if "default" in text.lower():
        return DEFAULT_PERSONA_ID
    return None


def _extract_clone_name(prompt):
    match = re.search(r'\bas\s+["“]?([^"”]+)["”]?\s*$', prompt, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


async def handle_persona_request(message, prompt: str):
    text = prompt.lower().strip()

    if any(re.search(pattern, text) for pattern in PERSONA_CLEAR_PATTERNS):
        clear_active_persona(message.channel.id)
        await message.reply("Cleared the active persona for this channel.")
        return

    if any(re.search(pattern, text) for pattern in PERSONA_CLONE_PATTERNS):
        source_id = _extract_persona_id(text)
        active = get_active_persona(message.channel.id)
        if not source_id:
            source_id = active["id"] if active else DEFAULT_PERSONA_ID
        persona = clone_persona(source_id, message.author.id, _extract_clone_name(prompt))
        if not persona:
            await message.reply("I couldn't find that persona to clone.")
            return
        set_active_persona(message.channel.id, persona["id"])
        await message.reply(
            embed=_persona_embed(persona, title="Persona Cloned and Selected"),
            view=PersonaSelectView(message.channel.id),
        )
        return

    if any(re.search(pattern, text) for pattern in PERSONA_REFINE_PATTERNS):
        target_id = _extract_persona_id(text)
        active = get_active_persona(message.channel.id)
        persona = get_persona(target_id) if target_id else active
        if not persona:
            await message.reply("No active persona to refine. Create or select a persona first.")
            return

        cloned_from_default = False
        if persona["id"] == DEFAULT_PERSONA_ID or persona.get("protected"):
            persona = clone_persona(persona["id"], message.author.id)
            cloned_from_default = True

        async with message.channel.typing():
            draft, usage_text = await _refine_persona_with_grok(message, persona, prompt)
            persona = update_persona(persona["id"], draft, message.author.id, prompt)
            set_active_persona(message.channel.id, persona["id"])

        title = "Persona Refined and Selected"
        if cloned_from_default:
            title = "Default Cloned, Refined, and Selected"
        await message.reply(
            embed=_persona_embed(persona, title=title, usage_text=usage_text),
            view=PersonaSelectView(message.channel.id),
        )
        return

    if any(re.search(pattern, text) for pattern in PERSONA_CREATE_PATTERNS):
        async with message.channel.typing():
            persona, usage_text = await _generate_persona(message, prompt)
            set_active_persona(message.channel.id, persona["id"])
        await message.reply(
            embed=_persona_embed(persona, title="Persona Saved and Selected", usage_text=usage_text),
            view=PersonaSelectView(message.channel.id),
        )
        return

    personas = list_personas()
    if not personas:
        await message.reply("No personas have been created yet. Ask me to create a persona first.")
        return

    current = get_active_persona(message.channel.id)
    description = "Choose a persona for this channel."
    if current:
        description += f"\nCurrent persona: **{current['name']}**"
    embed = discord.Embed(
        title="Personas",
        description=description,
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Available",
        value="\n".join(f"- **{p['name']}** (`{p['id']}`): {p.get('summary', '')}" for p in personas[:10]),
        inline=False,
    )
    await message.reply(embed=embed, view=PersonaSelectView(message.channel.id))
