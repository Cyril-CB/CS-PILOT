"""
Blueprint pesee_alisfa_bp.
Module d'analyse de fiches de poste selon la classification CCN ALISFA.
- Clés API gérées via la page Administration > Clés API
- Support multi-fournisseurs : OpenAI, Google Gemini, Anthropic Claude
- Analyse en 2 passes : extraction factuelle + cotation
- Température 0 + seed fixe pour reproductibilité
- Verrouillage par critère et ré-analyse partielle
Accès : directeur, comptable.
"""
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
import json
import os
import tempfile
import requests as http_requests
from database import get_db
from utils import login_required, get_setting

pesee_alisfa_bp = Blueprint('pesee_alisfa_bp', __name__)

PROFILS_AUTORISES = ['directeur', 'comptable']


# ── Familles de métiers et emplois repères CCN ALISFA ──

FAMILLES_METIERS = [
    'Animation sociale et socioculturelle',
    'Petite enfance',
    'Encadrement et direction',
    'Administratif et financier',
    'Services et technique',
]

# Emplois repères CCN ALISFA avec bornes min/max par critère (ordre des 8 critères)
# bornes[i] = [niveau_min, niveau_max] pour le critère i
EMPLOIS_REPERES = {
    'Animation sociale et socioculturelle': [
        {'nom': "Animateur·trice d'activité",
         'bornes': [[1,2],[1,2],[1,2],[2,2],[1,2],[1,2],[1,3],[1,2]]},
        {'nom': 'Animateur·trice',
         'bornes': [[3,4],[2,3],[2,3],[2,5],[2,4],[1,3],[2,3],[2,3]]},
        {'nom': 'Intervenant·e social·e',
         'bornes': [[3,5],[2,5],[2,3],[3,5],[1,5],[1,3],[1,2],[3,4]]},
        {'nom': 'Intervenant·e spécialisé·e',
         'bornes': [[2,5],[1,3],[1,4],[1,3],[1,2],[1,3],[1,3],[1,2]]},
    ],
    'Petite enfance': [
        {'nom': 'Animation petite enfance',
         'bornes': [[1,2],[1,2],[1,2],[2,2],[1,2],[1,2],[1,2],[1,3]]},
        {'nom': 'Accompagnement petite enfance et parentalité',
         'bornes': [[3,5],[2,3],[1,3],[2,3],[1,2],[1,2],[1,3],[1,3]]},
        {'nom': 'Éducation petite enfance',
         'bornes': [[4,5],[2,5],[1,4],[2,5],[1,4],[1,3],[2,3],[2,3]]},
    ],
    'Encadrement et direction': [
        {'nom': 'Coordinateur·trice / Encadrement',
         'bornes': [[3,5],[4,6],[3,4],[2,5],[2,5],[1,5],[2,3],[2,4]]},
        {'nom': 'Directeur·trice / Cadre fédéral·e',
         'bornes': [[5,6],[6,8],[4,6],[1,5],[5,8],[4,8],[3,6],[4,5]]},
    ],
    'Administratif et financier': [
        {'nom': 'Assistant·e de gestion ou de direction',
         'bornes': [[3,5],[2,5],[2,3],[1,2],[1,2],[1,3],[1,2],[1,3]]},
        {'nom': 'Personnel administratif ou financier',
         'bornes': [[3,5],[3,5],[2,3],[1,1],[2,5],[1,3],[1,2],[1,3]]},
        {'nom': "Chargé·e d'accueil",
         'bornes': [[1,3],[1,4],[1,2],[2,3],[1,2],[1,2],[1,3],[1,2]]},
        {'nom': 'Secrétaire',
         'bornes': [[2,4],[1,3],[1,2],[1,2],[1,2],[1,3],[1,2],[1,2]]},
    ],
    'Services et technique': [
        {'nom': 'Personnel de maintenance, de cuisine et de service',
         'bornes': [[1,3],[1,3],[1,2],[1,2],[1,4],[1,3],[1,3],[1,2]]},
        {'nom': 'Personnel médical et paramédical',
         'bornes': [[2,7],[3,7],[2,6],[2,5],[1,7],[1,8],[2,6],[1,5]]},
    ],
}

# Clés des critères dans la table postes_alisfa (ordre = CRITERES_ALISFA)
CRITERE_FIELDS = [
    'formation_niveau',
    'complexite_niveau',
    'autonomie_niveau',
    'relationnel_niveau',
    'finances_niveau',
    'rh_niveau',
    'securite_niveau',
    'projet_niveau',
]


# ── Classification ALISFA ──

