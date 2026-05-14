import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import CONVERSATION_RETENTION_HOURS, DB_PATH


logger = logging.getLogger('GrokBot')


def init_conversation_db():
    """Initialize SQLite database for conversation history."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)
        logger.info(f'Created database directory: {db_dir}')

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            message_id INTEGER PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            user_query TEXT NOT NULL,
            bot_response TEXT NOT NULL,
            model_used TEXT NOT NULL,
            xai_response_id TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    ''')

    try:
        cursor.execute('ALTER TABLE conversations ADD COLUMN xai_response_id TEXT')
        logger.info('Added xai_response_id column to conversations table')
    except sqlite3.OperationalError:
        pass

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_message_id ON conversations(message_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_created_at ON conversations(created_at)
    ''')

    conn.commit()
    conn.close()
    logger.info(f'Conversation database initialized at {DB_PATH}')


def store_conversation(message_id: int, channel_id: int, author_id: int,
                       user_query: str, bot_response: str, model_used: str,
                       xai_response_id: str = None):
    """Store conversation in SQLite database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        cursor.execute('''
            INSERT OR REPLACE INTO conversations
            (message_id, channel_id, author_id, user_query, bot_response, model_used, xai_response_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (message_id, channel_id, author_id, user_query, bot_response, model_used, xai_response_id, now_iso))

        conn.commit()
        conn.close()
        logger.debug(f'Stored conversation for message {message_id}' + (f' with xAI response ID {xai_response_id}' if xai_response_id else ''))
    except Exception as e:
        logger.error(f'Error storing conversation: {e}')


def get_conversation(message_id: int) -> Optional[dict]:
    """Retrieve conversation from SQLite database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT author_id, user_query, bot_response, model_used, created_at, xai_response_id
            FROM conversations
            WHERE message_id = ?
        ''', (message_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                'author_id': row[0],
                'user_query': row[1],
                'bot_response': row[2],
                'model_used': row[3],
                'created_at': row[4],
                'xai_response_id': row[5]
            }
        return None
    except Exception as e:
        logger.error(f'Error retrieving conversation: {e}')
        return None


def cleanup_old_conversations():
    """Remove conversations older than CONVERSATION_RETENTION_HOURS."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cutoff_time = (datetime.now(timezone.utc) - timedelta(hours=CONVERSATION_RETENTION_HOURS)).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        cursor.execute('''
            DELETE FROM conversations
            WHERE created_at < ?
        ''', (cutoff_time,))

        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()

        if deleted_count > 0:
            logger.info(f'Cleaned up {deleted_count} old conversations (older than {CONVERSATION_RETENTION_HOURS}h)')
    except Exception as e:
        logger.error(f'Error cleaning up conversations: {e}')


async def periodic_cleanup():
    """Periodically clean up old conversations."""
    while True:
        await asyncio.sleep(6 * 3600)
        cleanup_old_conversations()
