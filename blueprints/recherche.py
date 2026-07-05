"""
Blueprint recherche_bp — API de la barre de recherche intelligente.

POST /api/search {query} → verdict de routage (redirect | choices | none),
calculé par le moteur pur search_engine.analyser_recherche. Accès réservé à la
direction et à la comptabilité (comme les tableaux de bord qui l'affichent).
CSRF est injecté automatiquement par base.html.
"""
from flask import Blueprint, request, session, jsonify
from database import get_db
from utils import login_required, aujourd_hui
from search_engine import analyser_recherche

recherche_bp = Blueprint('recherche_bp', __name__)

PROFILS_AUTORISES = ('directeur', 'comptable')


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
    finally:
        conn.close()

    return jsonify(verdict)