CRITERES_ALISFA = [
    {
        "nom": "Formation requise",
        "niveaux": [
            {"niveau": 1, "label": "Pas de diplôme ou certification requis", "points": "SSC"},
            {"niveau": 2, "label": "Diplômes niveau 3 (CAP, BEP)", "points": 5},
            {"niveau": 3, "label": "Diplômes niveau 4 (Bac)", "points": 15},
            {"niveau": 4, "label": "Diplômes niveau 5 (Bac+2)", "points": 35},
            {"niveau": 5, "label": "Diplômes niveau 6 (Bac+3/4)", "points": 55},
            {"niveau": 6, "label": "Diplômes niveau 7 (Bac+5)", "points": 90},
            {"niveau": 7, "label": "Diplômes niveau 8+ (Doctorat)", "points": 120},
        ]
    },
    {
        "nom": "Complexité de l'emploi",
        "niveaux": [
            {"niveau": 1, "label": "Modes opératoires connus et réguliers", "points": "SSC"},
            {"niveau": 2, "label": "Adaptation régulière, trouver des solutions", "points": 5},
            {"niveau": 3, "label": "Analyse de processus, un domaine d'activité", "points": 15},
            {"niveau": 4, "label": "Analyse de processus, plusieurs domaines", "points": 30},
            {"niveau": 5, "label": "Force de propositions, plusieurs domaines", "points": 45},
            {"niveau": 6, "label": "Analyser, concevoir, coordonner des domaines", "points": 65},
            {"niveau": 7, "label": "Maîtrise ou expertise, démarche stratégique", "points": 80},
            {"niveau": 8, "label": "Expertise plusieurs domaines, évolutions stratégiques", "points": 110},
        ]
    },
    {
        "nom": "Autonomie",
        "niveaux": [
            {"niveau": 1, "label": "Demandes directes et précises, vérif procédures", "points": "SSC"},
            {"niveau": 2, "label": "Domaine(s) d'activité, vérif résultats/délais", "points": 5},
            {"niveau": 3, "label": "Gestion avec objectifs fixés, points d'étapes", "points": 15},
            {"niveau": 4, "label": "Pilotage projet entreprise, points d'étapes", "points": 25},
            {"niveau": 5, "label": "Pilotage projet établissement, bilans intermédiaires", "points": 35},
            {"niveau": 6, "label": "Gestion stratégique entreprise, instances politiques", "points": 55},
        ]
    },
    {
        "nom": "Dimensions relationnelles avec le public accueilli",
        "niveaux": [
            {"niveau": 1, "label": "Contacts ponctuels", "points": "SSC"},
            {"niveau": 2, "label": "Échanges réguliers", "points": 1},
            {"niveau": 3, "label": "Accompagnement du public", "points": 7},
            {"niveau": 4, "label": "Mobilisation au projet", "points": 18},
            {"niveau": 5, "label": "Gestion situations complexes", "points": 30},
        ]
    },
    {
        "nom": "Responsabilités financières",
        "niveaux": [
            {"niveau": 1, "label": "Pas de responsabilités financières", "points": "SSC"},
            {"niveau": 2, "label": "Caisse et/ou achats courants", "points": 2},
            {"niveau": 3, "label": "Suivi et exécution d'un budget", "points": 10},
            {"niveau": 4, "label": "Gestion budget un domaine", "points": 20},
            {"niveau": 5, "label": "Construction et gestion plusieurs domaines", "points": 40},
            {"niveau": 6, "label": "Construction et gestion entreprise/établissement", "points": 50},
            {"niveau": 7, "label": "Budget + financements structurels", "points": 55},
            {"niveau": 8, "label": "Budget consolidé + financements structurels", "points": 60},
        ]
    },
    {
        "nom": "Responsabilités dans la gestion des ressources humaines",
        "niveaux": [
            {"niveau": 1, "label": "Pas de responsabilités RH", "points": "SSC"},
            {"niveau": 2, "label": "Suivi exécution travail d'une équipe", "points": 10},
            {"niveau": 3, "label": "Gestion partielle RH partie équipe", "points": 20},
            {"niveau": 4, "label": "Gestion partielle RH ensemble entreprise", "points": 25},
            {"niveau": 5, "label": "Gestion ensemble RH établissement/entreprise", "points": 30},
            {"niveau": 6, "label": "Politique RH < 20 ETP", "points": 40},
            {"niveau": 7, "label": "Politique RH 20-49 ETP", "points": 50},
            {"niveau": 8, "label": "Politique RH ≥ 50 ETP", "points": 60},
        ]
    },
    {
        "nom": "Sécurité des personnes et des matériels",
        "niveaux": [
            {"niveau": 1, "label": "Participation individuelle sécurité générale", "points": "SSC"},
            {"niveau": 2, "label": "Responsabilité matériels public et sécurité activité", "points": 5},
            {"niveau": 3, "label": "Responsabilité matériels entreprise et sécurité", "points": 20},
            {"niveau": 4, "label": "Responsabilité sécurité établissement", "points": 35},
            {"niveau": 5, "label": "Responsabilité entreprise < 50 ETP", "points": 50},
            {"niveau": 6, "label": "Responsabilité entreprise ≥ 50 ETP ou multi-sites", "points": 70},
        ]
    },
    {
        "nom": "Contribution au projet de l'entreprise",
        "niveaux": [
            {"niveau": 1, "label": "Contribue au bon fonctionnement", "points": "SSC"},
            {"niveau": 2, "label": "Participe à mise en œuvre d'actions", "points": 10},
            {"niveau": 3, "label": "Participe élaboration et réussite projet", "points": 20},
            {"niveau": 4, "label": "Pilotage d'un projet agréé", "points": 30},
            {"niveau": 5, "label": "Pilotage projet entreprise", "points": 45},
        ]
    },
]


