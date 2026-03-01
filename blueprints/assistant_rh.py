"""
Blueprint assistant_rh_bp.
Chatbot IA assistant RH : questions sur la CCN ALISFA, le droit du travail, etc.
Chaque réponse inclut un % de recommandation de consultation d'avocat.
Accès : directeur, comptable.
"""
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
import json
from utils import login_required
from blueprints.pesee_alisfa import call_ai
from blueprints.api_keys import get_available_models

assistant_rh_bp = Blueprint('assistant_rh_bp', __name__)

PROFILS_AUTORISES = ['directeur', 'comptable']

SYSTEM_PROMPT = """Tu es un assistant RH expert en droit du travail français et en Convention Collective Nationale ALISFA (Acteurs du Lien Social et Familial).

RÈGLES IMPÉRATIVES :
1. Tu réponds TOUJOURS en français.
2. Tu donnes des réponses précises, sourcées quand possible (articles du Code du travail, articles de la CCN ALISFA).
3. Tu n'es PAS avocat. Tu fournis des orientations et informations générales, pas des conseils juridiques.
4. Tu dois TOUJOURS évaluer le risque juridique de la situation et donner un pourcentage de recommandation de consulter un avocat.

Tu DOIS répondre STRICTEMENT au format JSON suivant :
{
  "reponse": "Ta réponse détaillée ici en texte riche avec des retours à la ligne. Utilise des tirets pour les listes.",
  "sources": ["Article L1234-5 du Code du travail", "Article 15.2 de la CCN ALISFA"],
  "recommandation_avocat_pct": 42,
  "motif_recommandation": "Explication courte de pourquoi ce % (ex: situation simple et bien encadrée par la convention)"
}

Le champ recommandation_avocat_pct est un entier entre 0 et 100 :
- 0-20% : Question d'information générale, bien encadrée
- 20-50% : Situation courante mais avec nuances possibles
- 50-75% : Situation complexe, interprétation variable
- 75-100% : Risque de contentieux, situation sensible, licenciement, harcèlement, discrimination

Domaines de compétence :
- CCN ALISFA : grille de classification, pesée de poste, rémunération, congés conventionnels, formation
- Droit du travail : contrats, durée du travail, heures supplémentaires, congés, rupture de contrat
- Gestion RH : entretiens professionnels, formation, GPEC, sanctions disciplinaires
- Relations sociales : CSE, représentants du personnel, négociation collective
"""


@assistant_rh_bp.route('/assistant_rh')
@login_required
def assistant_rh():
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    models = get_available_models()
    has_key = len(models) > 0
    return render_template('assistant_rh.html', available_models=models, has_api_key=has_key)


@assistant_rh_bp.route('/api/assistant_rh/chat', methods=['POST'])
@login_required
def api_chat():
    if session.get('profil') not in PROFILS_AUTORISES:
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json()
    messages = data.get('messages', [])
    model = data.get('model', 'gpt-4o')

    if not messages:
        return jsonify({'error': 'Aucun message'}), 400

    # Construire la conversation avec le system prompt
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    try:
        raw = call_ai(full_messages, model)
        # Parser le JSON
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            # Si le modèle n'a pas retourné du JSON valide, on essaie d'extraire
            result = {
                "reponse": raw,
                "sources": [],
                "recommandation_avocat_pct": 50,
                "motif_recommandation": "Réponse non structurée — recommandation par défaut",
            }
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
