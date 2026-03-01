"""
Migration 0020 : Solde initial global pour la tresorerie.

- Ajoute annee_ref et mois_ref a tresorerie_solde_initial
  pour stocker la periode de reference du solde initial.
  Le solde est ensuite propage automatiquement quelle que soit la vue.
"""

NOM = "Solde initial global tresorerie"
DESCRIPTION = (
    "Ajoute annee_ref et mois_ref a la table tresorerie_solde_initial "
    "pour permettre un solde initial persistant independant de la vue."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    # Ajouter les colonnes de reference
    try:
        cursor.execute(
            'ALTER TABLE tresorerie_solde_initial ADD COLUMN annee_ref INTEGER'
        )
    except Exception:
        pass  # colonne existe deja

    try:
        cursor.execute(
            'ALTER TABLE tresorerie_solde_initial ADD COLUMN mois_ref INTEGER'
        )
    except Exception:
        pass  # colonne existe deja

    # Migrer les donnees existantes : copier annee->annee_ref, mois->mois_ref
    cursor.execute('''
        UPDATE tresorerie_solde_initial
        SET annee_ref = annee, mois_ref = mois
        WHERE annee_ref IS NULL
    ''')

    conn.commit()
