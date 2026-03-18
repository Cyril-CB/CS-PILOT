"""
Blueprint chatbot_bp.
Assistant chatbot contextuel flottant pour guider les utilisateurs.
Utilise le modèle IA configuré par le directeur dans gestion_cles_api.
"""
from flask import Blueprint, request, session, jsonify
import requests as http_requests
from utils import login_required, get_setting

chatbot_bp = Blueprint('chatbot_bp', __name__)


# ── Prompts contextuels par page ──

SYSTEM_BASE = (
    "Tu es l'assistant IA de CS-PILOT, une application de gestion pour les centres sociaux. "
    "Tu réponds uniquement aux questions concernant l'application CS-PILOT et son utilisation. "
    "Si l'utilisateur pose une question sans rapport avec l'application, décline poliment en précisant "
    "que tu es un assistant dédié à CS-PILOT et que tu ne peux répondre qu'aux questions sur l'application. "
    "Réponds de façon concise, claire et en français. Utilise le tutoiement. "
    "Tu peux utiliser des émojis pour rendre tes réponses plus lisibles."
)

PAGE_PROMPTS = {
    'dashboard_direction': (
        "L'utilisateur est sur le tableau de bord Direction. Cette page offre une vue globale de l'application : "
        "effectifs et ETP, absences en cours, factures en attente, récupérations, anomalies détectées, "
        "budget/trésorerie/subventions, validations mensuelles, actions en attente, et accès rapides. "
        "Tu as une vision globale de l'application et peux répondre de façon simple sur l'ensemble des modules. "
        "Si l'utilisateur semble vouloir des détails sur un module spécifique, renvoie-le vers la page dédiée "
        "en précisant qu'il y trouvera une aide plus détaillée via l'assistant contextuel de cette page."
    ),
    'dashboard_responsable': (
        "L'utilisateur est sur le tableau de bord Responsable. Cette page est scopée au secteur du responsable : "
        "équipe et ETP, absences, factures en attente d'approbation, récupérations, budget et subventions, "
        "validations à effectuer, et accès rapides. "
        "Aide l'utilisateur à comprendre ses indicateurs et à naviguer vers les bonnes pages."
    ),
    'dashboard_comptable': (
        "L'utilisateur est sur le tableau de bord Comptable. Cette page présente les KPIs spécifiques au profil comptable : "
        "fiche heures, documents manquants, clôture M-1, préparation paie, comptabilité (factures/écritures/export), "
        "données importées (bilan FEC + trésorerie). Aide à comprendre les indicateurs et les actions à mener."
    ),
    'dashboard_forfait_jour': (
        "L'utilisateur est sur le tableau de bord Forfait jour. Ce module permet de suivre les jours travaillés "
        "pour les salariés en forfait jour. Il affiche les compteurs de jours travaillés, repos et congés. "
        "Note : cette page est liée à la page 'Calendrier forfait jour' qui permet une visualisation "
        "calendaire des jours. L'utilisateur peut basculer entre les deux vues pour un suivi complet."
    ),
    'calendrier_forfait_jour': (
        "L'utilisateur est sur le Calendrier forfait jour. Cette page affiche une vue calendaire des jours "
        "travaillés, de repos et de congés pour les salariés en forfait jour. "
        "Note : cette page est liée au 'Tableau de bord forfait jour' qui offre une vue synthétique "
        "avec les compteurs. L'utilisateur peut basculer entre les deux pour un suivi complet."
    ),
    'approbation_factures': (
        "L'utilisateur est sur la page d'approbation des factures. Les responsables et la direction "
        "peuvent ici approuver les factures en attente pour leur périmètre. "
        "Explique l'importance du bouton 'Détail' : il permet d'accéder à la page détaillée de chaque facture "
        "pour assurer la traçabilité (historique des actions), consulter le fichier PDF de la facture, "
        "ajouter des commentaires, et vérifier toutes les informations avant approbation. "
        "L'approbation est une étape importante du circuit de validation des factures."
    ),
    'infos_salaries': (
        "L'utilisateur est sur la page Informations salariés. Ce module permet de stocker et gérer "
        "les documents RH des salariés (contrats, avenants, diplômes, pièces d'identité, etc.). "
        "En plus d'expliquer le fonctionnement de la page, tu dois pouvoir expliquer les règles "
        "de conservation des documents RH : "
        "- Contrat de travail : 5 ans après la fin du contrat "
        "- Bulletins de paie : 5 ans (l'employeur doit les conserver, le salarié à vie) "
        "- Registre du personnel : 5 ans après le départ du salarié "
        "- Documents relatifs aux charges sociales : 3 ans "
        "- Comptabilisation des horaires : 1 an "
        "- Dossier médical du salarié : 40 ans après l'exposition à un risque "
        "Documents obligatoires : contrat de travail signé, RIB, copie pièce d'identité, "
        "attestation de sécurité sociale, certificat de travail, DPAE."
    ),
    'pesee_alisfa': (
        "L'utilisateur est sur la page Pesée ALISFA. Ce module permet d'analyser les fiches de poste "
        "selon la classification de la Convention Collective Nationale ALISFA. "
        "L'IA analyse le PDF de la fiche de poste et attribue des niveaux sur 8 critères. "
        "Important : il faut impérativement fournir un vrai PDF textuel (pas un scan/image) "
        "pour que l'analyse IA fonctionne correctement. Un document scanné ne contient pas de texte "
        "exploitable et l'analyse échouera ou sera imprécise."
    ),
    'planning_enfance': (
        "L'utilisateur est sur la page Planning enfance (temps annualisé). Ce module permet de saisir "
        "les horaires des animateurs pour calculer leur temps de travail annualisé. "
        "Guide pas à pas : "
        "1. Commencer par saisir les horaires hors vacances (période scolaire) "
        "2. Saisir les horaires vacances pour chaque période de vacances "
        "3. Saisir les réunions (fréquence, durée) "
        "4. Saisir l'accompagnement à la scolarité si applicable "
        "⚠️ Attention : ne pas saisir deux fois le même créneau horaire ! "
        "Par exemple, si tu saisis 14h-18h en horaire normal ET un accompagnement à la scolarité "
        "de 16h-18h, les heures de 16h à 18h seront comptées en double. "
        "Il faut dans ce cas saisir 14h-16h en horaire normal + 16h-18h en accompagnement à la scolarité."
    ),
    'gestion_budgets': (
        "L'utilisateur est sur la page Gestion des budgets. C'est un budget simplifié destiné aux "
        "responsables de secteur pour le suivi de leurs dépenses. "
        "Il permet de suivre les dépenses par poste budgétaire et de réaffecter des montants "
        "entre les différents postes de dépenses si nécessaire, avec traçabilité des mouvements."
    ),
    'budget_previsionnel': (
        "L'utilisateur est sur la page Budget prévisionnel. Ce module permet d'élaborer les budgets "
        "prévisionnels par secteur et par type (fonctionnement, investissement). "
        "Pour créer un nouveau budget : sélectionner l'année, le type et le secteur, puis saisir "
        "les montants prévisionnels par compte comptable. "
        "Pour créer un secteur : aller dans Administration > Gestion des secteurs. "
        "Si rien ne s'affiche : c'est probablement parce qu'aucun compte comptable n'est lié aux "
        "secteurs. Il faut d'abord configurer l'affectation dans la page Plan comptable analytique "
        "(menu Comptabilité > Plan comptable analytique). "
        "Les saisies sont enregistrées en valeur temporaire puis peuvent être validées en valeur définitive."
    ),
    'subventions': (
        "L'utilisateur est sur la page Subventions. Ce module permet de gérer les subventions reçues "
        "ou demandées par la structure. "
        "Points importants : "
        "- Indiquer les deadlines (dates limites) est crucial pour ne pas rater les échéances "
        "- Les personnes assignées à une subvention y ont accès et voient les tâches qu'elles doivent réaliser "
        "- Le suivi permet de connaître l'état d'avancement de chaque subvention "
        "Tu peux répondre aux questions générales des responsables sur le fonctionnement des subventions "
        "dans le contexte associatif (demande, conventionnement, justification, bilan)."
    ),
    'tresorerie': (
        "L'utilisateur est sur la page Trésorerie. Ce module permet de suivre la trésorerie de la structure. "
        "Points importants : "
        "- Après l'importation des données bancaires, il faut saisir les mouvements internes passés "
        "  liés à l'épargne (virements entre comptes courant et épargne) "
        "- Penser à saisir le solde initial de chaque compte "
        "- Les indications d'optimisation de l'épargne permettent d'identifier les excédents "
        "  de trésorerie qui pourraient être placés "
        "- Après importation, vérifier les comptes : certains comptes de produits pourraient être "
        "  classés en charges et inversement. Il est important de corriger ces affectations. "
        "Guide l'utilisateur sur la lecture des graphiques et l'interprétation des indicateurs."
    ),
    'factures': (
        "L'utilisateur est sur la page Factures. Ce module est au cœur du circuit de traitement "
        "des factures et est lié à plusieurs autres modules : "
        "- Fournisseurs : gérer la liste des fournisseurs (créer, modifier, désactiver) "
        "- Règles comptables : définir les règles d'imputation automatique des factures "
        "- Écritures : les écritures comptables générées à partir des factures traitées "
        "- Exportation : exporter les écritures vers le logiciel comptable "
        "Flux complet : Réception facture → Saisie/Upload → Assignation secteur → "
        "Approbation responsable → Traitement comptable → Écriture → Export. "
        "Guide pas à pas si nécessaire sur chaque étape du processus."
    ),
    'salles': (
        "L'utilisateur est sur la page Salles. Ce module permet de gérer les réservations de salles. "
        "Pour créer une salle : cliquer sur le bouton d'ajout et renseigner le nom, la capacité et la description. "
        "Pour réserver : sélectionner la salle, choisir la date et l'heure, indiquer l'objet de la réservation. "
        "Les récurrences permettent de créer des réservations répétées (hebdomadaire, mensuelle). "
        "Pour créer une récurrence : lors de la réservation, cocher l'option récurrence et définir "
        "la fréquence et la date de fin."
    ),
    'administration': (
        "L'utilisateur est sur la page Administration (Mises à jour BDD). "
        "Cette page gère le système de migration de la base de données. "
        "Les migrations sont des scripts qui modifient la structure de la base de données "
        "(ajout de tables, de colonnes, etc.) pour faire évoluer l'application. "
        "Elles sont appliquées dans l'ordre et chaque migration n'est exécutée qu'une seule fois. "
        "En cas de problème, contacter le support technique."
    ),
    'mise_a_jour': (
        "L'utilisateur est sur la page Mise à jour de l'application. "
        "⚠️ Rappel important : avant toute mise à jour, effectuer une sauvegarde de la base de données ! "
        "Aller dans Administration > Sauvegardes BDD pour créer une sauvegarde avant de lancer la mise à jour. "
        "Cela permet de revenir en arrière en cas de problème."
    ),
    'saisie_heures': (
        "L'utilisateur est sur la page Saisie des heures. Cette page permet de saisir les heures "
        "travaillées au quotidien. Sélectionner la date, renseigner les horaires matin et après-midi, "
        "et enregistrer. Les heures sont ensuite visibles dans la vue mensuelle et le tableau de bord."
    ),
    'gestion_cles_api': (
        "L'utilisateur est sur la page Gestion des clés API. Cette page permet de configurer les clés API "
        "des fournisseurs d'intelligence artificielle (OpenAI, Groq, Anthropic) utilisées par l'application. "
        "Les clés sont chiffrées en base de données. En bas de page, le directeur peut choisir le modèle "
        "IA utilisé par l'assistant chatbot contextuel."
    ),
    'ecritures': (
        "L'utilisateur est sur la page Écritures comptables. Les écritures sont générées à partir "
        "des factures traitées selon les règles comptables définies. Elles peuvent être en brouillon "
        "ou validées avant export."
    ),
    'exportation': (
        "L'utilisateur est sur la page Exportation. Elle permet d'exporter les écritures comptables "
        "validées vers le logiciel comptable au format adapté."
    ),
    'fournisseurs': (
        "L'utilisateur est sur la page Fournisseurs. Elle permet de gérer la liste des fournisseurs "
        "(créer, modifier, désactiver). Chaque fournisseur peut être associé à des règles comptables "
        "pour automatiser l'imputation des factures."
    ),
    'regles_comptables': (
        "L'utilisateur est sur la page Règles comptables. Les règles permettent de définir l'imputation "
        "automatique des factures selon le fournisseur : compte de charge, TVA, etc."
    ),
    'absences': (
        "L'utilisateur est sur la page Absences. Elle permet de consulter et gérer les absences "
        "(congés, maladie, etc.) des salariés."
    ),
    'rh_statistiques': (
        "L'utilisateur est sur la page Statistiques RH. Elle présente des indicateurs sur les effectifs, "
        "les ETP, les types de contrats et les temps de travail."
    ),
}