def build_criteres_description():
    """Construit la description textuelle des critères pour le prompt."""
    lines = []
    for c in CRITERES_ALISFA:
        lines.append(f"\n{c['nom']}:")
        for n in c['niveaux']:
            lines.append(f"  Niveau {n['niveau']}: {n['label']} ({n['points']} points)")
    return "\n".join(lines)


def _get_bornes_for_emploi(famille, emploi_nom):
    """Retourne les bornes [min,max] par critère pour un emploi repère."""
    emplois = EMPLOIS_REPERES.get(famille, [])
    for e in emplois:
        if e['nom'] == emploi_nom:
            return e['bornes']
    return None


def _build_bornes_text(bornes):
    """Construit le texte des contraintes de bornes pour le prompt."""
    if not bornes:
        return ""
    noms = [c['nom'] for c in CRITERES_ALISFA]
    lines = []
    for i, nom in enumerate(noms):
        bmin, bmax = bornes[i]
        lines.append(f"  - {nom} : niveau {bmin} a {bmax}")
    return "\n".join(lines)


def extract_pdf_text(file_storage):
    """Extrait le texte d'un PDF uploadé."""
    import pdfplumber
    text = ""
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
        file_storage.save(tmp.name)
        tmp_path = tmp.name

    try:
        with pdfplumber.open(tmp_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    finally:
        os.unlink(tmp_path)

    return text.strip()


def _get_api_key_for_model(model):
    """Récupère la clé API correspondant au modèle choisi."""
    from blueprints.api_keys import get_provider_for_model, AI_PROVIDERS
    provider_id = get_provider_for_model(model)
    if not provider_id:
        return None, None
    key_setting = AI_PROVIDERS[provider_id]['key_setting']
    api_key = get_setting(key_setting)
    return provider_id, api_key


def call_openai(api_key, messages, model="gpt-4o"):
    """Appel API OpenAI avec température 0 et seed fixe."""
    is_reasoning = model.startswith("o3") or model.startswith("o1")

    payload = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "max_completion_tokens": 8000,
    }
    # Les modèles o3/o1 ne supportent pas temperature ni seed
    if not is_reasoning:
        payload["temperature"] = 0
        payload["seed"] = 42

    resp = http_requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )
    if resp.status_code != 200:
        error_msg = resp.json().get('error', {}).get('message', resp.text[:200])
        raise Exception(f"Erreur API OpenAI ({resp.status_code}): {error_msg}")

    return resp.json()['choices'][0]['message']['content']


def call_groq(api_key, messages, model="llama-3.3-70b-versatile"):
    """Appel API Groq (compatible OpenAI) avec température 0."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "seed": 42,
        "response_format": {"type": "json_object"},
        "max_tokens": 8000,
    }

    resp = http_requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )
    if resp.status_code != 200:
        error_msg = resp.text[:300]
        try:
            error_msg = resp.json().get('error', {}).get('message', error_msg)
        except Exception:
            pass
        raise Exception(f"Erreur API Groq ({resp.status_code}): {error_msg}")

    return resp.json()['choices'][0]['message']['content']


def call_anthropic(api_key, messages, model="claude-sonnet-4-5-20250929"):
    """Appel API Anthropic Claude avec température 0."""
    # Séparer le system message des user messages
    system_text = ""
    user_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_text += msg["content"] + "\n"
        else:
            user_messages.append(msg)

    # Si pas de messages user séparés, tout est dans un seul message user
    if not user_messages:
        user_messages = messages

    payload = {
        "model": model,
        "max_tokens": 8000,
        "temperature": 0,
        "messages": user_messages,
    }
    if system_text.strip():
        payload["system"] = system_text.strip()

    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }

    resp = http_requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload,
        timeout=120,
    )
    if resp.status_code != 200:
        error_detail = resp.text[:300]
        try:
            error_detail = resp.json().get('error', {}).get('message', error_detail)
        except Exception:
            pass
        raise Exception(f"Erreur API Anthropic ({resp.status_code}): {error_detail}")

    result = resp.json()
    return result['content'][0]['text']


def _extract_json_from_response(raw):
    """Extrait le JSON d'une réponse IA, même enveloppée dans des backticks markdown."""
    import re
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Bloc ```json ... ``` ou ``` ... ```
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    # Premier { ... } englobant
    start = raw.find('{')
    end = raw.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise json.JSONDecodeError("Impossible d'extraire du JSON de la réponse", raw, 0)


