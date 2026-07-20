"""
Migration 0059 : pause méridienne rémunérée dans la saisie des heures.

Certains salariés (accueil de loisirs, crèche…) prennent leur pause sur
place en restant à la disposition de l'employeur : ce temps est du travail
effectif rémunéré (art. L3121-2 du Code du travail).

On ajoute `pause_remuneree` à `heures_reelles` : à 1, le temps entre la fin
du matin et le début de l'après-midi est compté dans les heures travaillées
et ne déclenche pas d'alerte « pause manquante » (la pause a bien eu lieu,
simplement sans quitter le poste). À 0 (défaut, et sur tout l'existant),
comportement inchangé.
"""

NOM = "Pause méridienne rémunérée (saisie des heures)"
DESCRIPTION = (
    "Ajoute heures_reelles.pause_remuneree (INTEGER, défaut 0). À 1, la pause "
    "entre le matin et l'après-midi est comptée dans les heures travaillées "
    "(salarié resté à disposition) et ne génère pas d'alerte pause. "
    "L'existant reste à 0 : aucun changement rétroactif."
)


def upgrade(conn):
    """Applique la migration (idempotente)."""
    import sqlite3
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT pause_remuneree FROM heures_reelles LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE heures_reelles ADD COLUMN pause_remuneree INTEGER DEFAULT 0")
    conn.commit()


def downgrade(conn):
    """SQLite ne supporte pas DROP COLUMN simplement : downgrade non destructif
    (la colonne reste, inerte tant que le code ne la lit pas)."""
    pass
