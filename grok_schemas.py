from typing import Dict, List

from pydantic import BaseModel, Field


class GrokAnswer(BaseModel):
    answer: str = Field(description="Discord-ready answer text.")
    sources: List[str] = Field(default_factory=list, description="Source URLs or citation strings.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class DiscordHistorySource(BaseModel):
    message_id: str
    channel_id: str
    user_id: str
    excerpt: str
    link: str


class DiscordHistoryAnswer(BaseModel):
    answer: str = Field(description="Answer with inline citations like [#1].")
    sources: Dict[str, DiscordHistorySource] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class PersonaDraft(BaseModel):
    name: str = Field(description="Short memorable persona name.")
    summary: str = Field(description="One-sentence description of the persona.")
    system_prompt: str = Field(description="Complete reusable system prompt for this persona.")
    tags: List[str] = Field(default_factory=list, description="Short lowercase tags.")


def _make_strict_json_schema(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object" and "properties" in schema:
            schema["additionalProperties"] = False
            schema["required"] = list(schema["properties"].keys())
        for value in schema.values():
            _make_strict_json_schema(value)
    elif isinstance(schema, list):
        for value in schema:
            _make_strict_json_schema(value)
    return schema


def json_schema_response_format(model: type[BaseModel], name: str) -> dict:
    if hasattr(model, "model_json_schema"):
        schema = model.model_json_schema()
    else:
        schema = model.schema()
    schema = _make_strict_json_schema(schema)

    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "schema": schema,
            "strict": True,
        },
    }
