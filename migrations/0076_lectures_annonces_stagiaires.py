"""Lecture personnelle des annonces d'accueil de stagiaires."""
from schema_stagiaires_lectures import creer_schema

NOM = 'Lectures individuelles des annonces de stagiaires'
DESCRIPTION = 'Mémorise les annonces lues par responsable, secteur, stagiaire et date.'


def upgrade(conn):
    creer_schema(conn)


def downgrade(conn):
    conn.execute('DROP TABLE IF EXISTS stagiaires_annonces_lectures')
