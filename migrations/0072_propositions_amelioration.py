"""Demandes de développement explicites, pièces et suivi de transmission."""
from schema_propositions import creer_schema

NOM = 'Propositions d’amélioration'
DESCRIPTION = 'Conservation des demandes, pièces jointes et tentatives d’envoi par email.'


def upgrade(conn):
    creer_schema(conn)


def downgrade(conn):
    raise RuntimeError('Restaurez la sauvegarde préalable pour conserver les propositions et leurs pièces.')
