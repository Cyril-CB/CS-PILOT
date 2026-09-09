"""Preuves autonomes des nouveaux exports ; aucune reconstruction historique."""
NOM = 'Preuves des exports comptables'
DESCRIPTION = 'Conserve le fichier exact, ses lignes et sa traçabilité dans une même transaction.'


def upgrade(conn):
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    from exports_comptables import creer_schema
    creer_schema(conn)


def downgrade(conn):
    raise RuntimeError('Restaurez une sauvegarde préalable pour revenir avant 0069 sans effacer les preuves comptables.')
