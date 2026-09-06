"""Conserver les contenus des fiches et rattacher les nouvelles signatures."""
NOM = 'Versions et integrite des fiches mensuelles'
DESCRIPTION = ('Reprise des fiches existantes sans inventer leur contenu historique, '
               'versions du contenu et journal des signatures/reouvertures.')


def upgrade(conn):
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    from fiches_versions import creer_schema
    creer_schema(conn)


def downgrade(conn):
    # Supprimer ces références détruirait les preuves des nouvelles signatures.
    raise RuntimeError('Restaurez la sauvegarde préalable pour revenir avant la migration 0065.')
