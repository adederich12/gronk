"""Tool helpers mirroring xai_sdk.tools."""


def web_search(*args, **kwargs):
    return ("tool", "web_search")


def x_search(*args, **kwargs):
    return ("tool", "x_search")


def code_execution(*args, **kwargs):
    return ("tool", "code_execution")
