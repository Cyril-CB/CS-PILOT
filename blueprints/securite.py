"""
Blueprint securite_bp - Journal des acces (securite).

Permet a la direction de consulter le journal des connexions a l'application :
connexions reussies, echecs de connexion, demandes de reinitialisation et
modifications de mot de passe. Le journal peut etre consulte directement dans
l'interface ou telecharge au format CSV.

Accessible aux profils de direction et de comptabilite (directeur, comptable).
"""
import csv
import io
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for, session, flash,
    Response
)

from access_log import EVENEMENTS_LABELS, ACTIONS_LABELS
from database import get_db
from utils import login_required

securite_bp = Blueprint('securite_bp', __name__)

# Nombre maximal d'entrees affichees a l'ecran (l'export CSV n'est pas limite)
LIMITE_AFFICHAGE = 500


def _check_acces():
    """Verifie que l'utilisateur peut consulter le journal (direction/comptable).

    Pour l'instant le comptable dispose des memes acces que la direction ;
    ce perimetre pourra etre restreint ulterieurement si besoin.
    """
    return session.get('profil') in ('directeur', 'comptable')


def _lire_filtres():
    """Recupere les filtres communs depuis la requete."""
    return {
        'evenement': request.args.get('evenement') or '',
        'date_debut': request.args.get('date_debut') or '',
        'date_fin': request.args.get('date_fin') or '',
        'recherche': (request.args.get('recherche') or '').strip(),
    }


# Requete du journal : chaine CONSTANTE (jamais derivee d'une saisie
# utilisateur). Les filtres sont optionnels et appliques via des parametres
# nommes (:nom) ; une valeur vide neutralise le filtre correspondant.
# limite = -1 retourne toutes les lignes (illimite en SQLite).
_JOURNAL_QUERY = '''
    SELECT j.id, j.date_heure, j.login_saisi, j.evenement, j.adresse_ip,
           u.nom AS nom, u.prenom AS prenom
    FROM journal_acces j
    LEFT JOIN users u ON j.user_id = u.id
    WHERE (:evenement = '' OR j.evenement = :evenement)
      AND (:date_debut = '' OR date(j.date_heure) >= date(:date_debut))
      AND (:date_fin = '' OR date(j.date_heure) <= date(:date_fin))
      AND (:recherche = ''
           OR j.login_saisi LIKE :recherche_like
           OR u.nom LIKE :recherche_like
           OR u.prenom LIKE :recherche_like)
    ORDER BY j.date_heure DESC, j.id DESC
    LIMIT :limite
'''


def _params_filtres(filtres, limite):
    """Construit le dictionnaire de parametres nommes pour `_JOURNAL_QUERY`.

    Les valeurs saisies par l'utilisateur ne transitent QUE par ces parametres
    (lies par le moteur SQL) ; elles ne sont jamais concatenees a la requete.
    """
    evenement = filtres['evenement'] if filtres['evenement'] in EVENEMENTS_LABELS else ''
    recherche = filtres['recherche']
    return {
        'evenement': evenement,
        'date_debut': filtres['date_debut'],
        'date_fin': filtres['date_fin'],
        'recherche': recherche,
        'recherche_like': f'%{recherche}%',
        'limite': limite,
    }


@securite_bp.route('/securite/journal-acces')
@login_required
def journal_acces():
    """Affiche le journal des acces (direction et comptabilite)."""
    if not _check_acces():
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    filtres = _lire_filtres()

    conn = get_db()
    try:
        entrees = conn.execute(_JOURNAL_QUERY, _params_filtres(filtres, LIMITE_AFFICHAGE)).fetchall()
    finally:
        conn.close()

    return render_template(
        'journal_acces.html',
        entrees=entrees,
        evenements_labels=EVENEMENTS_LABELS,
        limite=LIMITE_AFFICHAGE,
        **filtres,
    )


@securite_bp.route('/securite/journal-acces/export')
@login_required
def export_journal_acces():
    """Telecharge le journal des acces (filtre applique) au format CSV."""
    if not _check_acces():
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    filtres = _lire_filtres()

    conn = get_db()
    try:
        # limite = -1 : export complet (pas de plafond d'affichage)
        entrees = conn.execute(_JOURNAL_QUERY, _params_filtres(filtres, -1)).fetchall()
    finally:
        conn.close()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Date et heure', 'Identifiant saisi', 'Utilisateur', 'Événement', 'Adresse IP'])
    for e in entrees:
        nom_complet = f"{e['prenom'] or ''} {e['nom'] or ''}".strip()
        writer.writerow([
            e['date_heure'] or '',
            e['login_saisi'] or '',
            nom_complet,
            EVENEMENTS_LABELS.get(e['evenement'], e['evenement']),
            e['adresse_ip'] or '',
        ])

    nom_fichier = f"journal_acces_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    # Encodage utf-8-sig : ajoute un BOM pour un affichage correct des accents
    # a l'ouverture du CSV dans Excel.
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename={nom_fichier}'},
    )