def call_ai(messages, model="gpt-4o"):
    """Dispatcher : appelle le bon fournisseur en fonction du modèle choisi."""
    provider_id, api_key = _get_api_key_for_model(model)

    if not provider_id:
        raise Exception(f"Modèle inconnu : {model}")
    if not api_key:
        raise Exception(f"Clé API non configurée pour le fournisseur du modèle {model}. "
                        "Allez dans Administration > Clés API pour la configurer.")

    if provider_id == 'openai':
        return call_openai(api_key, messages, model)
    elif provider_id == 'groq':
        return call_groq(api_key, messages, model)
    elif provider_id == 'anthropic':
        return call_anthropic(api_key, messages, model)
    else:
        raise Exception(f"Fournisseur non supporté : {provider_id}")


# ── Correction certitude côté serveur ──

# Mapping : champ extraction → critère(s) ALISFA impacté(s)
_EXTRACTION_TO_CRITERE = {
    'diplome_requis': ['Formation requise'],
    'complexite_taches': ["Complexité de l'emploi"],
    'nb_domaines_activite': ["Complexité de l'emploi"],
    'niveau_autonomie': ['Autonomie'],
    'type_reporting': ['Autonomie'],
    'relation_public': ['Dimensions relationnelles avec le public accueilli'],
    'responsabilites_budget': ['Responsabilités financières'],
    'perimetre_budget': ['Responsabilités financières'],
    'nb_personnes_encadrees': ['Responsabilités dans la gestion des ressources humaines'],
    'perimetre_encadrement': ['Responsabilités dans la gestion des ressources humaines'],
    'responsabilite_securite': ['Sécurité des personnes et des matériels'],
    'contribution_projet': ["Contribution au projet de l'entreprise"],
}


def _is_missing(value):
    """Vérifie si une valeur d'extraction est absente ou vague."""
    if not value:
        return True
    v = str(value).lower().strip()
    return v in ('', 'non mentionné', 'non renseigné', 'non précisé',
                 'non spécifié', 'absent', 'aucun', 'aucune', 'n/a', 'na',
                 'pas mentionné', 'non indiqué', 'non défini', 'inconnu')


def _correct_certainties(extraction, cotation):
    """Post-traitement : plafonne les certitudes si l'extraction manque d'info."""
    if not extraction or not cotation or 'criteres' not in cotation:
        return cotation

    # 1. Identifier les critères dont les champs source sont manquants
    criteres_penalises = {}
    for champ, criteres_noms in _EXTRACTION_TO_CRITERE.items():
        val = extraction.get(champ)
        if _is_missing(val):
            for nom in criteres_noms:
                if nom not in criteres_penalises:
                    criteres_penalises[nom] = []
                criteres_penalises[nom].append(champ)

    # 2. Appliquer les plafonds
    alertes_ajoutees = []
    for c in cotation['criteres']:
        nom = c.get('nom', '')
        champs_manquants = criteres_penalises.get(nom, [])

        if champs_manquants:
            # Plafonner à 50% si info manquante
            if c.get('certitude', 0) > 50:
                ancien = c['certitude']
                c['certitude'] = 50
                champs_str = ', '.join(f.replace('_', ' ') for f in champs_manquants)
                c['justification'] = (
                    c.get('justification', '') +
                    f" ⚠️ [Correction auto] Certitude réduite de {ancien}% à 50% "
                    f"car l'information source est absente ({champs_str})."
                )
                alertes_ajoutees.append(
                    f"{nom} : certitude corrigée ({ancien}% → 50%) — "
                    f"information manquante dans la fiche ({champs_str})"
                )

    # 3. Vérifier la cohérence globale
    certitudes = [c.get('certitude', 0) for c in cotation['criteres']]

    # Interdire : tous les critères > 80%
    nb_high = sum(1 for c in certitudes if c > 80)
    if nb_high >= 7:
        for c in cotation['criteres']:
            if c.get('certitude', 0) > 80 and c['nom'] not in criteres_penalises:
                c['certitude'] = min(c['certitude'], 80)
        alertes_ajoutees.append(
            "Certitudes globalement trop élevées — plafonnées à 80% par cohérence."
        )

    # 4. Recalculer la certitude globale = moyenne réelle
    certitudes = [c.get('certitude', 0) for c in cotation['criteres']]
    cotation['certitude_globale'] = round(sum(certitudes) / len(certitudes)) if certitudes else 0

    # 5. Ajouter les alertes
    if alertes_ajoutees:
        existing = cotation.get('alertes', []) or []
        cotation['alertes'] = existing + alertes_ajoutees

    return cotation


