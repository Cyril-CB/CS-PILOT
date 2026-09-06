"""Révoquer les cookies antérieurs aux changements sensibles du compte."""
NOM = 'Revocation des sessions'
DESCRIPTION = ('Compteur de session et trigger sur activation/mot de passe. '
               'Les cookies sans compteur imposent une reconnexion.')


def upgrade(conn):
    from sessions_securite import creer_schema
    creer_schema(conn)


def downgrade(conn):
    raise RuntimeError('Restaurez la sauvegarde préalable pour revenir avant la migration 0066.')
