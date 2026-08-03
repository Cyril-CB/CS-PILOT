"""
Flux d'information des pages, dans l'interface sans menu.

Sans menu, une page ne s'ouvre plus « pour voir » : on y arrive depuis le fil,
la barre intelligente ou la vue d'ensemble. Elle doit donc dire d'emblée ce
qu'elle a à signaler — factures non validées, écritures à générer, étapes en
retard — avant la liste elle-même.

Chaque entrée est un bandeau court : `{icone, valeur, libelle, lien,
lien_texte, ton}`. Le ton (`alerte`, `attention`, `calme`) donne la couleur.

Un bandeau ne dit que ce que la liste ne dit pas d'elle-même. Recompter ses
lignes juste au-dessus d'elle n'apprend rien et repousse le tableau vers le
bas : un total sans retard, sans échéance ni décision à prendre n'est pas une
information, c'est la liste écrite deux fois.

Toutes les pages n'ont pas de flux : la trésorerie, par exemple, EST son
tableau. Une page sans constructeur n'affiche simplement rien de plus.
"""
import logging

from flask import url_for

from utils import NOMS_MOIS, aujourd_hui

logger = logging.getLogger(__name__)

# Profils qui voient les flux financiers (mêmes droits que les pages elles-mêmes).
_COMPTA = ('directeur', 'comptable')


def _info(icone, valeur, libelle, lien, lien_texte, ton='calme'):
    return {
        'icone': icone,
        'valeur': valeur,
        'libelle': libelle,
        'lien': lien,
        'lien_texte': lien_texte,
        'ton': ton,
    }


def _factures(conn, contexte):
    """Ce que la page Factures doit signaler avant sa liste.

    Les compteurs d'approbation reprennent le filtre de la page d'approbation
    (`factures_bp.approbation_factures`) : elle n'affiche que les factures
    rattachées à un secteur ou assignées à la direction. Annoncer un nombre
    plus grand enverrait vers une page qui en montre moins — ou vide. Les
    factures non assignées sont signalées à part, vers leur vraie destination.
    """
    if contexte.get('profil') not in _COMPTA:
        return []
    today = aujourd_hui().isoformat()
    # Ce que la page d'approbation liste réellement.
    approuvables = "(secteur_id IS NOT NULL OR assigned_direction = 1)"
    infos = []

    attente = conn.execute(
        f"""SELECT COUNT(*) AS nb FROM factures
            WHERE approbation = 'en_attente' AND {approuvables}"""
    ).fetchone()['nb']
    if attente:
        infos.append(_info(
            '🧾', attente, 'facture(s) en attente d\'approbation',
            url_for('factures_bp.approbation_factures'), 'Approuver',
            'attention',
        ))

    retard = conn.execute(
        f'''SELECT COUNT(*) AS nb FROM factures
            WHERE approbation = 'en_attente' AND {approuvables}
              AND date_echeance IS NOT NULL AND date_echeance != ''
              AND date_echeance < ?''',
        (today,)
    ).fetchone()['nb']
    if retard:
        infos.append(_info(
            '⏰', retard, "facture(s) dont l'échéance est dépassée",
            url_for('factures_bp.approbation_factures'), 'Traiter',
            'alerte',
        ))

    # Une facture importée sans secteur ni direction n'est encore entrée dans
    # aucun circuit : elle n'est pas « à approuver », elle est à assigner.
    a_assigner = conn.execute(
        """SELECT COUNT(*) AS nb FROM factures
           WHERE approbation = 'en_attente'
             AND secteur_id IS NULL AND assigned_direction = 0"""
    ).fetchone()['nb']
    if a_assigner:
        infos.append(_info(
            '📥', a_assigner, 'facture(s) à assigner à un secteur',
            url_for('factures_bp.liste_factures'), 'Assigner',
            'attention',
        ))

    orphelines = conn.execute(
        'SELECT COUNT(*) AS nb FROM factures WHERE fournisseur_id IS NULL'
    ).fetchone()['nb']
    if orphelines:
        infos.append(_info(
            '🏢', orphelines, 'facture(s) sans fournisseur rattaché',
            url_for('fournisseurs_bp.liste_fournisseurs'), 'Fournisseurs',
        ))

    return infos


def _ecritures(conn, contexte):
    """Ce que la page Écritures doit signaler."""
    if contexte.get('profil') not in _COMPTA:
        return []
    infos = []

    a_generer = conn.execute(
        "SELECT COUNT(*) AS nb FROM factures WHERE statut = 'a_traiter'"
    ).fetchone()['nb']
    if a_generer:
        infos.append(_info(
            '⚙', a_generer, 'facture(s) sans écriture — à générer',
            url_for('ecritures_bp.liste_ecritures'), 'Générer',
            'attention',
        ))

    brouillons = conn.execute(
        "SELECT COUNT(*) AS nb FROM ecritures_comptables WHERE statut = 'brouillon'"
    ).fetchone()['nb']
    if brouillons:
        infos.append(_info(
            '📝', brouillons, 'écriture(s) en brouillon à valider',
            url_for('ecritures_bp.liste_ecritures'), 'Valider',
            'attention',
        ))

    validees = conn.execute(
        "SELECT COUNT(*) AS nb FROM ecritures_comptables WHERE statut = 'validee'"
    ).fetchone()['nb']
    if validees:
        infos.append(_info(
            '📤', validees, 'écriture(s) validée(s), prêtes à exporter',
            url_for('exportation_bp.liste_exportation'), 'Exporter',
        ))

    return infos


