"""
Migration 0038 : Correction des types numeriques des tables variables_paie
et variables_paie_defauts.

Sur les bases creees par init_db (database.py), les colonnes mutuelle,
transport, acompte, saisie_salaire, pret_avance et autres_regularisation
avaient une affinite TEXT : SQLite stockait 0/1 sous forme de texte ('0'),
valeur consideree comme vraie cote Python/Jinja. Consequence visible :
toutes les cases "Mutuelle" de la page Variables de paie apparaissaient
cochees apres le premier enregistrement.

Reconstruit les deux tables avec les types INTEGER/REAL (schema des
migrations 0004 et 0010) et convertit les donnees existantes.
"""

NOM = "Correctif types variables paie"
DESCRIPTION = (
    "Reconstruit variables_paie et variables_paie_defauts avec des types "
    "INTEGER/REAL (les colonnes TEXT faisaient apparaitre toutes les cases "
    "mutuelle cochees) et convertit les donnees existantes."
)


def upgrade(conn):
    """Applique la migration."""
    # Logique partagee avec le fallback execute par init_db() au demarrage
    # (meme correctif, idempotent).
    from database import _corriger_types_variables_paie

    _corriger_types_variables_paie(conn.cursor())
    conn.commit()
