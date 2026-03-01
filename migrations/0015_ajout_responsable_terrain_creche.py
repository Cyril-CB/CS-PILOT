"""
Migration 0015 : Ajout option responsable sur le terrain + mise a jour labels tranches.

Ajoute la colonne responsable_terrain a frequentation_creche pour permettre
au responsable de se compter dans le taux d'encadrement par tranche horaire.
Met a jour les labels de tranches pour utiliser des bornes decalees (09h01, 10h01...)
afin d'eviter toute ambiguite aux frontieres horaires.
"""

NOM = "Ajout responsable terrain creche"
DESCRIPTION = (
    "Ajoute la colonne responsable_terrain a frequentation_creche "
    "et met a jour les labels de tranches (bornes decalees)."
)


def upgrade(conn):
    cursor = conn.cursor()

    # 1. Ajouter la colonne responsable_terrain
    cursor.execute("PRAGMA table_info(frequentation_creche)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'responsable_terrain' not in columns:
        cursor.execute('''
            ALTER TABLE frequentation_creche
            ADD COLUMN responsable_terrain INTEGER DEFAULT 0
        ''')

    # 2. Mettre a jour les labels de tranches (anciens -> nouveaux)
    mapping = {
        '08h-09h': '08h00-09h00',
        '09h-10h': '09h01-10h00',
        '10h-11h': '10h01-11h00',
        '11h-12h': '11h01-12h00',
        '12h-13h': '12h01-13h00',
        '13h-14h': '13h01-14h00',
        '14h-15h': '14h01-15h00',
        '15h-16h': '15h01-16h00',
        '16h-17h': '16h01-17h00',
        '17h-18h': '17h01-18h00',
    }

    for ancien, nouveau in mapping.items():
        cursor.execute(
            'UPDATE frequentation_creche SET tranche = ? WHERE tranche = ?',
            (nouveau, ancien)
        )
