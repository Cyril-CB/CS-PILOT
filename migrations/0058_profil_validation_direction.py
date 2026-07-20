"""
Migration 0058 : profil du valideur « direction » des demandes de congés/récup.

Jusqu'ici, seul le nom du valideur de second niveau était stocké
(`validation_direction`) ; le libellé « (direction) » était écrit en dur à
l'affichage. Quand un(e) comptable validait une demande (en l'absence de la
direction), son nom apparaissait donc à tort suivi de « (direction) ».

On ajoute `profil_validation_direction` à `demandes_conges` et
`demandes_recup` : renseigné à la validation ('directeur' ou 'comptable'),
il permet d'afficher le bon libellé. Les lignes déjà validées sont remplies
au mieux en retrouvant l'utilisateur par « Prénom Nom » parmi les profils
habilités ; sans correspondance la colonne reste NULL et l'affichage
retombe sur « (direction) » comme avant.
"""

NOM = "Profil du valideur direction/comptable des demandes"
DESCRIPTION = (
    "Ajoute demandes_conges.profil_validation_direction et "
    "demandes_recup.profil_validation_direction (TEXT, nullable) : profil du "
    "valideur de second niveau ('directeur' ou 'comptable') pour afficher le "
    "bon libellé à côté de son nom. Backfill au mieux par correspondance "
    "Prénom Nom sur les demandes déjà validées."
)


def upgrade(conn):
    """Applique la migration (idempotente)."""
    import sqlite3
    cursor = conn.cursor()
    for table in ('demandes_conges', 'demandes_recup'):
        try:
            cursor.execute(f"SELECT profil_validation_direction FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN profil_validation_direction TEXT")

        # Backfill au mieux : retrouver le valideur par « Prénom Nom » parmi les
        # profils habilités à valider ce niveau. Idempotent (ne touche que les
        # lignes encore NULL) ; sans correspondance, NULL → libellé historique.
        cursor.execute(f'''
            UPDATE {table}
            SET profil_validation_direction = (
                SELECT u.profil FROM users u
                WHERE (u.prenom || ' ' || u.nom) = {table}.validation_direction
                  AND u.profil IN ('directeur', 'comptable')
            )
            WHERE validation_direction IS NOT NULL
              AND validation_direction != ''
              AND profil_validation_direction IS NULL
        ''')
    conn.commit()


def downgrade(conn):
    """SQLite ne supporte pas DROP COLUMN simplement : downgrade non destructif
    (la colonne reste, inerte tant que le code ne la lit pas)."""
    pass
