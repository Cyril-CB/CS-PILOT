"""
Blueprint recherche_bp — API de la barre de recherche intelligente.

POST /api/search {query} → verdict de routage (redirect | choices | none).
POST /api/search/suggestions {query} → pages et enregistrements déjà classés.

La recherche métier est ouverte aux responsables depuis que les entités et les
destinations sont filtrées sur leur périmètre. La route de suggestions reste
ouverte à tout utilisateur connecté : les autres profils n'y reçoivent que leur
carte de navigation, déjà filtrée par leurs droits.

Le journal de recherche est alimenté par les deux routes, jamais à la frappe :
`/api/search` trace le résultat métier effectivement ouvert, `/api/search/
suggestions` trace la recherche restée vaine que l'utilisateur abandonne.
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

# Longueur minimale d'une recherche vaine pour être journalisée. La barre
# s'ouvre dès la première touche frappée n'importe où sur la page : une frappe
# accidentelle suivie d'Échap ne dit rien du vocabulaire attendu.
LONGUEUR_MIN_JOURNAL = 3


def _lire_query_json():
    """Lit une requête JSON objet contenant une chaîne `query`, sinon None."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None
    query = data.get('query', '')
    if not isinstance(query, str):
        return None
    return query.strip()[:200]


def _journal_demande():
    """Le client signale-t-il une recherche abandonnée, à tracer une fois ?"""
    data = request.get_json(silent=True)
    return isinstance(data, dict) and data.get('journal') is True


def _resultat_precis(suggestions):
    """La palette a-t-elle proposé autre chose que la vue d'ensemble ?

    La vue d'ensemble est toujours ajoutée en dernier ; elle ne répond à aucune
    saisie en particulier. Si elle est seule, la recherche n'a rien donné.
    """
    return any(s.get('action') != 'ensemble' for s in suggestions)


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

    query = _lire_query_json()
    if query is None:
        return jsonify({
            'type': 'none', 'message': 'Requête JSON invalide', 'exemples': [],
        }), 400

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
    """Palette unifiée. Aucune frappe n'est tracée, les recherches vaines si.

    Le journal de recherche existe pour repérer le vocabulaire qui manque au
    moteur : ce sont donc les saisies restées sans réponse qui l'intéressent le
    plus. Le client ne demande la journalisation qu'une fois, au moment où
    l'utilisateur referme la barre sur une recherche vaine. Le serveur revérifie
    que la palette était bien vide : ce chemin ne peut enregistrer que des
    échecs, jamais un faux succès.
    """
    query = _lire_query_json()
    if query is None:
        return jsonify({
            'suggestions': [], 'error': 'Requête JSON invalide',
        }), 400
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

    suggestions = construire_suggestions(carte, query, verdict)

    if (_journal_demande() and len(query) >= LONGUEUR_MIN_JOURNAL
            and not _resultat_precis(suggestions)):
        conn = get_db()
        try:
            _journaliser_recherche(conn, query, {
                'type': 'none',
                'message': (verdict or {}).get('message') or 'Aucune correspondance',
            })
        finally:
            conn.close()

    return jsonify({'suggestions': suggestions})
