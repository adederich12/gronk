import logging
import re

import discord


logger = logging.getLogger('GrokBot')


def convert_usernames_to_mentions(text: str, guild: discord.Guild) -> str:
    """
    Convert Discord usernames in text to proper mentions.
    Handles patterns like: username, @username, "username".
    """
    if not guild:
        return text

    username_map = {}
    for member in guild.members:
        username_map[member.name.lower()] = member
        username_map[member.display_name.lower()] = member
        if '#' in member.name:
            base_name = member.name.split('#')[0].lower()
            username_map[base_name] = member

    patterns_to_try = [
        (r'(?<!<)@([a-zA-Z0-9_]{2,32})(?!>)', lambda m: f"<@{username_map[m.group(1).lower()].id}>" if m.group(1).lower() in username_map else m.group(0)),
        (r'"([a-zA-Z0-9_]{2,32})"', lambda m: f"<@{username_map[m.group(1).lower()].id}>" if m.group(1).lower() in username_map else m.group(0)),
        (r'(?<=\s)([A-Z][a-zA-Z0-9_]{1,31})(?=[\s,.\'])', lambda m: f"<@{username_map[m.group(1).lower()].id}>" if m.group(1).lower() in username_map else m.group(0)),
    ]

    result = text
    for pattern, replacement in patterns_to_try:
        try:
            result = re.sub(pattern, replacement, result)
        except Exception as e:
            logger.warning(f'Error applying username pattern {pattern}: {e}')
            continue

    return result
