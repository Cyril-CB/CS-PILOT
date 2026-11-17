"""Réception de PDF et traitements documentaires de l'assistant."""
NOM = 'Assistant : boîte de réception documentaire'
DESCRIPTION = 'PDF privés, analyses chiffrées et suivi idempotent des créations métier.'


def upgrade(conn):
    from schema_assistant_reception import creer_schema
    creer_schema(conn)


def downgrade(conn):
    raise RuntimeError('Restaurez la sauvegarde préalable pour conserver les documents déposés.')
