"""
Migration 0030 : Ameliorations du module subventions.

- Ajout annee_action, compte_comptable_1_id, compte_comptable_2_id, benevoles_ids sur subventions
- Ajout document_path, document_nom sur subventions_sous_elements
"""

NOM = "Ameliorations subventions"
DESCRIPTION = (
    "Ajoute les colonnes annee_action, compte_comptable_1_id, "
    "compte_comptable_2_id, benevoles_ids a subventions et "
    "document_path, document_nom a subventions_sous_elements."
)


def _column_exists(cursor, table, column):
    """Verifie si une colonne existe dans une table."""
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    if not _column_exists(cursor, 'subventions', 'annee_action'):
        cursor.execute("ALTER TABLE subventions ADD COLUMN annee_action TEXT")

    if not _column_exists(cursor, 'subventions', 'compte_comptable_1_id'):
        cursor.execute("ALTER TABLE subventions ADD COLUMN compte_comptable_1_id INTEGER REFERENCES comptabilite_comptes(id)")

    if not _column_exists(cursor, 'subventions', 'compte_comptable_2_id'):
        cursor.execute("ALTER TABLE subventions ADD COLUMN compte_comptable_2_id INTEGER REFERENCES comptabilite_comptes(id)")

    if not _column_exists(cursor, 'subventions', 'benevoles_ids'):
        cursor.execute("ALTER TABLE subventions ADD COLUMN benevoles_ids TEXT DEFAULT '[]'")

    if not _column_exists(cursor, 'subventions_sous_elements', 'document_path'):
        cursor.execute("ALTER TABLE subventions_sous_elements ADD COLUMN document_path TEXT")

    if not _column_exists(cursor, 'subventions_sous_elements', 'document_nom'):
        cursor.execute("ALTER TABLE subventions_sous_elements ADD COLUMN document_nom TEXT")

    conn.commit()
