"""Synthetic stand-in for the official xai_sdk package.

Only the surface area the bot actually uses is implemented. Tests drive the
canned responses via the module-level ``control`` object, and inspect what the
bot sent via ``control.created`` / ``control.files``.
"""


class _Control:
    """Programmable state shared across a single test."""

    def __init__(self):
        self.reset()

    def reset(self):
        # Canned response fields returned by sample()/parse().
        self.response_id = "resp_test_1"
        self.content = '{"answer": "synthetic answer", "sources": [], "confidence": 1.0}'
        self.usage = {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140}
        # Payload used to build the parsed pydantic object in parse().
        self.parsed_payload = {"answer": "synthetic answer", "sources": [], "confidence": 1.0}
        self.citations = []
        self.tool_calls = None
        self.server_side_tool_usage = None
        # Recorded activity for assertions.
        self.created = []          # list of chat.create(**kwargs) dicts
        self.appended = []         # list of appended message tuples
        self.files_uploaded = []   # local paths uploaded
        self.files_deleted = []    # file ids deleted


control = _Control()


class _FakeUsage:
    def __init__(self, usage):
        self.prompt_tokens = usage.get("prompt_tokens", 0)
        self.completion_tokens = usage.get("completion_tokens", 0)
        self.total_tokens = usage.get("total_tokens", 0)


class _FakeResponse:
    def __init__(self):
        self.id = control.response_id
        self.content = control.content
        self.usage = _FakeUsage(control.usage)
        self.citations = list(control.citations)
        self.tool_calls = control.tool_calls
        self.server_side_tool_usage = control.server_side_tool_usage


class _FakeChat:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        control.created.append(kwargs)

    def append(self, message):
        control.appended.append(message)

    async def sample(self):
        return _FakeResponse()

    async def parse(self, response_format):
        parsed = response_format(**control.parsed_payload)
        return _FakeResponse(), parsed


class _ChatNamespace:
    def create(self, **kwargs):
        return _FakeChat(**kwargs)


class _UploadedFile:
    def __init__(self, file_id):
        self.id = file_id


class _FilesNamespace:
    async def upload(self, path):
        control.files_uploaded.append(path)
        return _UploadedFile(f"file_test_{len(control.files_uploaded)}")

    async def delete(self, file_id):
        control.files_deleted.append(file_id)


class AsyncClient:
    def __init__(self, *args, **kwargs):
        self.chat = _ChatNamespace()
        self.files = _FilesNamespace()


# The real SDK also exposes a sync Client; provide it for completeness.
Client = AsyncClient
