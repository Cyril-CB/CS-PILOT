"""Convergence des installations et suivi des tentatives de migration."""
from schema_resilience import creer_schema

NOM = 'Résilience et convergence du schéma'
DESCRIPTION = 'Journal des tentatives, contrats, plan comptable et contraintes cohérentes.'


def upgrade(conn):
    creer_schema(conn)


def downgrade(conn):
    raise RuntimeError('Restaurez la sauvegarde préalable avec le code correspondant.')
