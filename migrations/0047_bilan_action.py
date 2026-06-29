"""
Migration 0047 : Ajout du module Bilan action.

Construction du budget prévisionnel et du réalisé d'une action analytique,
par action et par année, avec deux onglets (prévisionnel / réalisé).

- bilan_action_data : un enregistrement par (action, année, onglet). L'état
  complet de l'onglet (comptes de charges 60/61/62, produits, salariés avec
  paramètres de paie, sélection du taux de logistique, bénévoles, commentaires)
  est sérialisé en JSON dans la colonne `donnees`. Les totaux sont mis en cache
  pour un accès rapide.

Les taux de logistique restent stockés dans `bilan_taux_logistique` (partagés
avec la page Bilan secteurs). Le réalisé comptable est lu depuis
`bilan_fec_donnees` (import BI).
"""

NOM = "Ajout module bilan action"
DESCRIPTION = (
    "Ajoute la table bilan_action_data (budget prévisionnel et réalisé d'une "
    "action analytique, par action / année / onglet)."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bilan_action_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_id INTEGER NOT NULL,
            annee INTEGER NOT NULL,
            onglet TEXT NOT NULL DEFAULT 'previsionnel'
                CHECK(onglet IN ('previsionnel', 'realise')),
            donnees TEXT,
            total_charges REAL DEFAULT 0,
            total_produits REAL DEFAULT 0,
            updated_by INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(action_id, annee, onglet),
            FOREIGN KEY (action_id) REFERENCES comptabilite_actions(id) ON DELETE CASCADE,
            FOREIGN KEY (updated_by) REFERENCES users(id)
        )
    ''')


def downgrade(conn):
    """Suppression de la table du module bilan action."""
    cursor = conn.cursor()
    cursor.execute('DROP TABLE IF EXISTS bilan_action_data')
    conn.commit()
