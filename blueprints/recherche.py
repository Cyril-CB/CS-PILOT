"""
Blueprint recherche_bp — API de la barre de recherche intelligente.

POST /api/search {query} → verdict de routage (redirect | choices | none).
POST /api/search/suggestions {query} → pages et enregistrements déjà classés.

La recherche métier est ouverte aux responsables depuis que les entités et les
destinations sont filtrées sur leur périmètre. La route de suggestions reste
ouverte à tout utilisateur connecté : les autres profils n'y reçoivent que leur
carte de navigation, déjà filtrée par leurs droits.
CSRF est injecté automatiquement par base.html.
"""
import logging

from flask import Blueprint, request, session, jsonify
from database import get_db
from utils import login_required, aujourd_hui, maintenant
from search_engine import analyser_recherche, anonymiser_terme_salaries
from search_palette import construire_suggestions

recherche_bp = Blueprint('recherche_bp', __name__)

logger = logging.getLogger(__name__)

PROFILS_AUTORISES = ('directeur', 'comptable', 'responsable')


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
    query = (data.get('query') or '').strip()[:200]

    conn = get_db()
    try:
        from interface_flux import (carte_pour_utilisateur,
                                    endpoints_recherche_autorises)
        profil = session.get('profil')
        user_id = session.get('user_id')
        carte = carte_pour_utilisateur(profil, user_id)
        verdict = analyser_recherche(
            conn, query, profil, aujourd_hui(), user_id=user_id,
            endpoints_autorises=endpoints_recherche_autorises(
                profil, user_id, carte),
        )
        if query:
            _journaliser_recherche(conn, query, verdict)
    finally:
        conn.close()

    return jsonify(verdict)


@recherche_bp.route('/api/search/suggestions', methods=['POST'])
@login_required
def api_search_suggestions():
    """Retourne une palette unifiée sans journaliser les frappes intermédiaires."""
    data = request.get_json(silent=True) or {}
    query = (data.get('query') or '').strip()[:200]
    profil = session.get('profil')
    user_id = session.get('user_id')

    from interface_flux import (carte_pour_utilisateur,
                                endpoints_recherche_autorises,
                                recherche_globale_autorisee)
    carte = carte_pour_utilisateur(profil, user_id)
    verdict = None
    if query and recherche_globale_autorisee(profil):
        conn = get_db()
        try:
            verdict = analyser_recherche(
                conn, query, profil, aujourd_hui(), user_id=user_id,
                endpoints_autorises=endpoints_recherche_autorises(
                    profil, user_id, carte),
            )
        finally:
            conn.close()

    return jsonify({'suggestions': construire_suggestions(carte, query, verdict)})
