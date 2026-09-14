"""Lectures individuelles des messages du CSE (migration 0074)."""


def creer_schema(conn):
    """Crée le suivi de lecture sans altérer les messages existants."""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS cse_messages_lectures (
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            lu_le TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (message_id, user_id),
            FOREIGN KEY (message_id) REFERENCES cse_messages(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_cse_messages_lectures_user
        ON cse_messages_lectures(user_id)
    ''')
