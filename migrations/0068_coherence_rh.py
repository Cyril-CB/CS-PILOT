"""Provenance des nouveaux reports et vérification de la préparation de paie."""
NOM = 'Coherence absences recuperations et preparation paie'
DESCRIPTION = 'Conserve les absences historiques ; les traitements sans preuve sont à vérifier.'


def upgrade(conn):
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    from absences_coherence import creer_schema as absences
    from prepa_paie_donnees import creer_schema as paie
    absences(conn)
    paie(conn)


def downgrade(conn):
    raise RuntimeError('Restaurez la sauvegarde préalable pour conserver les preuves et revenir avant 0068.')
