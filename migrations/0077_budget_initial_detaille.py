"""Construction explicite de l'initial, sans reprise des budgets existants."""
from schema_budget_initial import creer_schema

NOM = 'Budget initial annuel détaillé'
DESCRIPTION = 'Ajoute hypothèses, lignes identifiées et traces de report sans réécrire les saisies.'


def upgrade(conn):
    creer_schema(conn)


def downgrade(conn):
    raise RuntimeError('Retour arrière : restaurer une sauvegarde cohérente pour conserver les hypothèses du budget initial.')