def _get_system_prompt(page_id):
    """Construit le prompt système complet pour une page donnée."""
    page_context = PAGE_PROMPTS.get(page_id, '')
    if page_context:
        return f"{SYSTEM_BASE}\n\nContexte de la page actuelle :\n{page_context}"
    return (
        f"{SYSTEM_BASE}\n\nL'utilisateur se trouve sur la page '{page_id}'. "
        "Aide-le à comprendre cette page et réponds à ses questions sur son fonctionnement."
    )


# ── Appels API IA (réutilisation du pattern pesee_alisfa) ──

def _get_api_key_for_model(model):
    """Récupère la clé API correspondant au modèle choisi."""
    from blueprints.api_keys import AI_PROVIDERS, MODEL_TO_PROVIDER
    provider_id = MODEL_TO_PROVIDER.get(model)
    if not provider_id:
        return None, None
    api_key = get_setting(AI_PROVIDERS[provider_id]['key_setting'])
    return provider_id, api_key


def _call_openai(api_key, messages, model):
    """Appel API OpenAI pour le chatbot."""
    payload = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": 1000,
        "temperature": 0.7,
    }
    resp = http_requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if resp.status_code != 200:
        error_msg = resp.text[:300]
        try:
            error_msg = resp.json().get('error', {}).get('message', error_msg)
        except Exception:
            pass
        raise Exception(f"Erreur API OpenAI ({resp.status_code}): {error_msg}")
    return resp.json()['choices'][0]['message']['content']


