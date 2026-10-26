"""Un férié désigné par année, sans désignation ni recalcul automatique."""
from schema_solidarite import creer_schema

NOM = 'Journée de solidarité annuelle'
DESCRIPTION = 'Permet de désigner un jour férié annuel pour les congés CP/CC.'


def upgrade(conn):
    creer_schema(conn)


def downgrade(conn):
    if conn.execute('SELECT 1 FROM jours_feries WHERE solidarite = 1 LIMIT 1').fetchone():
        raise ValueError('Des journées de solidarité sont désignées ; retour arrière refusé pour préserver les décomptes.')
    conn.execute('DROP INDEX IF EXISTS idx_solidarite_annee')
    # Colonne additive conservée : pas de reconstruction destructive de la table.
