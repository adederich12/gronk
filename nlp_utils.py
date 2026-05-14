import logging
import re

import spacy


logger = logging.getLogger('GrokBot')


try:
    nlp_spacy = spacy.load('en_core_web_sm')
except OSError:
    import subprocess
    subprocess.run(['python', '-m', 'spacy', 'download', 'en_core_web_sm'])
    nlp_spacy = spacy.load('en_core_web_sm')


INTENT_PATTERNS = {
    'image_generation': [
        r'\b(generate|create|make|draw|paint|sketch|render|illustrate|visualize)\b.*\b(image|picture|art|artwork|illustration|visual)\b',
        r'\b(image|picture|art|artwork|illustration)\b.*\b(of|for|with|showing)\b',
        r'\bshow me (an? )?(image|picture|art)\b',
        r'\b(grok|bot),?\s*(make|create|generate|draw)\b',
    ],
    'discord_history': [
        r'\b(who|what|how many)\b.*\b(talked|said|mentioned|posted|discussed)\b',
        r'\b(summarize|summary|overview)\b.*\b(chat|discord|server|channel|conversation)\b',
        r'\bin (this|the) (server|channel|discord|chat)\b',
        r'\b(we|our|us)\b.*\b(discuss|talk|mention|chat)\b',
    ],
    'general_query': [
        r'\b(what is|who is|how does|why does|when did|where is)\b',
        r'\b(explain|tell me about|describe)\b',
    ]
}


def detect_intent_pattern(text):
    """
    Lightweight pattern-based intent detection.
    Returns the detected intent or None.
    """
    text_lower = text.lower()
    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return intent
    return None


def advanced_nlp_parse(text):
    """
    Lightweight NLP using spaCy for entity extraction and regex for intent.
    Returns dict with entities, topics, and intent.
    """
    doc = nlp_spacy(text)
    entities = [(ent.text, ent.label_) for ent in doc.ents]
    topics = [chunk.text for chunk in doc.noun_chunks]
    intent = detect_intent_pattern(text)

    return {
        'entities': entities,
        'topics': topics,
        'intent': intent
    }
