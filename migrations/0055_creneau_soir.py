"""
Migration 0055 : troisième créneau optionnel « soir ».

Le personnel d'entretien travaille parfois en trois créneaux dans la journée,
notamment en période de vacances. On ajoute un créneau « soir » (début/fin) en
plus de « matin » et « après-midi » :
- sur les heures réelles saisies (`heures_reelles`) ;
- sur le planning théorique hebdomadaire (`planning_theorique`), pour chaque
  jour ouvré (lundi → vendredi).

Les colonnes sont NULLABLES : les plannings et saisies existants restent
inchangés (un créneau soir vide compte pour 0 heure). Côté interface, le créneau
n'est proposé qu'en contexte « vacances » et reste activable ponctuellement.
"""

NOM = "Créneau soir optionnel (entretien / vacances)"
DESCRIPTION = (
    "Ajoute un 3e créneau « soir » (début/fin) aux heures réelles et au planning "
    "théorique (par jour). Colonnes nullables, rétrocompatibles."
)

JOURS = ('lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi')


def _ajouter_colonne(cursor, table, colonne):
    """Ajoute une colonne TEXT si elle n'existe pas déjà (idempotent)."""
    import sqlite3
    try:
        cursor.execute(f"SELECT {colonne} FROM {table} LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {colonne} TEXT")


def upgrade(conn):
    """Applique la migration (idempotente)."""
    cursor = conn.cursor()
    for colonne in ('heure_debut_soir', 'heure_fin_soir'):
        _ajouter_colonne(cursor, 'heures_reelles', colonne)
    for jour in JOURS:
        _ajouter_colonne(cursor, 'planning_theorique', f'{jour}_soir_debut')
        _ajouter_colonne(cursor, 'planning_theorique', f'{jour}_soir_fin')
    conn.commit()


def downgrade(conn):
    """SQLite ne supporte pas DROP COLUMN simplement : downgrade non destructif
    (les colonnes soir restent, inertes)."""
    pass
