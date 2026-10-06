"""Lot 2 : création additive, aucune conversion de budget existant."""
from schema_budget_suivi import creer_schema

NOM = 'Gel annuel et suivi des écarts'
DESCRIPTION = 'Références immuables, ajustements versionnés et instantanés PDF, sans synchronisation.'


def upgrade(conn):
    creer_schema(conn)


def downgrade(conn):
    raise RuntimeError('Restaurer une sauvegarde cohérente : les archives budgétaires doivent être préservées.')
