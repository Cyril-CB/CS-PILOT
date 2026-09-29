"""Suivi des stagiaires et de leur emploi du temps par demi-journée."""
from schema_stagiaires import creer_schema

NOM = 'Suivi des stagiaires'
DESCRIPTION = (
    'Ajoute la fiche des stagiaires accueillis (études, établissement, tuteur, '
    'période) et leur emploi du temps par demi-journée et par secteur.'
)


def upgrade(conn):
    creer_schema(conn)


def downgrade(conn):
    conn.execute('DROP INDEX IF EXISTS idx_stagiaires_creneaux_secteur_date')
    conn.execute('DROP TABLE IF EXISTS stagiaires_creneaux')
    conn.execute('DROP TABLE IF EXISTS stagiaires')
