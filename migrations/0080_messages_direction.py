"""Communications de la direction, indépendantes des messages du CSE."""
from schema_messages_direction import creer_schema

NOM = 'Messages de la direction aux salariés'
DESCRIPTION = 'Ajoute les messages, archives et lectures individuelles de la direction.'


def upgrade(conn):
    creer_schema(conn)


def downgrade(conn):
    conn.execute('DROP TABLE IF EXISTS messages_direction_lectures')
    conn.execute('DROP TABLE IF EXISTS messages_direction')
