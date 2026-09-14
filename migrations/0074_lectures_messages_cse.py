"""Lecture individuelle des messages du CSE."""
from schema_cse_lectures import creer_schema

NOM = 'Lectures individuelles des messages du CSE'
DESCRIPTION = (
    'Mémorise par utilisateur la lecture de chaque message CSE afin de ne plus '
    'afficher sa bannière après ouverture.'
)


def upgrade(conn):
    creer_schema(conn)


def downgrade(conn):
    conn.execute('DROP TABLE IF EXISTS cse_messages_lectures')
