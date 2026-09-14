"""Identité légale et documents communs de l'établissement."""
from schema_identite_centre import creer_schema

NOM = 'Fiche d’identité du centre'
DESCRIPTION = 'Fiche unique, champs texte personnalisés et documents communs sous droits.'


def upgrade(conn):
    creer_schema(conn)


def downgrade(conn):
    raise RuntimeError('Restaurez la sauvegarde préalable pour conserver la fiche et ses documents.')
