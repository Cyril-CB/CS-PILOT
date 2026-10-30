"""Conserve les demandes initiales et leurs annulations datées."""
NOM = 'Annulations datées des récupérations validées'
DESCRIPTION = 'Traçabilité des annulations et des remplacements par arrêt, sans reprise automatique.'


def upgrade(conn):
    from recuperations_annulation import creer_schema
    creer_schema(conn)


def downgrade(conn):
    raise RuntimeError('Restaurez la sauvegarde préalable pour conserver la trace des annulations.')
