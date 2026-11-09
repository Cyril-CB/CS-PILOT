"""Option facultative de lieux d'intervention pour Mon équipe."""
from schema_equipe_lieux import creer_schema
NOM = 'Lieux d intervention dans Mon equipe'
DESCRIPTION = 'Répartition habituelle par secteur et demi-journée, sans lien avec les heures.'

def upgrade(conn):
    creer_schema(conn)

def downgrade(conn):
    conn.execute('DROP TABLE IF EXISTS equipe_lieux_affectations')
    conn.execute('DROP TABLE IF EXISTS equipe_lieux_options')
