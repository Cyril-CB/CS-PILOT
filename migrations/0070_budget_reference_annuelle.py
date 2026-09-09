"""Paramètres explicites du budget, sans recalcul des anciennes saisies."""
from budget_calculs import creer_schema

NOM = 'Référence annuelle et modes des comptes du budget'
DESCRIPTION = 'Ajoute les arrêtés explicites et les modes par compte ; conserve toutes les saisies existantes.'


def upgrade(conn):
    creer_schema(conn)


def downgrade(conn):
    raise RuntimeError('Restaurez une sauvegarde cohérente pour revenir en arrière sans perdre les paramètres du budget.')
