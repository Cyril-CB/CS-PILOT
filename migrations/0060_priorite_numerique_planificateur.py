"""
Migration 0060 : priorité numérique relative du planificateur de tâches.

L'échelle fixe haute/normale/basse s'écrase à l'usage (tout finit en
« haute »). Elle est remplacée par une priorité numérique relative, jamais
affichée, construite par comparaisons par paires à la saisie : la première
tâche vaut 0, chaque nouvelle tâche est située par rapport à la plus urgente
et la moins urgente des tâches en cours (supérieur / égal / inférieur).

On ajoute `priorite_num` (INTEGER, nullable) à `planif_taches` et
`planif_recurrences`. L'existant est repris en préservant l'ordre relatif de
l'ancienne échelle : haute → 1, normale → 0, basse → -1. L'ancienne colonne
`priorite` reste en place (SQLite ne supprime pas les colonnes) et sert de
secours au moteur quand `priorite_num` est NULL.
"""

NOM = "Priorité numérique relative du planificateur"
DESCRIPTION = (
    "Ajoute planif_taches.priorite_num et planif_recurrences.priorite_num "
    "(INTEGER, nullable) : priorité relative construite par comparaisons par "
    "paires. Reprise de l'existant : haute → 1, normale → 0, basse → -1."
)


def upgrade(conn):
    """Applique la migration (idempotente)."""
    import sqlite3
    cursor = conn.cursor()
    for table in ('planif_taches', 'planif_recurrences'):
        try:
            cursor.execute(f"SELECT priorite_num FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN priorite_num INTEGER")

        # Reprise de l'existant en conservant l'ordre relatif des trois niveaux.
        cursor.execute(f'''
            UPDATE {table}
            SET priorite_num = CASE priorite
                WHEN 'haute' THEN 1
                WHEN 'basse' THEN -1
                ELSE 0
            END
            WHERE priorite_num IS NULL
        ''')
    conn.commit()


def downgrade(conn):
    """SQLite ne supporte pas DROP COLUMN simplement : downgrade non destructif
    (la colonne reste, inerte tant que le code ne la lit pas)."""
    pass
