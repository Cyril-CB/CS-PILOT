"""
Migration 0035 : Demandes de recuperation partielles (journee ou creneau).

Ajoute a la table demandes_recup la possibilite de demander une recuperation
sur un creneau d'absence (demi-journee ou quelques heures) en plus de la
journee complete existante :

- type_demande : 'journee' (defaut, comportement historique) ou 'partielle'
- heure_debut  : debut du creneau d'absence (recup partielle uniquement)
- heure_fin    : fin du creneau d'absence (recup partielle uniquement)
"""

NOM = "Recuperation partielle"
DESCRIPTION = (
    "Ajoute les colonnes type_demande, heure_debut et heure_fin a la table "
    "demandes_recup pour gerer les recuperations sur un creneau d'absence."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    cols = [row[1] for row in cursor.execute('PRAGMA table_info(demandes_recup)').fetchall()]

    if 'type_demande' not in cols:
        cursor.execute(
            "ALTER TABLE demandes_recup ADD COLUMN type_demande TEXT DEFAULT 'journee'"
        )

    if 'heure_debut' not in cols:
        cursor.execute("ALTER TABLE demandes_recup ADD COLUMN heure_debut TEXT")

    if 'heure_fin' not in cols:
        cursor.execute("ALTER TABLE demandes_recup ADD COLUMN heure_fin TEXT")

    conn.commit()


def downgrade(conn):
    """Annule la migration (SQLite ne supporte pas DROP COLUMN simplement)."""
    # SQLite ancien ne permet pas DROP COLUMN : on laisse les colonnes en place.
    pass
