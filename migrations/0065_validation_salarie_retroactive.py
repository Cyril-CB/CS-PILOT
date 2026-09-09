"""
Migration 0065 : régularisation des fiches verrouillées sans le salarié.

La validation d'une fiche d'heures suit désormais un ordre imposé — le salarié
déclare, le responsable contrôle, la direction arrête — et le verrouillage
exige les trois signatures. Jusqu'ici il n'en demandait que deux : des fiches
ont donc été closes sans que leur titulaire ait jamais signé.

Ces fiches sont régularisées ici plutôt que laissées dans un état que la
nouvelle règle interdit : leur signature salarié est posée au nom de
l'application (`Validation automatique`), ce qui se lit sur la fiche comme dans
le PDF mensuel — personne ne peut la confondre avec une signature. Chaque
régularisation laisse une ligne dans le journal d'audit, consultable par la
direction sous Administration > Sécurité, qui reste libre de déverrouiller une
fiche pour la faire signer réellement.

Migration de données : elle ne touche ni au schéma, ni aux fiches déjà signées,
et peut être rejouée sans effet.
"""
from access_log import ACTION_VALIDATION_SALARIE_AUTO
from utils import maintenant

NOM = "Régularisation des fiches verrouillées sans validation du salarié"
DESCRIPTION = (
    "Pose une validation salarié automatique sur les fiches verrouillées qui "
    "n'en portaient pas, et journalise chaque régularisation."
)

# Doit rester identique à validation.SIGNATURE_AUTOMATIQUE : c'est ce nom qui
# distingue, sur la fiche et dans le PDF, une signature d'une régularisation.
SIGNATURE_AUTOMATIQUE = 'Validation automatique'


def _fiches_a_regulariser(cursor):
    """Fiches verrouillées dont la signature salarié manque."""
    cursor.execute('''
        SELECT id, user_id, mois, annee FROM validations
        WHERE bloque = 1
          AND (validation_salarie IS NULL OR TRIM(validation_salarie) = '')
        ORDER BY annee, mois, user_id
    ''')
    return cursor.fetchall()


def upgrade(conn):
    """Applique la migration (idempotente)."""
    cursor = conn.cursor()
    horodatage = maintenant().strftime('%Y-%m-%d %H:%M:%S')

    for fiche in _fiches_a_regulariser(cursor):
        fiche_id, user_id, mois, annee = (fiche[0], fiche[1], fiche[2], fiche[3])
        cursor.execute(
            'UPDATE validations SET validation_salarie = ?, date_salarie = ? '
            'WHERE id = ?',
            (SIGNATURE_AUTOMATIQUE, horodatage, fiche_id)
        )
        # user_id reste vide : aucun utilisateur n'a posé cette signature.
        cursor.execute(
            'INSERT INTO journal_actions '
            '(date_heure, user_id, action, cible_type, cible_id, details) '
            'VALUES (?, NULL, ?, ?, ?, ?)',
            (horodatage, ACTION_VALIDATION_SALARIE_AUTO, 'user', user_id,
             f"mois={mois}/{annee} — fiche verrouillée sans validation du "
             f"salarié, régularisée à l'introduction de l'ordre de validation")
        )

    conn.commit()


def downgrade(conn):
    """Retire les signatures automatiques et leurs traces.

    Seules les fiches encore marquées `Validation automatique` sont concernées :
    une signature réelle posée depuis n'est pas effacée.
    """
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE validations SET validation_salarie = NULL, date_salarie = NULL '
        'WHERE validation_salarie = ?',
        (SIGNATURE_AUTOMATIQUE,)
    )
    cursor.execute('DELETE FROM journal_actions WHERE action = ?',
                   (ACTION_VALIDATION_SALARIE_AUTO,))
    conn.commit()
