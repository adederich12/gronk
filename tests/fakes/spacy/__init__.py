"""Minimal synthetic stand-in for spaCy.

Returns an analyzer that produces no entities/noun-chunks, which is enough for
the routing code under test (it falls back to regex patterns).
"""


class _Doc:
    def __init__(self, text):
        self.text = text
        self.ents = []
        self.noun_chunks = []


class _Nlp:
    def __call__(self, text):
        return _Doc(text)


def load(name):
    return _Nlp()
