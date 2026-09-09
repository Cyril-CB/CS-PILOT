"""Circuit salarié, responsable, direction et confirmation des anciens verrous."""
NOM = 'Circuit ordonne des fiches mensuelles'
DESCRIPTION = 'Anciens verrous conservés en circuit 1 ; fiches ouvertes en circuit 2.'


def upgrade(conn):
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    from fiches_circuit import creer_schema
    creer_schema(conn)


def downgrade(conn):
    raise RuntimeError('Restaurez la sauvegarde préalable pour revenir avant la migration 0067.')
