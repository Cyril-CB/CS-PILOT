"""
Migration 0036 : Horaires forfait jour.

Le forfait jour n'impose pas d'horaire, mais la direction souhaite pouvoir
noter, de facon facultative, les heures travaillees sur une journee. On ajoute
a la table presence_forfait_jour quatre colonnes d'horaires (matin / apres-midi) :

- matin_debut  : debut de la matinee (HH:MM)
- matin_fin    : fin de la matinee (HH:MM)
- aprem_debut  : debut de l'apres-midi (HH:MM)
- aprem_fin    : fin de l'apres-midi (HH:MM)
"""

NOM = "Horaires forfait jour"
DESCRIPTION = (
    "Ajoute les colonnes matin_debut, matin_fin, aprem_debut et aprem_fin a la "
    "table presence_forfait_jour pour le suivi facultatif des heures travaillees."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    cols = [row[1] for row in cursor.execute('PRAGMA table_info(presence_forfait_jour)').fetchall()]

    for col in ('matin_debut', 'matin_fin', 'aprem_debut', 'aprem_fin'):
        if col not in cols:
            cursor.execute(f"ALTER TABLE presence_forfait_jour ADD COLUMN {col} TEXT")

    conn.commit()


def downgrade(conn):
    """Annule la migration (SQLite ne supporte pas DROP COLUMN simplement)."""
    # SQLite ancien ne permet pas DROP COLUMN : on laisse les colonnes en place.
    pass
