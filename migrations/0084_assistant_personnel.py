"""Conversations et mémoire privées de l'assistant, sans reprise de l'ancien chatbot."""
NOM = 'Assistant personnel : conversation et mémoire'
DESCRIPTION = 'Stockage chiffré individuel, quotas et protection des requêtes concurrentes.'


def upgrade(conn):
    from schema_assistant import creer_schema
    creer_schema(conn)


def downgrade(conn):
    raise RuntimeError('Restaurez la sauvegarde préalable pour conserver les conversations personnelles.')
