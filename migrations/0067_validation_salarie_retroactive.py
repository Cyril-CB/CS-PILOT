"""
Migration 0067 : régularisation des fiches verrouillées sans le salarié.

La validation d'une fiche d'heures suit désormais un ordre imposé — le salarié
déclare, le responsable contrôle, la direction arrête — et le verrouillage
exige les trois signatures. Jusqu'ici il n'en demandait que deux : des fiches
ont donc été closes sans que leur titulaire ait jamais signé.

Ces fiches sont régularisées ici plutôt que laissées dans un état que la
nouvelle règle interdit : leur signature salarié est posée au nom de
l'application (`Validation automatique`), ce qui se lit sur la fiche comme dans
le PDF mensuel — personne ne peut la confondre avec une signature. Chaque
régularisation laisse une ligne dans l'historique de la fiche, sans auteur
puisque personne n'a signé. La direction reste libre de rouvrir une fiche, avec
motif, pour la faire signer réellement.

La signature est rattachée à la version courante de la fiche quand celle-ci en
a une, afin qu'elle compte comme les autres. Les fiches verrouillées avant le
versionnage n'en ont pas : elles restent des fiches historiques, déjà signalées
comme telles à l'affichage.

Migration de données : elle ne touche ni au schéma, ni aux fiches déjà signées,
et peut être rejouée sans effet.
"""
from fiches_versions import evenement
from utils import maintenant

NOM = "Régularisation des fiches verrouillées sans validation du salarié"
DESCRIPTION = (
    "Pose une validation salarié automatique sur les fiches verrouillées qui "
    "n'en portaient pas, et l'inscrit dans l'historique de chaque fiche."
)

# Doit rester identique à validation.SIGNATURE_AUTOMATIQUE : c'est ce nom qui
# distingue, sur la fiche et dans le PDF, une signature d'une régularisation.
SIGNATURE_AUTOMATIQUE = 'Validation automatique'

# Type d'événement de l'historique des fiches (libellé dans
# templates/_fiche_signatures.html).
EVENEMENT = 'validation_salarie_auto'


def upgrade(conn):
    """Applique la migration (idempotente)."""
    horodatage = maintenant().strftime('%Y-%m-%d %H:%M:%S')

    fiches = conn.execute('''
        SELECT id, user_id, mois, annee, version_courante_id FROM validations
        WHERE bloque = 1
          AND (validation_salarie IS NULL OR TRIM(validation_salarie) = '')
        ORDER BY annee, mois, user_id
    ''').fetchall()

    for fiche in fiches:
        conn.execute(
            'UPDATE validations SET validation_salarie = ?, date_salarie = ?, '
            'version_salarie_id = ? WHERE id = ?',
            (SIGNATURE_AUTOMATIQUE, horodatage, fiche['version_courante_id'],
             fiche['id'])
        )
        # Aucun auteur : personne n'a posé cette signature. `evenement` laisse
        # l'auteur inconnu hors requête, ce qui est précisément le cas ici.
        evenement(conn, fiche['user_id'], fiche['annee'], fiche['mois'],
                  EVENEMENT, fiche['version_courante_id'], role='salarie',
                  details="Fiche verrouillée sans validation du salarié, "
                          "régularisée à l'introduction de l'ordre de validation")

    conn.commit()


def downgrade(conn):
    """Retire les signatures automatiques et leurs traces.

    Seules les fiches encore marquées `Validation automatique` sont concernées :
    une signature réelle posée depuis n'est pas effacée.
    """
    conn.execute(
        'UPDATE validations SET validation_salarie = NULL, date_salarie = NULL, '
        'version_salarie_id = NULL WHERE validation_salarie = ?',
        (SIGNATURE_AUTOMATIQUE,)
    )
    conn.execute('DELETE FROM fiches_evenements WHERE evenement = ?', (EVENEMENT,))
    conn.commit()