def _enforce_bornes(cotation, bornes):
    """Clampe les niveaux aux bornes CCN et recalcule les points."""
    if not bornes or 'criteres' not in cotation:
        return cotation

    noms_criteres = [c['nom'] for c in CRITERES_ALISFA]
    alertes_bornes = []

    for crit in cotation['criteres']:
        nom = crit.get('nom', '')
        if nom in noms_criteres:
            idx = noms_criteres.index(nom)
            bmin, bmax = bornes[idx]
            niveau = crit.get('niveau', 1)

            if niveau < bmin or niveau > bmax:
                ancien = niveau
                niveau_corrige = max(bmin, min(bmax, niveau))
                crit['niveau'] = niveau_corrige

                # Recalculer points et label
                for n in CRITERES_ALISFA[idx]['niveaux']:
                    if n['niveau'] == niveau_corrige:
                        crit['points'] = n['points'] if isinstance(n['points'], int) else 0
                        crit['label_niveau'] = n['label']
                        break

                direction = "au-dessus" if ancien > bmax else "en-dessous"
                alertes_bornes.append(
                    f"{nom} : niveau {ancien} corrige a {niveau_corrige} "
                    f"(bornes CCN {bmin}-{bmax}, l'IA avait evalue {direction})"
                )

    if alertes_bornes:
        existing = cotation.get('alertes', []) or []
        cotation['alertes'] = existing + alertes_bornes

        # Recalculer total
        total = 0
        for crit in cotation['criteres']:
            pts = crit.get('points', 0)
            total += pts if isinstance(pts, int) else 0
        cotation['total_points'] = total

    return cotation


# ── Helpers postes ──

def _get_points_for_niveau(critere_index, niveau):
    """Retourne les points pour un critère et un niveau donnés."""
    critere = CRITERES_ALISFA[critere_index]
    for n in critere['niveaux']:
        if n['niveau'] == niveau:
            return n['points'] if isinstance(n['points'], int) else 0
    return 0


def _calculer_total_points_from_niveaux(niveaux_dict):
    """Calcule le total de points à partir des niveaux choisis."""
    total = 0
    for i, field in enumerate(CRITERE_FIELDS):
        niveau = niveaux_dict.get(field, 1)
        total += _get_points_for_niveau(i, niveau)
    return total


# ── Routes ──

@pesee_alisfa_bp.route('/pesee_alisfa')
@login_required
def pesee_alisfa():
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    from blueprints.api_keys import get_available_models
    available_models = get_available_models()
    has_key = len(available_models) > 0
    return render_template('pesee_alisfa.html',
                           has_api_key=has_key,
                           available_models=available_models,
                           criteres=CRITERES_ALISFA,
                           familles=FAMILLES_METIERS,
                           emplois_reperes=EMPLOIS_REPERES)


@pesee_alisfa_bp.route('/postes_alisfa')
@login_required
def postes_alisfa():
    """Page de gestion des postes ALISFA + vue salariés."""
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    postes = conn.execute(
        'SELECT * FROM postes_alisfa ORDER BY famille_metier, intitule'
    ).fetchall()
    salaries_rows = conn.execute('''
        SELECT u.id, u.nom, u.prenom, u.profil, u.pesee,
               COALESCE(s.nom, '') AS secteur_nom
        FROM users u
        LEFT JOIN secteurs s ON u.secteur_id = s.id
        WHERE u.actif = 1 AND u.profil != 'prestataire'
        ORDER BY u.pesee DESC NULLS LAST, u.nom, u.prenom
    ''').fetchall()
    conn.close()
    salaries = [dict(r) for r in salaries_rows]

    return render_template('postes_alisfa.html',
                           criteres=CRITERES_ALISFA,
                           familles=FAMILLES_METIERS,
                           emplois_reperes=EMPLOIS_REPERES,
                           critere_fields=CRITERE_FIELDS,
                           postes=postes,
                           salaries=salaries)


