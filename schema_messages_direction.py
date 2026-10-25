"""Messages de la direction et lectures individuelles (migration 0080)."""


def creer_schema(conn):
    """Schéma partagé par les installations neuves et les mises à niveau."""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS messages_direction (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titre TEXT,
            contenu TEXT NOT NULL,
            date_validite TEXT NOT NULL,
            statut TEXT NOT NULL DEFAULT 'actif' CHECK (statut IN ('actif', 'archive')),
            cree_par INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            archive_le TEXT,
            FOREIGN KEY (cree_par) REFERENCES users(id)
        )
    ''')
    conn.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_direction_actif
        ON messages_direction(statut) WHERE statut = 'actif'
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS messages_direction_lectures (
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            lu_le TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (message_id, user_id),
            FOREIGN KEY (message_id) REFERENCES messages_direction(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_messages_direction_lectures_user
        ON messages_direction_lectures(user_id)
    ''')
