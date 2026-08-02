"""
Flux d'information des pages, dans l'interface sans menu.

Sans menu, une page ne s'ouvre plus « pour voir » : on y arrive depuis le fil,
la barre intelligente ou la vue d'ensemble. Elle doit donc dire d'emblée ce
qu'elle a à signaler — factures non validées, écritures à générer, étapes en
retard — avant la liste elle-même.

Chaque entrée est un bandeau court : `{icone, valeur, libelle, lien,
lien_texte, ton}`. Le ton (`alerte`, `attention`, `calme`) donne la couleur.

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
    """Ce que la page Factures doit signaler avant sa liste."""
    if contexte.get('profil') not in _COMPTA:
        return []
    today = aujourd_hui().isoformat()
    infos = []

    attente = conn.execute(
        "SELECT COUNT(*) AS nb FROM factures WHERE approbation = 'en_attente'"
    ).fetchone()['nb']
    if attente:
        infos.append(_info(
            '🧾', attente, 'facture(s) en attente d\'approbation',
            url_for('factures_bp.approbation_factures'), 'Approuver',
            'attention',
        ))

    retard = conn.execute(
        '''SELECT COUNT(*) AS nb FROM factures
           WHERE approbation = 'en_attente'
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
    """Ce que la page Subventions doit signaler."""
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

    en_cours = conn.execute(
        f'''SELECT COUNT(*) AS nb
            FROM subventions_sous_elements se
            JOIN subventions s ON s.id = se.subvention_id
            WHERE se.statut != 'fait' AND s.groupe != 'refusee' {scope}''',
        params
    ).fetchone()['nb']
    if en_cours:
        infos.append(_info(
            '📋', en_cours, 'étape(s) encore ouverte(s)',
            url_for('subventions_bp.gestion_subventions', annee='toutes'), 'Suivre',
        ))

    return infos


def _validations(conn, contexte):
    """Ce que la vue d'ensemble des validations doit signaler."""
    today = aujourd_hui()
    mois_prec = today.month - 1 or 12
    annee_prec = today.year if today.month > 1 else today.year - 1
    infos = []

    non_validees = conn.execute(
        '''SELECT COUNT(*) AS nb FROM users u
           WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
             AND NOT EXISTS (
                 SELECT 1 FROM validations v
                 WHERE v.user_id = u.id AND v.mois = ? AND v.annee = ? AND v.bloque = 1
             )''',
        (mois_prec, annee_prec)
    ).fetchone()['nb']
    if non_validees:
        infos.append(_info(
            '✅', non_validees,
            f"fiche(s) de {NOMS_MOIS[mois_prec].lower()} non validée(s)",
            url_for('validation_bp.vue_ensemble_validation'), 'Vue mensuelle',
            'alerte' if today.day > 10 else 'attention',
        ))

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