@pesee_alisfa_bp.route('/api/pesee_alisfa/analyze', methods=['POST'])
@login_required
def api_analyze():
    """Analyse en 2 passes : extraction factuelle + cotation ALISFA."""
    if session.get('profil') not in PROFILS_AUTORISES:
        return jsonify({'error': 'Accès non autorisé'}), 403

    model = request.form.get('model', 'gpt-4o')

    # Vérifier que le modèle a une clé configurée
    provider_id, api_key = _get_api_key_for_model(model)
    if not api_key:
        return jsonify({'error': 'Clé API non configurée pour ce modèle. '
                        'Allez dans Administration > Clés API pour la configurer.'}), 400

    pdf_file = request.files.get('pdf')
    if not pdf_file or not pdf_file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Fichier PDF requis'}), 400

    nb_etp = request.form.get('nb_etp', '')
    budget = request.form.get('budget', '')
    famille_metier = request.form.get('famille_metier', '')
    emploi_repere = request.form.get('emploi_repere', '')

    # Extraction texte du PDF
    try:
        pdf_text = extract_pdf_text(pdf_file)
    except Exception as e:
        return jsonify({'error': f'Impossible de lire le PDF: {str(e)}'}), 400

    if len(pdf_text) < 50:
        return jsonify({'error': 'Le PDF semble vide ou illisible (trop peu de texte extrait).'}), 400

    # Bornes CCN pour l'emploi repère sélectionné
    bornes = _get_bornes_for_emploi(famille_metier, emploi_repere)
    bornes_text = _build_bornes_text(bornes) if bornes else ""

    # ═══ PASSE 1 : Extraction factuelle ═══
    ctx_lines = []
    if nb_etp:
        ctx_lines.append(f"- ETP : {nb_etp}")
    if budget:
        ctx_lines.append(f"- Budget : {budget} EUR")
    if emploi_repere:
        ctx_lines.append(f"- Emploi repere : {emploi_repere} ({famille_metier})")
    ctx_block = "\n".join(ctx_lines) if ctx_lines else "Non renseigne"

    prompt_extraction = f"""Extrais les faits de cette fiche de poste. Reponds en JSON strict.

FICHE DE POSTE :
{pdf_text[:8000]}

CONTEXTE :
{ctx_block}

Pour chaque champ, cite ce que dit la fiche. Si absent, mets "non mentionne".

{{
  "intitule_poste": "",
  "diplome_requis": "diplome EXIGE (pas souhaite). Indique le niveau : CAP=3, Bac=4, Bac+2=5, Bac+3=6, Bac+5=7",
  "missions_principales": [],
  "nb_personnes_encadrees": "nombre exact ou non mentionne",
  "perimetre_encadrement": "equipe / service / etablissement / entreprise",
  "responsabilites_budget": "caisse / suivi / gestion / construction budgetaire",
  "perimetre_budget": "un domaine / plusieurs domaines / entreprise / consolide",
  "niveau_autonomie": "instructions directes / objectifs fixes / pilotage projet / gestion strategique",
  "type_reporting": "controle procedures / resultats / points etapes / bilans / instances",
  "relation_public": "contacts ponctuels / echanges reguliers / accompagnement / mobilisation / situations complexes",
  "complexite_taches": "description des taches les plus complexes",
  "nb_domaines_activite": "un / plusieurs",
  "responsabilite_securite": "activite / etablissement / entreprise / multi-sites",
  "contribution_projet": "fonctionnement / mise en oeuvre actions / elaboration projet / pilotage projet",
  "elements_remarquables": []
}}"""

    try:
        extraction_raw = call_ai([{"role": "user", "content": prompt_extraction}], model)
        extraction = _extract_json_from_response(extraction_raw)
    except json.JSONDecodeError:
        return jsonify({'error': 'Erreur de format dans la reponse IA (passe 1). Reessayez.'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    # ═══ PASSE 2 : Cotation ALISFA ═══
    criteres_desc = build_criteres_description()
    extraction_json = json.dumps(extraction, ensure_ascii=False, indent=2)

    bornes_block = ""
    if bornes_text:
        bornes_block = f"""
CONTRAINTES CCN — Emploi repere : {emploi_repere}
Les niveaux de cet emploi repere sont bornes par la CCN ALISFA.
Tu DOIS rester dans ces bornes. Si un fait semble justifier un niveau hors bornes, reste a la borne la plus proche et signale-le en alerte.
{bornes_text}
"""

    prompt_cotation = f"""Tu cotas une fiche de poste selon la CCN ALISFA (8 criteres).

FAITS EXTRAITS :
{extraction_json}

GRILLE DES 8 CRITERES :
{criteres_desc}
{bornes_block}
REGLES :
- Evalue chaque critere sur les faits uniquement.
- Doute entre 2 niveaux → choisis le niveau inferieur.
- "coordonner" ≠ "piloter" ≠ "gerer" : les termes exacts comptent.
- Formation : seul le diplome EXIGE compte.
- RH et securite : le nombre d'ETP determine les niveaux hauts.

CERTITUDE (qualite de l'info disponible) :
- 90-100% : fait explicite et chiffre.
- 70-89% : present mais implicite ou partiel.
- 50-69% : vague ou interpretable.
- 30-49% : absent ou tres insuffisant.
- Si "non mentionne" → certitude ≤ 50%.
- Hesitation entre 2 niveaux → certitude ≤ 65%.

Reponds en JSON :
{{
  "intitule_poste": "",
  "emploi_repere": "{emploi_repere}",
  "criteres": [
    {{"nom": "", "niveau": 1, "label_niveau": "", "points": 0, "certitude": 50, "justification": "Cite les faits. Explique pourquoi pas le niveau superieur."}}
  ],
  "total_points": 0,
  "certitude_globale": 0,
  "synthese": "",
  "alertes": []
}}"""

    try:
        cotation_raw = call_ai([{"role": "user", "content": prompt_cotation}], model)
        cotation = _extract_json_from_response(cotation_raw)
    except json.JSONDecodeError:
        return jsonify({'error': 'Erreur de format dans la reponse IA (passe 2). Reessayez.'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    # ═══ POST-TRAITEMENT : Correction certitude cote serveur ═══
    cotation = _correct_certainties(extraction, cotation)

    # Verifier les bornes cote serveur aussi
    if bornes:
        cotation = _enforce_bornes(cotation, bornes)

    # ═══ PASSE 3 : Diagnostic qualite de la fiche ═══
    cotation_json = json.dumps(cotation, ensure_ascii=False, indent=2)

    prompt_diagnostic = f"""Analyse la qualite de redaction de cette fiche de poste pour la classification ALISFA.
Tu ne remets pas en cause la pesee. Tu identifies ce qui manque ou est mal formule.

FAITS EXTRAITS :
{extraction_json}

PESEE :
{cotation_json}

TEXTE ORIGINAL :
{pdf_text[:6000]}

CONSIGNES :
- Distingue FOND (info absente) de FORME (info presente mais mal formulee).
- Pour chaque critere a certitude < 70%, propose une reformulation.
- Signale si la fiche decrit des TACHES au lieu de RESPONSABILITES.
- Identifie les termes faibles ("participer", "contribuer", "en lien avec") qui sous-evaluent le poste.

Reponds en JSON :
{{
  "diagnostic_global": "3-4 phrases : qualite, impact sur pesee, priorites",
  "points_forts": ["ce qui est bien redige"],
  "problemes_redaction": [
    {{"critere": "", "type": "fond ou forme", "probleme": "", "extrait_actuel": "", "suggestion": ""}}
  ],
  "termes_faibles": [
    {{"terme_actuel": "", "contexte": "", "terme_suggere": "", "impact_pesee": ""}}
  ],
  "recommandation_prioritaire": "La reformulation la plus impactante"
}}"""

    diagnostic = None
    try:
        diag_raw = call_ai([{"role": "user", "content": prompt_diagnostic}], model)
        diagnostic = _extract_json_from_response(diag_raw)
    except Exception as e:
        import traceback
        print(f"[PESEE ALISFA] Passe 3 diagnostic echouee: {e}")
        traceback.print_exc()
        diagnostic = None

    return jsonify({
        'extraction': extraction,
        'cotation': cotation,
        'diagnostic': diagnostic,
    })


@pesee_alisfa_bp.route('/api/pesee_alisfa/reanalyze', methods=['POST'])
@login_required
def api_reanalyze():
    """Ré-analyse uniquement les critères déverrouillés."""
    if session.get('profil') not in PROFILS_AUTORISES:
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json()
    extraction = data.get('extraction')
    locked_criteria = data.get('locked_criteria', {})
    famille_metier = data.get('famille_metier', '')
    emploi_repere = data.get('emploi_repere', '')
    model = data.get('model', 'gpt-4o')

    provider_id, api_key = _get_api_key_for_model(model)
    if not api_key:
        return jsonify({'error': 'Cle API non configuree pour ce modele.'}), 400

    if not extraction:
        return jsonify({'error': "Donnees d'extraction manquantes"}), 400

    criteres_desc = build_criteres_description()
    extraction_json = json.dumps(extraction, ensure_ascii=False, indent=2)

    # Bornes CCN
    bornes = _get_bornes_for_emploi(famille_metier, emploi_repere)
    bornes_text = _build_bornes_text(bornes) if bornes else ""

    bornes_block = ""
    if bornes_text:
        bornes_block = f"""
CONTRAINTES CCN — Emploi repere : {emploi_repere}
Reste dans ces bornes :
{bornes_text}
"""

    # Criteres verrouilles
    locked_instructions = ""
    if locked_criteria:
        locked_lines = []
        for nom, info in locked_criteria.items():
            locked_lines.append(f"- {nom} : FIXE niveau {info['niveau']} ({info['points']} points)")
        locked_instructions = f"""
CRITERES VERROUILLES (reprendre tels quels) :
{chr(10).join(locked_lines)}
"""

    prompt = f"""Recotation ALISFA avec criteres verrouilles.

FAITS EXTRAITS :
{extraction_json}

GRILLE DES 8 CRITERES :
{criteres_desc}
{bornes_block}{locked_instructions}
REGLES :
- Criteres verrouilles : reprends exactement le niveau indique.
- Criteres libres : reevalue sur les faits. Doute → niveau inferieur.
- Certitude : 90-100% explicite, 70-89% implicite, 50-69% vague, 30-49% absent.
- "non mentionne" → certitude ≤ 50%.

Reponds en JSON :
{{
  "intitule_poste": "",
  "emploi_repere": "{emploi_repere}",
  "criteres": [
    {{"nom": "", "niveau": 1, "label_niveau": "", "points": 0, "certitude": 50, "justification": ""}}
  ],
  "total_points": 0,
  "certitude_globale": 0,
  "synthese": "",
  "alertes": []
}}"""

    try:
        result_raw = call_ai([{"role": "user", "content": prompt}], model)
        result = _extract_json_from_response(result_raw)
    except json.JSONDecodeError:
        return jsonify({'error': 'Erreur de format dans la reponse IA. Reessayez.'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    result = _correct_certainties(extraction, result)
    if bornes:
        result = _enforce_bornes(result, bornes)

    return jsonify({'cotation': result})


# ── CRUD Postes ALISFA ──

@pesee_alisfa_bp.route('/api/pesee_alisfa/poste', methods=['POST'])
@login_required
def api_creer_poste():
    """Créer un nouveau poste ALISFA."""
    if session.get('profil') not in PROFILS_AUTORISES:
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json()
    intitule = (data.get('intitule') or '').strip()
    famille = (data.get('famille_metier') or '').strip()

    if not intitule or not famille:
        return jsonify({'error': 'Intitulé et famille de métier requis.'}), 400

    niveaux = {}
    for field in CRITERE_FIELDS:
        niveaux[field] = data.get(field, 1)
    total = _calculer_total_points_from_niveaux(niveaux)

    conn = get_db()
    try:
        cursor = conn.execute('''
            INSERT INTO postes_alisfa
                (intitule, famille_metier, emploi_repere,
                 formation_niveau, complexite_niveau, autonomie_niveau,
                 relationnel_niveau, finances_niveau, rh_niveau,
                 securite_niveau, projet_niveau, total_points, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (intitule, famille, data.get('emploi_repere', ''),
              niveaux['formation_niveau'], niveaux['complexite_niveau'],
              niveaux['autonomie_niveau'], niveaux['relationnel_niveau'],
              niveaux['finances_niveau'], niveaux['rh_niveau'],
              niveaux['securite_niveau'], niveaux['projet_niveau'],
              total, session['user_id']))
        conn.commit()
        poste_id = cursor.lastrowid
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500
    conn.close()
    return jsonify({'id': poste_id, 'total_points': total})


@pesee_alisfa_bp.route('/api/pesee_alisfa/poste/<int:poste_id>', methods=['PUT'])
@login_required
def api_modifier_poste(poste_id):
    """Modifier un poste ALISFA existant."""
    if session.get('profil') not in PROFILS_AUTORISES:
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json()
    intitule = (data.get('intitule') or '').strip()
    famille = (data.get('famille_metier') or '').strip()

    if not intitule or not famille:
        return jsonify({'error': 'Intitulé et famille de métier requis.'}), 400

    niveaux = {}
    for field in CRITERE_FIELDS:
        niveaux[field] = data.get(field, 1)
    total = _calculer_total_points_from_niveaux(niveaux)

    conn = get_db()
    conn.execute('''
        UPDATE postes_alisfa SET
            intitule = ?, famille_metier = ?, emploi_repere = ?,
            formation_niveau = ?, complexite_niveau = ?,
            autonomie_niveau = ?, relationnel_niveau = ?,
            finances_niveau = ?, rh_niveau = ?,
            securite_niveau = ?, projet_niveau = ?,
            total_points = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (intitule, famille, data.get('emploi_repere', ''),
          niveaux['formation_niveau'], niveaux['complexite_niveau'],
          niveaux['autonomie_niveau'], niveaux['relationnel_niveau'],
          niveaux['finances_niveau'], niveaux['rh_niveau'],
          niveaux['securite_niveau'], niveaux['projet_niveau'],
          total, poste_id))
    conn.commit()
    conn.close()
    return jsonify({'total_points': total})


@pesee_alisfa_bp.route('/api/pesee_alisfa/poste/<int:poste_id>', methods=['DELETE'])
@login_required
def api_supprimer_poste(poste_id):
    """Supprimer un poste ALISFA."""
    if session.get('profil') not in PROFILS_AUTORISES:
        return jsonify({'error': 'Accès non autorisé'}), 403

    conn = get_db()
    conn.execute('DELETE FROM postes_alisfa WHERE id = ?', (poste_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@pesee_alisfa_bp.route('/api/pesee_alisfa/poste/<int:poste_id>', methods=['GET'])
@login_required
def api_get_poste(poste_id):
    """Récupérer les données d'un poste."""
    if session.get('profil') not in PROFILS_AUTORISES:
        return jsonify({'error': 'Accès non autorisé'}), 403

    conn = get_db()
    poste = conn.execute('SELECT * FROM postes_alisfa WHERE id = ?', (poste_id,)).fetchone()
    conn.close()
    if not poste:
        return jsonify({'error': 'Poste introuvable'}), 404
    return jsonify(dict(poste))
