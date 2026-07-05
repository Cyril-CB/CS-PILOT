"""
Blueprint recherche_bp — API de la barre de recherche intelligente.

POST /api/search {query} → verdict de routage (redirect | choices | none),
calculé par le moteur pur search_engine.analyser_recherche. Accès réservé à la
direction et à la comptabilité (comme les tableaux de bord qui l'affichent).
CSRF est injecté automatiquement par base.html.
"""
import logging

from flask import Blueprint, request, session, jsonify
from database import get_db
from utils import login_required, aujourd_hui, maintenant
from search_engine import analyser_recherche, anonymiser_terme_salaries

recherche_bp = Blueprint('recherche_bp', __name__)

logger = logging.getLogger(__name__)

PROFILS_AUTORISES = ('directeur', 'comptable')


def _journaliser_recherche(conn, terme, verdict):
    """Trace la recherche (terme + a-t-elle abouti) — best-effort, jamais bloquant.

    Une redirection ou une liste de choix comptent comme un résultat ; un verdict
    « none » (aucune correspondance) est enregistré comme sans résultat. Le terme
    et le libellé de destination sont anonymisés (noms de salariés → « salarié »)
    pour ne pas révéler quels salariés font l'objet de recherches. Toute erreur de
    journalisation reste silencieuse : elle ne doit pas casser la recherche.
    """
    try:
        type_resultat = verdict.get('type', '')
        a_resultat = 1 if type_resultat in ('redirect', 'choices') else 0
        libelle = verdict.get('label') or verdict.get('prompt') or verdict.get('message') or ''
        terme = anonymiser_terme_salaries(conn, terme)
        libelle = anonymiser_terme_salaries(conn, libelle)
        conn.execute(
            'INSERT INTO recherche_log (date_heure, user_id, terme, type_resultat, a_resultat, libelle) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (maintenant().strftime('%Y-%m-%d %H:%M:%S'), session.get('user_id'),
             terme[:200], type_resultat, a_resultat, libelle[:200]),
        )
        conn.commit()
    except Exception:
        logger.exception("Impossible de journaliser la recherche")


@recherche_bp.route('/api/search', methods=['POST'])
@login_required
def api_search():
    if session.get('profil') not in PROFILS_AUTORISES:
        return jsonify({'type': 'none', 'message': 'Accès non autorisé', 'exemples': []}), 403

    data = request.get_json(silent=True) or {}
    query = (data.get('query') or '').strip()

    conn = get_db()
    try:
        verdict = analyser_recherche(conn, query, session.get('profil'), aujourd_hui())
        if query:
            _journaliser_recherche(conn, query, verdict)
    finally:
        conn.close()

    return jsonify(verdict)