def _call_groq(api_key, messages, model):
    """Appel API Groq pour le chatbot."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 1000,
    }
    resp = http_requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if resp.status_code != 200:
        error_msg = resp.text[:300]
        try:
            error_msg = resp.json().get('error', {}).get('message', error_msg)
        except Exception:
            pass
        raise Exception(f"Erreur API Groq ({resp.status_code}): {error_msg}")
    return resp.json()['choices'][0]['message']['content']


def _call_anthropic(api_key, messages, model):
    """Appel API Anthropic pour le chatbot."""
    system_text = ""
    user_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_text += msg["content"] + "\n"
        else:
            user_messages.append(msg)
    if not user_messages:
        user_messages = messages

    payload = {
        "model": model,
        "max_tokens": 1000,
        "temperature": 0.7,
        "messages": user_messages,
    }
    if system_text.strip():
        payload["system"] = system_text.strip()

    resp = http_requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
        json=payload,
        timeout=30,
    )
    if resp.status_code != 200:
        error_msg = resp.text[:300]
        try:
            error_msg = resp.json().get('error', {}).get('message', error_msg)
        except Exception:
            pass
        raise Exception(f"Erreur API Anthropic ({resp.status_code}): {error_msg}")
    return resp.json()['content'][0]['text']


def _call_ai(messages, model):
    """Dispatcher : appelle le bon fournisseur en fonction du modèle."""
    provider_id, api_key = _get_api_key_for_model(model)
    if not provider_id:
        raise Exception(f"Modèle inconnu : {model}")
    if not api_key:
        raise Exception("Clé API non configurée. Contactez votre directeur.")

    if provider_id == 'openai':
        return _call_openai(api_key, messages, model)
    elif provider_id == 'groq':
        return _call_groq(api_key, messages, model)
    elif provider_id == 'anthropic':
        return _call_anthropic(api_key, messages, model)
    else:
        raise Exception(f"Fournisseur non supporté : {provider_id}")


# ── Routes ──

@chatbot_bp.route('/api/chatbot/message', methods=['POST'])
@login_required
def chatbot_message():
    """Envoie un message au chatbot contextuel et retourne la réponse."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Données invalides'}), 400

    user_message = data.get('message', '').strip()
    page_id = data.get('page', '').strip()
    history = data.get('history', [])

    if not user_message:
        return jsonify({'error': 'Message vide'}), 400

    # Récupérer le modèle configuré
    model = get_setting('chatbot_model')
    if not model:
        return jsonify({'error': "Aucun modèle IA configuré pour l'assistant. "
                        "Le directeur doit sélectionner un modèle dans Administration > Clés API."}), 400

    # Construire les messages pour l'API
    system_prompt = _get_system_prompt(page_id)
    messages = [{"role": "system", "content": system_prompt}]

    # Ajouter l'historique de conversation (limiter à 10 derniers échanges)
    for h in history[-10:]:
        role = h.get('role', 'user')
        content = h.get('content', '')
        if role in ('user', 'assistant') and content:
            messages.append({"role": role, "content": content})

    # Ajouter le message actuel
    messages.append({"role": "user", "content": user_message})

    try:
        response = _call_ai(messages, model)
        return jsonify({'response': response})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@chatbot_bp.route('/api/chatbot/config')
@login_required
def chatbot_config():
    """Retourne la configuration du chatbot (modèle actif, etc.)."""
    model = get_setting('chatbot_model')
    return jsonify({
        'enabled': model is not None,
        'model': model,
    })


@chatbot_bp.route('/api/chatbot/model', methods=['POST'])
@login_required
def chatbot_set_model():
    """Définit le modèle IA du chatbot (directeur uniquement)."""
    if session.get('profil') != 'directeur':
        return jsonify({'error': 'Accès réservé au directeur'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Données invalides'}), 400

    model = data.get('model', '').strip()

    if not model:
        # Désactiver le chatbot
        from utils import delete_setting
        delete_setting('chatbot_model')
        return jsonify({'success': True, 'enabled': False})

    # Vérifier que le modèle existe et a une clé configurée
    provider_id, api_key = _get_api_key_for_model(model)
    if not provider_id:
        return jsonify({'error': 'Modèle inconnu'}), 400
    if not api_key:
        return jsonify({'error': 'Clé API non configurée pour ce fournisseur'}), 400

    from utils import save_setting
    save_setting('chatbot_model', model)
    return jsonify({'success': True, 'enabled': True})
