"""
Migration 0011 : Ajout de la colonne email_notifications_enabled
dans la table users.

Permet aux salaries de donner (ou non) leur consentement pour recevoir
des notifications par email. Par defaut a 0 (pas de consentement).
Les profils directeur, comptable et responsable restent notifies
independamment de ce flag (mail professionnel).
"""

NOM = "Ajout consentement notifications email"
DESCRIPTION = (
    "Ajoute la colonne email_notifications_enabled (defaut 0) "
    "a la table users pour le consentement des salaries."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    cols = [row[1] for row in cursor.execute('PRAGMA table_info(users)').fetchall()]

    if 'email_notifications_enabled' not in cols:
        cursor.execute('ALTER TABLE users ADD COLUMN email_notifications_enabled INTEGER DEFAULT 0')

    conn.commit()
