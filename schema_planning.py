"""Évolution idempotente du schéma des plannings théoriques.

Partagée par l'initialisation d'une base neuve et la migration des bases existantes.
Les plannings antérieurs n'ont pas de date de création attestée : NULL est conservé.
"""


def assurer_date_creation_planning(conn):
    """Ajoute uniquement la date de création, sans inventer celle de l'historique."""
    colonnes = {ligne[1] for ligne in conn.execute('PRAGMA table_info(planning_theorique)')}
    if 'created_at' not in colonnes:
        conn.execute('ALTER TABLE planning_theorique ADD COLUMN created_at TEXT')
