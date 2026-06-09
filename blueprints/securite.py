"""
Blueprint securite_bp - Journal des acces (securite).

Permet a la direction de consulter le journal des connexions a l'application :
connexions reussies, echecs de connexion, demandes de reinitialisation et
modifications de mot de passe. Le journal peut etre consulte directement dans
l'interface ou telecharge au format CSV.

Accessible uniquement aux directeurs (la direction).
"""
import csv
import io
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for, session, flash,
    Response
)

from access_log import EVENEMENTS_LABELS
from database import get_db
from utils import login_required

securite_bp = Blueprint('securite_bp', __name__)

# Nombre maximal d'entrees affichees a l'ecran (l'export CSV n'est pas limite)
LIMITE_AFFICHAGE = 500


def _check_direction():
    """Verifie que l'utilisateur connecte fait partie de la direction."""
    return session.get('profil') == 'directeur'


def _lire_filtres():
    """Recupere les filtres communs depuis la requete."""
    return {
        'evenement': request.args.get('evenement') or '',
        'date_debut': request.args.get('date_debut') or '',
        'date_fin': request.args.get('date_fin') or '',
        'recherche': (request.args.get('recherche') or '').strip(),
    }


def _construire_requete(filtres):
    """Construit la requete SQL filtree et la liste de parametres associee."""
    query = '''
        SELECT j.id, j.date_heure, j.login_saisi, j.evenement, j.adresse_ip,
               u.nom AS nom, u.prenom AS prenom
        FROM journal_acces j
        LEFT JOIN users u ON j.user_id = u.id
        WHERE 1=1
    '''
    params = []

    if filtres['evenement'] and filtres['evenement'] in EVENEMENTS_LABELS:
        query += ' AND j.evenement = ?'
        params.append(filtres['evenement'])
    if filtres['date_debut']:
        query += ' AND date(j.date_heure) >= date(?)'
        params.append(filtres['date_debut'])
    if filtres['date_fin']:
        query += ' AND date(j.date_heure) <= date(?)'
        params.append(filtres['date_fin'])
    if filtres['recherche']:
        like = f"%{filtres['recherche']}%"
        query += ' AND (j.login_saisi LIKE ? OR u.nom LIKE ? OR u.prenom LIKE ?)'
        params.extend([like, like, like])

    return query, params


@securite_bp.route('/securite/journal-acces')
@login_required
def journal_acces():
    """Affiche le journal des acces (direction uniquement)."""
    if not _check_direction():
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    filtres = _lire_filtres()
    query, params = _construire_requete(filtres)
    query += ' ORDER BY j.date_heure DESC, j.id DESC LIMIT ?'
    params.append(LIMITE_AFFICHAGE)

    conn = get_db()
    try:
        entrees = conn.execute(query, params).fetchall()
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
    if not _check_direction():
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    filtres = _lire_filtres()
    query, params = _construire_requete(filtres)
    query += ' ORDER BY j.date_heure DESC, j.id DESC'

    conn = get_db()
    try:
        entrees = conn.execute(query, params).fetchall()
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
