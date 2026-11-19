"""Horodater les nouveaux plannings sans inventer la date des anciens."""

NOM = 'Date de création du planning théorique'
DESCRIPTION = ('Ajoute created_at aux plannings pour limiter la correction à 7 jours ; '
               'les anciennes lignes restent sans date et ne peuvent pas être corrigées.')


def upgrade(conn):
    colonnes = {row[1] for row in conn.execute('PRAGMA table_info(planning_theorique)')}
    if 'created_at' not in colonnes:
        conn.execute('ALTER TABLE planning_theorique ADD COLUMN created_at TEXT')


def downgrade(conn):
    colonnes = {row[1] for row in conn.execute('PRAGMA table_info(planning_theorique)')}
    if 'created_at' in colonnes:
        conn.execute('ALTER TABLE planning_theorique DROP COLUMN created_at')
