"""
Migration 0007 : Ajout des compteurs de conges pour les salaries.

Ajoute les colonnes de suivi des conges payes et conventionnels
directement dans la table users :
- cp_acquis : conges payes en cours d'acquisition (periode mai-mai)
- cp_a_prendre : solde de conges payes disponibles
- cp_pris : cumul de jours pris
- cc_solde : solde de conges conventionnels disponibles
- date_entree : date d'entree du salarie (pour prorata premier mois)
"""

NOM = "Ajout compteurs conges salaries"
DESCRIPTION = (
    "Ajoute cp_acquis, cp_a_prendre, cp_pris, cc_solde et date_entree "
    "dans la table users pour le suivi des conges payes et conventionnels."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    colonnes = [
        ("cp_acquis", "REAL DEFAULT 0"),
        ("cp_a_prendre", "REAL DEFAULT 0"),
        ("cp_pris", "REAL DEFAULT 0"),
        ("cc_solde", "REAL DEFAULT 0"),
        ("date_entree", "TEXT"),
    ]

    for nom_col, type_col in colonnes:
        try:
            cursor.execute(f"SELECT {nom_col} FROM users LIMIT 1")
        except Exception:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {nom_col} {type_col}")
