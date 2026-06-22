"""Message/content helpers mirroring xai_sdk.chat.

Each returns a lightweight tagged tuple so tests can assert on what was sent
(e.g. that an image part was appended for the vision path).
"""


def system(content):
    return ("system", content)


def user(content, *parts):
    return ("user", content, parts)


def assistant(content):
    return ("assistant", content)


def file(file_id):
    return ("file", file_id)


def image(image_url=None, detail=None):
    return ("image", image_url, detail)
