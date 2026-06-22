"""Synthetic stand-in for the openai package (OpenAI-compatible client).

The bot constructs ``OpenAI(api_key=..., base_url=...)`` at import time and, in
the pre-fix code, used it for the vision path. Tests drive responses via the
module-level ``control`` object.
"""


class _Control:
    def __init__(self):
        self.reset()

    def reset(self):
        self.content = '{"answer": "synthetic vision answer", "sources": [], "confidence": 1.0}'
        self.usage = {"prompt_tokens": 200, "completion_tokens": 50, "total_tokens": 250}
        self.created = []  # recorded create(**kwargs) calls


control = _Control()


class _Message:
    def __init__(self, content):
        self.content = content
        self.tool_calls = None


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Usage:
    def __init__(self, usage):
        self.prompt_tokens = usage.get("prompt_tokens", 0)
        self.completion_tokens = usage.get("completion_tokens", 0)
        self.total_tokens = usage.get("total_tokens", 0)
        self.prompt_tokens_details = None


class _Completion:
    def __init__(self, model):
        self.model = model
        self.choices = [_Choice(control.content)]
        self.usage = _Usage(control.usage)


class _Completions:
    def create(self, **kwargs):
        control.created.append(kwargs)
        return _Completion(kwargs.get("model", "unknown"))


class _Chat:
    def __init__(self):
        self.completions = _Completions()


class OpenAI:
    def __init__(self, *args, **kwargs):
        self.chat = _Chat()
