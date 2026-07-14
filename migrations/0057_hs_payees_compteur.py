"""
Migration 0057 : paiement des heures supplémentaires déduit du compteur de récup.

Jusqu'ici, payer des heures supplémentaires (colonne « H. supps » des variables
de paie) ne laissait aucune trace côté compteur : le solde de récupération du
salarié restait plein, avec un risque de double compensation (heures payées
PUIS récupérées) — problème surtout visible pour les CDD en fin de contrat.

On ajoute `hs_deduites_compteur` à `variables_paie` : à 1, les heures supp
payées ce mois-là sont déduites du solde de récupération (calculer_solde_recup)
et apparaissent dans l'historique du salarié.

La colonne est NULLABLE et vaut NULL sur les lignes existantes : les saisies
antérieures à la migration ne déduisent rien rétroactivement. Le formulaire
coche la déduction par défaut pour les nouvelles saisies.
"""

NOM = "Heures supp payées déduites du compteur de récup"
DESCRIPTION = (
    "Ajoute variables_paie.hs_deduites_compteur (INTEGER, nullable). À 1, les "
    "heures supp payées du mois sont déduites du solde de récupération. NULL "
    "sur l'existant : aucune déduction rétroactive."
)


def upgrade(conn):
    """Applique la migration (idempotente)."""
    import sqlite3
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT hs_deduites_compteur FROM variables_paie LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE variables_paie ADD COLUMN hs_deduites_compteur INTEGER")
    conn.commit()


def downgrade(conn):
    """SQLite ne supporte pas DROP COLUMN simplement : downgrade non destructif
    (la colonne reste, inerte tant que le code ne la lit pas)."""
    pass