def _subventions(conn, contexte):
    """Ce que la page Subventions doit signaler : le retard, et rien d'autre.

    Le nombre d'étapes encore ouvertes ne vaut pas un bandeau : c'est le
    tableau qui suit, annoncé une ligne plus haut. Le retard, lui, ne se lit
    pas d'un coup d'œil — il se disperse dans les sous-éléments repliés, et
    souvent hors de l'année filtrée par défaut, d'où le lien vers « toutes ».
    """
    profil = contexte.get('profil')
    user_id = contexte.get('user_id')
    if profil == 'responsable':
        scope = 'AND (s.assignee_1_id = ? OR s.assignee_2_id = ? OR se.assignee_id = ?)'
        params = (user_id, user_id, user_id)
    elif profil in _COMPTA:
        scope, params = '', ()
    else:
        return []

    today = aujourd_hui().isoformat()
    infos = []

    retard = conn.execute(
        f'''SELECT COUNT(*) AS nb
            FROM subventions_sous_elements se
            JOIN subventions s ON s.id = se.subvention_id
            WHERE se.date_echeance IS NOT NULL AND se.date_echeance != ''
              AND se.date_echeance < ? AND se.statut != 'fait'
              AND s.groupe != 'refusee' {scope}''',
        (today,) + params
    ).fetchone()['nb']
    if retard:
        infos.append(_info(
            '🚨', retard, "étape(s) dont l'échéance est passée",
            url_for('subventions_bp.gestion_subventions', annee='toutes'), 'Voir',
            'alerte',
        ))

    return infos


def _validations(conn, contexte):
    """Ce que la vue d'ensemble des validations doit signaler.

    Deux cadrages distincts, calqués sur ce que le lecteur peut réellement
    voir et faire :
    - le décompte des fiches suit la page elle-même, qui borne un responsable
      sans délégation à son équipe ;
    - le bandeau des demandes à valider n'apparaît que pour les profils que
      `recup_bp.validation_demandes_recup` accepte. Un salarié délégué au
      suivi des validations n'y a pas droit — sa délégation porte sur le suivi
      des fiches, pas sur les décisions de congés.
    """
    profil = contexte.get('profil')
    user_id = contexte.get('user_id')
    today = aujourd_hui()
    mois_prec = today.month - 1 or 12
    annee_prec = today.year if today.month > 1 else today.year - 1
    infos = []

    # Un responsable ne suit que son équipe ; les autres lecteurs de la page
    # (direction, comptabilité, délégué au suivi) la voient en entier.
    equipe_seule = profil == 'responsable'
    if equipe_seule:
        secteur = conn.execute('SELECT secteur_id FROM users WHERE id = ?',
                               (user_id,)).fetchone()
        scope = 'AND (u.secteur_id = ? OR u.responsable_id = ?)'
        params = (secteur['secteur_id'] if secteur else None, user_id)
    else:
        scope, params = '', ()

    non_validees = conn.execute(
        f'''SELECT COUNT(*) AS nb FROM users u
            WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
              {scope}
              AND NOT EXISTS (
                  SELECT 1 FROM validations v
                  WHERE v.user_id = u.id AND v.mois = ? AND v.annee = ? AND v.bloque = 1
              )''',
        params + (mois_prec, annee_prec)
    ).fetchone()['nb']
    if non_validees:
        infos.append(_info(
            '✅', non_validees,
            f"fiche(s) de {NOMS_MOIS[mois_prec].lower()} non validée(s)"
            + (' dans votre équipe' if equipe_seule else ''),
            url_for('validation_bp.vue_ensemble_validation'), 'Vue mensuelle',
            'alerte' if today.day > 10 else 'attention',
        ))

    if profil not in ('directeur', 'comptable', 'responsable'):
        return infos

    if equipe_seule:
        attente = conn.execute(
            '''SELECT (SELECT COUNT(*) FROM demandes_recup d
                       JOIN users u ON u.id = d.user_id
                       WHERE d.statut = 'en_attente_responsable'
                         AND (u.secteur_id = ? OR u.responsable_id = ?))
                    + (SELECT COUNT(*) FROM demandes_conges d
                       JOIN users u ON u.id = d.user_id
                       WHERE d.statut = 'en_attente_responsable'
                         AND (u.secteur_id = ? OR u.responsable_id = ?))
                    AS nb''',
            params + params
        ).fetchone()['nb']
    else:
        attente = conn.execute(
            '''SELECT (SELECT COUNT(*) FROM demandes_recup
                       WHERE statut IN ('en_attente_responsable', 'en_attente_direction'))
                    + (SELECT COUNT(*) FROM demandes_conges
                       WHERE statut IN ('en_attente_responsable', 'en_attente_direction'))
                    AS nb'''
        ).fetchone()['nb']
    if attente:
        infos.append(_info(
            '📋', attente, 'demande(s) en attente de validation',
            url_for('recup_bp.validation_demandes_recup'), 'Valider',
            'attention',
        ))

    return infos


# Constructeurs par endpoint. Une page absente de cette table n'affiche pas de
# flux : c'est le cas voulu pour les pages qui sont déjà un tableau complet.
CONSTRUCTEURS = {
    'factures_bp.liste_factures': _factures,
    'ecritures_bp.liste_ecritures': _ecritures,
    'subventions_bp.gestion_subventions': _subventions,
    'validation_bp.vue_ensemble_validation': _validations,
}


def construire(conn, endpoint, contexte):
    """Flux d'information d'une page, ou liste vide.

    Ne doit jamais faire tomber la page qu'elle décore : toute erreur de lecture
    (table absente sur une base non migrée, base verrouillée) se solde par un
    flux vide.
    """
    constructeur = CONSTRUCTEURS.get(endpoint)
    if not constructeur:
        return []
    try:
        return constructeur(conn, contexte)
    except Exception:
        logger.warning("Flux d'information indisponible pour %s", endpoint, exc_info=True)
        return []