# ===================== Journal des actions metier (audit) =====================

def _lire_filtres_actions():
    """Recupere les filtres du journal des actions depuis la requete."""
    return {
        'action': request.args.get('action') or '',
        'date_debut': request.args.get('date_debut') or '',
        'date_fin': request.args.get('date_fin') or '',
        'recherche': (request.args.get('recherche') or '').strip(),
    }


# Requete CONSTANTE (jamais derivee d'une saisie utilisateur). Les filtres sont
# appliques via des parametres nommes. La 2e jointure resout le nom du salarie
# vise quand la cible est un utilisateur (cible_type = 'user').
_ACTIONS_QUERY = '''
    SELECT j.id, j.date_heure, j.action, j.cible_type, j.cible_id,
           j.details, j.adresse_ip,
           u.nom AS auteur_nom, u.prenom AS auteur_prenom,
           c.nom AS cible_nom, c.prenom AS cible_prenom
    FROM journal_actions j
    LEFT JOIN users u ON j.user_id = u.id
    LEFT JOIN users c ON j.cible_type = 'user' AND j.cible_id = c.id
    WHERE (:action = '' OR j.action = :action)
      AND (:date_debut = '' OR date(j.date_heure) >= date(:date_debut))
      AND (:date_fin = '' OR date(j.date_heure) <= date(:date_fin))
      AND (:recherche = ''
           OR u.nom LIKE :recherche_like
           OR u.prenom LIKE :recherche_like)
    ORDER BY j.date_heure DESC, j.id DESC
    LIMIT :limite
'''


def _params_filtres_actions(filtres, limite):
    """Parametres nommes pour `_ACTIONS_QUERY` (valeurs liees, jamais concatenees)."""
    action = filtres['action'] if filtres['action'] in ACTIONS_LABELS else ''
    recherche = filtres['recherche']
    return {
        'action': action,
        'date_debut': filtres['date_debut'],
        'date_fin': filtres['date_fin'],
        'recherche': recherche,
        'recherche_like': f'%{recherche}%',
        'limite': limite,
    }


def _cible_lisible(e):
    """Libelle lisible de la cible d'une action (nom du salarie si connu)."""
    if e['cible_nom'] or e['cible_prenom']:
        return f"{e['cible_prenom'] or ''} {e['cible_nom'] or ''}".strip()
    if e['cible_type']:
        return f"{e['cible_type']} #{e['cible_id']}" if e['cible_id'] else e['cible_type']
    return ''


@securite_bp.route('/securite/journal-actions')
@login_required
def journal_actions():
    """Affiche le journal des actions metier (direction et comptabilite)."""
    if not _check_acces():
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    filtres = _lire_filtres_actions()

    conn = get_db()
    try:
        entrees = conn.execute(_ACTIONS_QUERY, _params_filtres_actions(filtres, LIMITE_AFFICHAGE)).fetchall()
    finally:
        conn.close()

    return render_template(
        'journal_actions.html',
        entrees=entrees,
        actions_labels=ACTIONS_LABELS,
        cible_lisible=_cible_lisible,
        limite=LIMITE_AFFICHAGE,
        **filtres,
    )


@securite_bp.route('/securite/journal-actions/export')
@login_required
def export_journal_actions():
    """Telecharge le journal des actions (filtre applique) au format CSV."""
    if not _check_acces():
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    filtres = _lire_filtres_actions()

    conn = get_db()
    try:
        entrees = conn.execute(_ACTIONS_QUERY, _params_filtres_actions(filtres, -1)).fetchall()
    finally:
        conn.close()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Date et heure', 'Auteur', 'Action', 'Cible', 'Détails', 'Adresse IP'])
    for e in entrees:
        auteur = f"{e['auteur_prenom'] or ''} {e['auteur_nom'] or ''}".strip()
        writer.writerow([
            e['date_heure'] or '',
            auteur,
            ACTIONS_LABELS.get(e['action'], e['action']),
            _cible_lisible(e),
            e['details'] or '',
            e['adresse_ip'] or '',
        ])

    nom_fichier = f"journal_actions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename={nom_fichier}'},
    )
