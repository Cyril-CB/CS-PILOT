"""
Migration 0010 : Ajout des colonnes heures_reelles et heures_supps
dans la table variables_paie.

- heures_reelles : pour les salaries payes en heures reelles chaque mois
- heures_supps : heures supplementaires exceptionnelles ou fin de contrat
"""

NOM = "Ajout heures reelles et heures supps"
DESCRIPTION = (
    "Ajoute les colonnes heures_reelles et heures_supps "
    "a la table variables_paie."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    # Verifier si les colonnes existent deja
    cols = [row[1] for row in cursor.execute('PRAGMA table_info(variables_paie)').fetchall()]

    if 'heures_reelles' not in cols:
        cursor.execute('ALTER TABLE variables_paie ADD COLUMN heures_reelles REAL')

    if 'heures_supps' not in cols:
        cursor.execute('ALTER TABLE variables_paie ADD COLUMN heures_supps REAL')

    conn.commit()
