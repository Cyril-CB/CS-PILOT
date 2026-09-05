"""
Application de Gestion du Temps de Travail - Point d'entrée principal.
Architecture en Blueprints Flask.
"""
import os
import sys
import secrets
import sqlite3
from dotenv import load_dotenv
from flask import Flask, session, render_template, flash, redirect, url_for, request, jsonify
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix
import logging
from logging.handlers import RotatingFileHandler
import app_version
from database import init_db, get_db, DATA_DIR
from blueprints.delegations import (
    MISSION_SUIVI_VALIDATIONS_RELANCES, user_peut_gerer_benevoles,
)
from extensions import csrf, limiter
from fiches_versions import FicheVerrouillee


def configure_logging():
    """Configure le logging applicatif : console + fichier avec rotation.

    Sans handler configure, les logger.info()/logger.exception() des modules
    partent dans le vide (seul le niveau WARNING atteint la console par defaut).
    On ecrit dans DATA_DIR/logs/cspilot.log (inscriptible meme en mode .exe)
    avec rotation pour borner la taille. Neutralise sous pytest, ou la capture
    des logs est geree par le harnais de test.
    """
    if "pytest" in sys.modules:
        return
    root = logging.getLogger()
    if root.handlers:  # deja configure (evite les handlers en double)
        return
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        log_dir = os.path.join(DATA_DIR, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, 'cspilot.log'),
            maxBytes=2_000_000, backupCount=10, encoding='utf-8',
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        # Repertoire non inscriptible : on conserve au moins la console.
        logging.getLogger(__name__).warning(
            "Journalisation fichier indisponible (DATA_DIR non inscriptible)"
        )

    # Limiter le bruit des logs de requetes HTTP de werkzeug.
    logging.getLogger('werkzeug').setLevel(logging.WARNING)


configure_logging()
logger = logging.getLogger(__name__)


def generate_env_file(env_path):
    """
    Génère un fichier .env avec une clé SECRET_KEY aléatoire sécurisée.

    Args:
        env_path: Chemin du fichier .env à créer
    """
    secret_key = secrets.token_hex(32)

    env_content = f"""# Clé secrète pour les sessions Flask et les tokens CSRF
# Cette clé a été générée automatiquement au premier démarrage.
# Pour générer une nouvelle clé : python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY={secret_key}

# Mettre à true si l'application est derrière un proxy/tunnel (ngrok, Cloudflare, etc.)
# Active ProxyFix et SESSION_COOKIE_SECURE pour le bon fonctionnement en HTTPS
# BEHIND_PROXY=true
"""

    try:
        with open(env_path, 'w', encoding='utf-8') as f:
            f.write(env_content)
        print("=" * 60)
        print("Fichier .env créé avec succès !")
        print("=" * 60)
        print()
        print(f"Un nouveau fichier .env a été généré dans :")
        print(f"  {env_path}")
        print()
        print("Une clé secrète aléatoire a été créée automatiquement.")
        print("Vous pouvez maintenant utiliser l'application en toute sécurité.")
        print()
        print("=" * 60)
        return True
    except Exception as e:
        print("=" * 60)
        print("ERREUR lors de la création du fichier .env")
        print("=" * 60)
        print()
        print(f"Impossible de créer le fichier .env : {e}")
        print()
        print("Veuillez créer manuellement un fichier .env avec :")
        print()
        print('  python -c "import secrets; print(secrets.token_hex(32))"')
        print()
        print("Puis ajoutez le résultat dans .env :")
        print("  SECRET_KEY=<votre_cle_generee>")
        print()
        print("=" * 60)
        return False


# Charger les variables d'environnement depuis .env (s'il existe).
# DATA_DIR pointe vers le dossier du projet en mode script, et vers AppData en mode .exe,
# donc le .env est toujours au même endroit que la base de données.
env_path = os.path.join(DATA_DIR, '.env')

# Si le fichier .env n'existe pas ET qu'aucune SECRET_KEY n'est définie dans l'environnement,
# générer automatiquement un fichier .env avec une clé secrète.
if not os.path.exists(env_path) and not os.environ.get('SECRET_KEY'):
    generate_env_file(env_path)

load_dotenv(dotenv_path=env_path)

_DEFAULT_SECRET_KEY = 'dev-secret-key-do-not-use-in-production'

# Vérifie si l'app tourne en .exe (frozen) ou en script normal
if getattr(sys, 'frozen', False):
    # Chemin vers le dossier temporaire de PyInstaller (ou fallback si non défini)
    base_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
else:
    # Mode script normal : dossier du fichier courant
    base_dir = os.path.dirname(os.path.abspath(__file__))

template_folder = os.path.join(base_dir, 'templates')
static_folder = os.path.join(base_dir, 'static')
app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)


@app.errorhandler(FicheVerrouillee)
def fiche_verrouillee_refusee(exc):
    """Le contrôle central a déjà annulé la transaction entière."""
    flash(str(exc), 'error')
    return redirect(url_for('validation_bp.vue_mensuelle'), code=303)

# ==================== Sécurité : SECRET_KEY ====================
_secret_key = os.environ.get('SECRET_KEY', '')
if not _secret_key or _secret_key == _DEFAULT_SECRET_KEY:
    if not app.testing:
        print("=" * 60)
        print("ERREUR CRITIQUE DE SECURITE")
        print("=" * 60)
        print()
        print("La variable d'environnement SECRET_KEY n'est pas definie")
        print("ou utilise encore la valeur par defaut.")
        print()
        print("L'application ne peut pas demarrer sans une cle secrete")
        print("personnalisee. Ceci est necessaire pour securiser les")
        print("sessions et les tokens CSRF.")
        print()
        print("Pour generer une cle secrete, executez :")
        print()
        print('  python -c "import secrets; print(secrets.token_hex(32))"')
        print()
        print("Puis ajoutez-la dans votre fichier .env :")
        print()
        print("  SECRET_KEY=<votre_cle_generee>")
        print()
        print("Ou definissez la variable d'environnement directement :")
        print()
        print("  export SECRET_KEY=<votre_cle_generee>")
        print()
        print("=" * 60)
        sys.exit(1)

app.secret_key = _secret_key

# ==================== Proxy (ngrok, reverse proxy) ====================
# ProxyFix permet à Flask de détecter HTTPS derrière un proxy/tunnel
if os.environ.get('BEHIND_PROXY', '').lower() in ('1', 'true', 'yes'):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# ==================== Configuration des cookies de session ====================
_behind_proxy = os.environ.get('BEHIND_PROXY', '').lower() in ('1', 'true', 'yes')
app.config['SESSION_COOKIE_HTTPONLY'] = True
if _behind_proxy:
    # Derrière ngrok/reverse proxy : SameSite=None pour compatibilité mobile.
    # Les navigateurs mobiles peuvent bloquer les cookies SameSite=Lax lors de
    # redirections via la page interstitielle ngrok (free tier) ou dans les
    # WebViews intégrés (WhatsApp, iMessage, etc.), empêchant le stockage du
    # cookie de session et causant l'erreur "CSRF session token is missing".
    # La protection CSRF reste assurée par les tokens Flask-WTF.
    app.config['SESSION_COOKIE_SAMESITE'] = 'None'
    app.config['SESSION_COOKIE_SECURE'] = True
else:
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = False

# ==================== Taille maximale des envois de fichiers ====================
# L'application expose de nombreux points d'envoi (justificatifs d'absence,
# contrats et documents salariés, modèles DOCX de génération de contrats,
# imports comptables FEC/TXT, plan comptable, lots de factures PDF...). Sans
# borne, une requête de taille arbitraire peut saturer la mémoire ou le disque
# du serveur.
#
# La limite est volontairement TRÈS LARGE pour ne bloquer aucun usage réel :
# le flux le plus volumineux est l'import de factures, qui accepte plusieurs
# PDF dans une seule requête. La restauration d'une sauvegarde ne transite pas
# par un formulaire d'envoi (le fichier est déjà présent sur le serveur, seul
# son nom est transmis), elle n'est donc pas concernée par cette limite.
#
# Surchargeable par la variable d'environnement MAX_UPLOAD_MO (en méga-octets).
MAX_UPLOAD_MO_DEFAUT = 256


def lire_max_upload_mo():
    """Retourne la taille maximale d'un envoi HTTP, en méga-octets.

    Lit MAX_UPLOAD_MO dans l'environnement et retombe sur la valeur par défaut
    si elle est absente, non numérique ou nulle/négative.
    """
    valeur = os.environ.get('MAX_UPLOAD_MO', '').strip()
    if not valeur:
        return MAX_UPLOAD_MO_DEFAUT
    try:
        mo = int(valeur)
    except ValueError:
        logger.warning(
            "MAX_UPLOAD_MO invalide (%r) : limite par défaut de %s Mo appliquée.",
            valeur, MAX_UPLOAD_MO_DEFAUT,
        )
        return MAX_UPLOAD_MO_DEFAUT
    if mo <= 0:
        logger.warning(
            "MAX_UPLOAD_MO doit être un entier positif (%r) : limite par défaut "
            "de %s Mo appliquée.", valeur, MAX_UPLOAD_MO_DEFAUT,
        )
        return MAX_UPLOAD_MO_DEFAUT
    return mo


app.config['MAX_CONTENT_LENGTH'] = lire_max_upload_mo() * 1024 * 1024

# ==================== Initialisation des extensions ====================
# Le jeton CSRF reste valide tant que la session l'est (pas d'expiration au
# bout d'1h). Evite l'echec des enregistrements AJAX quand une page reste
# ouverte longtemps (ex: saisie d'un budget secteur avec de nombreuses
# colonnes), qui se manifestait par une redirection vers /login interpretee
# a tort comme une "Erreur reseau" cote navigateur. La protection CSRF reste
# entiere (jeton toujours requis et lie a la session).
app.config['WTF_CSRF_TIME_LIMIT'] = None
csrf.init_app(app)
limiter.init_app(app)

# ==================== Enregistrement des Blueprints ====================
from blueprints.auth import auth
from blueprints.dashboard import dashboard_bp
from blueprints.saisie import saisie_bp
from blueprints.planning import planning_bp
from blueprints.admin import admin_bp
from blueprints.validation import validation_bp
from blueprints.recup import recup_bp
from blueprints.forfait import forfait_bp
from blueprints.suivi import suivi_bp
from blueprints.exports import exports_bp
from blueprints.planning_enfance import planning_enfance_bp
from blueprints.pesee_alisfa import pesee_alisfa_bp
from blueprints.api_keys import api_keys_bp
from blueprints.assistant_rh import assistant_rh_bp
from blueprints.backup import backup_bp
from blueprints.administration import administration_bp
from blueprints.securite import securite_bp
from blueprints.absences import absences_bp
from blueprints.variables_paie import variables_paie_bp
from blueprints.infos_salaries import infos_salaries_bp
from blueprints.prepa_paie import prepa_paie_bp
from blueprints.mon_equipe import mon_equipe_bp
from blueprints.dashboard_direction import dashboard_direction_bp
from blueprints.notifications import notifications_bp
from blueprints.parametres import parametres_bp
from blueprints.budget import budget_bp
from blueprints.subventions import subventions_bp
from blueprints.benevoles import benevoles_bp
from blueprints.salles import salles_bp
from blueprints.tresorerie import tresorerie_bp
from blueprints.factures import factures_bp
from blueprints.fournisseurs import fournisseurs_bp
from blueprints.regles_comptables import regles_comptables_bp
from blueprints.ecritures import ecritures_bp
from blueprints.exportation import exportation_bp
from blueprints.generation_contrats import generation_contrats_bp
from blueprints.comptabilite_analytique import comptabilite_analytique_bp
from blueprints.plan_comptable_general import plan_comptable_general_bp
from blueprints.bilan_secteurs import bilan_secteurs_bp
from blueprints.bilan_action import bilan_action_bp
from blueprints.alsh import alsh_bp
from blueprints.mise_a_jour import mise_a_jour_bp
from blueprints.rh_statistiques import rh_statistiques_bp
from blueprints.presence_effectif import presence_effectif_bp
from blueprints.dashboard_responsable import dashboard_responsable_bp
from blueprints.dashboard_comptable import dashboard_comptable_bp
from blueprints.chatbot import chatbot_bp
from blueprints.compte_resultat import compte_resultat_bp
from blueprints.indicateurs_financiers import indicateurs_financiers_bp
from blueprints.import_bi import import_bi_bp
from blueprints.commandes_salaries import commandes_salaries_bp
from blueprints.cse import cse_bp
from blueprints.planificateur import planificateur_bp
from blueprints.contrats import contrats_bp
from blueprints.recherche import recherche_bp
from blueprints.accueil import accueil_bp

app.register_blueprint(auth)
app.register_blueprint(accueil_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(dashboard_responsable_bp)
app.register_blueprint(dashboard_comptable_bp)
app.register_blueprint(saisie_bp)
app.register_blueprint(planning_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(validation_bp)
app.register_blueprint(recup_bp)
app.register_blueprint(forfait_bp)
app.register_blueprint(suivi_bp)
app.register_blueprint(exports_bp)
app.register_blueprint(planning_enfance_bp)
app.register_blueprint(pesee_alisfa_bp)
app.register_blueprint(api_keys_bp)
app.register_blueprint(assistant_rh_bp)
app.register_blueprint(backup_bp)
app.register_blueprint(administration_bp)
app.register_blueprint(securite_bp)
app.register_blueprint(absences_bp)
app.register_blueprint(variables_paie_bp)
app.register_blueprint(infos_salaries_bp)
app.register_blueprint(prepa_paie_bp)
app.register_blueprint(mon_equipe_bp)
app.register_blueprint(dashboard_direction_bp)
app.register_blueprint(notifications_bp)
app.register_blueprint(parametres_bp)
app.register_blueprint(budget_bp)
app.register_blueprint(subventions_bp)
app.register_blueprint(benevoles_bp)
app.register_blueprint(salles_bp)
app.register_blueprint(tresorerie_bp)
app.register_blueprint(factures_bp)
app.register_blueprint(fournisseurs_bp)
app.register_blueprint(regles_comptables_bp)
app.register_blueprint(ecritures_bp)
app.register_blueprint(exportation_bp)
app.register_blueprint(generation_contrats_bp)
app.register_blueprint(comptabilite_analytique_bp)
app.register_blueprint(plan_comptable_general_bp)
app.register_blueprint(bilan_secteurs_bp)
app.register_blueprint(bilan_action_bp)
app.register_blueprint(alsh_bp)
app.register_blueprint(mise_a_jour_bp)
app.register_blueprint(rh_statistiques_bp)
app.register_blueprint(presence_effectif_bp)
app.register_blueprint(chatbot_bp)
app.register_blueprint(compte_resultat_bp)
app.register_blueprint(indicateurs_financiers_bp)
app.register_blueprint(import_bi_bp)
app.register_blueprint(commandes_salaries_bp)
app.register_blueprint(cse_bp)
app.register_blueprint(planificateur_bp)
app.register_blueprint(contrats_bp)
app.register_blueprint(recherche_bp)


# ==================== Context Processors ====================
_cached_app_version = None

@app.context_processor
def inject_version():
    """Injecte la version de l'application dans tous les templates (mise en cache)."""
    global _cached_app_version
    if _cached_app_version is None:
        _cached_app_version = app_version.get_app_version()
    return {'app_version': _cached_app_version}


def invalidate_version_cache():
    """Invalide le cache de version (a appeler apres une migration)."""
    global _cached_app_version
    _cached_app_version = None


@app.context_processor
def inject_static_version():
    """Empreinte des fichiers statiques, pour forcer le navigateur à relire.

    La feuille de style et les scripts portaient un numéro écrit à la main
    (`?v=20`). Personne ne pense à l'incrémenter : une modification de CSS
    reste alors invisible chez tous ceux qui ont déjà chargé la page, et le
    défaut se diagnostique mal — le code est juste, le rendu ne bouge pas.

    L'empreinte suit la date de modification du fichier : elle change
    d'elle-même à chaque livraison, et jamais autrement.
    """
    empreintes = {}
    for nom in ('css/style.css', 'js/flux.js'):
        chemin = os.path.join(app.static_folder, nom)
        try:
            empreintes[nom] = str(int(os.path.getmtime(chemin)))
        except OSError:
            # Fichier absent (montage incomplet) : pas de cache-busting plutôt
            # qu'une page qui ne se rend pas.
            empreintes[nom] = ''
    return {'static_version': empreintes}


@app.context_processor
def inject_pending_counts():
    """Injecte le nombre de demandes en attente dans tous les templates."""
    if 'user_id' not in session:
        return {
            'pending_count': 0,
            'chatbot_enabled': False,
            'can_access_vue_ensemble_validation': False,
        }

    profil = session.get('profil', '')
    conn = None
    try:
        conn = get_db()

        if profil == 'directeur' or profil == 'comptable':
            row_recup = conn.execute(
                "SELECT COUNT(*) as nb FROM demandes_recup WHERE statut IN ('en_attente_direction', 'en_attente_responsable')"
            ).fetchone()
            row_conge = conn.execute(
                "SELECT COUNT(*) as nb FROM demandes_conges WHERE statut IN ('en_attente_direction', 'en_attente_responsable')"
            ).fetchone()
            count = (row_recup['nb'] if row_recup else 0) + (row_conge['nb'] if row_conge else 0)
        elif profil == 'responsable':
            user = conn.execute("SELECT secteur_id FROM users WHERE id = ?", (session['user_id'],)).fetchone()
            sid = user['secteur_id'] if user else None
            if sid:
                row_recup = conn.execute(
                    """SELECT COUNT(*) as nb FROM demandes_recup d
                       JOIN users u ON d.user_id = u.id
                       WHERE u.secteur_id = ? AND d.statut = 'en_attente_responsable'""",
                    (sid,)
                ).fetchone()
                row_conge = conn.execute(
                    """SELECT COUNT(*) as nb FROM demandes_conges d
                       JOIN users u ON d.user_id = u.id
                       WHERE u.secteur_id = ? AND d.statut = 'en_attente_responsable'""",
                    (sid,)
                ).fetchone()
                count = (row_recup['nb'] if row_recup else 0) + (row_conge['nb'] if row_conge else 0)
            else:
                count = 0
        else:
            count = 0

        chatbot_on = False
        try:
            from utils import get_setting as _gs
            chatbot_on = _gs('chatbot_model') is not None
        except Exception:
            pass

        delegation_validation = False
        try:
            row = conn.execute(
                'SELECT delegated_user_id FROM delegations_missions WHERE mission_key = ?',
                (MISSION_SUIVI_VALIDATIONS_RELANCES,)
            ).fetchone()
            delegation_validation = bool(row and row['delegated_user_id'] == session.get('user_id'))
        except Exception:
            delegation_validation = False

        can_access_vue_ensemble_validation = profil in ('directeur', 'comptable', 'responsable') or delegation_validation

        return {
            'pending_count': count,
            'chatbot_enabled': chatbot_on,
            'can_access_vue_ensemble_validation': can_access_vue_ensemble_validation,
        }
    except Exception:
        return {
            'pending_count': 0,
            'chatbot_enabled': False,
            'can_access_vue_ensemble_validation': False,
        }
    finally:
        if conn:
            conn.close()


@app.context_processor
def inject_app_options():
    """Injecte les options utiles à l'affichage global."""
    try:
        from app_options import get_option_bool
        return {
            'generation_contrats_responsable_autorise': get_option_bool('generation_contrats_responsable_autorise'),
            'budget_previsionnel_responsable_autorise': get_option_bool('budget_previsionnel_responsable_autorise'),
        }
    except Exception:
        return {
            'generation_contrats_responsable_autorise': True,
            'budget_previsionnel_responsable_autorise': True,
        }


@app.context_processor
def inject_cse_context():
    """Injecte le contexte CSE (rôle et message actif) dans tous les templates."""
    defaults = {
        'is_cse_membre': False,
        'is_cse_gestionnaire': False,
        'cse_message_actif': None,
    }
    if 'user_id' not in session:
        return defaults

    profil = session.get('profil', '')
    conn = None
    try:
        from blueprints.cse import est_membre_cse, get_message_actif, PROFILS_GESTION
        conn = get_db()
        is_membre = est_membre_cse(conn, session.get('user_id'))
        message_actif = get_message_actif(conn) if profil != 'prestataire' else None
        return {
            'is_cse_membre': is_membre,
            'is_cse_gestionnaire': profil in PROFILS_GESTION,
            'cse_message_actif': message_actif,
        }
    except Exception:
        return defaults
    finally:
        if conn:
            conn.close()


@app.context_processor
def inject_delegation_benevoles():
    """Injecte la délégation « gestion des bénévoles » pour le menu latéral.

    La direction et la comptabilité ont déjà l'entrée de menu par leur profil :
    la lecture n'est faite que pour les salariés et responsables, seuls
    concernés par cette délégation.
    """
    if 'user_id' not in session or session.get('profil') not in ('salarie', 'responsable'):
        return {'is_delegue_benevoles': False}
    try:
        return {'is_delegue_benevoles': user_peut_gerer_benevoles(session.get('user_id'))}
    except sqlite3.Error:
        # Defaillance attendue : table absente sur une base dont la mise a
        # niveau n'est pas encore appliquee (la page qui lance les migrations
        # doit rester affichable), ou base momentanement verrouillee. Seule
        # l'entree de menu disparait : les routes gardent leur propre controle.
        logging.getLogger(__name__).warning(
            "Delegation benevoles illisible, entree de menu masquee", exc_info=True
        )
        return {'is_delegue_benevoles': False}


@app.context_processor
def inject_interface_flux():
    """Injecte l'état et la carte de l'interface sans menu.

    Le calcul est mémorisé dans `flask.g` : plusieurs gabarits peuvent lire la
    carte sans relancer les lectures de droits. Toute défaillance retombe sur
    l'interface historique plutôt que de faire échouer le rendu.
    """
    try:
        import interface_flux
        contexte = dict(interface_flux.contexte())
        if contexte.get('ui_flux'):
            contexte['flux_infos'] = interface_flux.flux_infos_page()
        return contexte
    except Exception:
        logger.warning("Contexte de l'interface sans menu indisponible", exc_info=True)
        return {'ui_flux': False, 'ui_flux_eligible': False}


@app.errorhandler(429)
def ratelimit_handler(e):
    """Affiche un message clair quand la limite de tentatives est atteinte."""
    flash('Trop de tentatives. Veuillez patienter avant de réessayer.', 'error')
    return render_template('login.html'), 429


def _taille_max_lisible():
    """Retourne la taille maximale d'envoi formatée pour un message utilisateur."""
    limite = app.config.get('MAX_CONTENT_LENGTH') or 0
    mo = limite / (1024 * 1024)
    if mo >= 1:
        return f"{mo:.0f} Mo" if mo == int(mo) else f"{mo:.1f} Mo"
    return f"{limite / 1024:.0f} Ko"


def _attend_du_json():
    """Vrai si le client attend une réponse JSON (route d'API ou appel fetch).

    N'inspecte que le chemin et les en-têtes : lire le corps de la requête
    relancerait immédiatement l'erreur de dépassement de taille.
    """
    return ('/api/' in request.path
            or request.accept_mimetypes.best == 'application/json'
            or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or request.is_json)


def _url_retour_sure():
    """Retourne l'URL où renvoyer l'utilisateur après un envoi trop volumineux.

    On ne réutilise JAMAIS l'URL fournie par le navigateur (en-tête Referer) :
    une valeur contrôlée par le client ne doit pas devenir une cible de
    redirection (redirection ouverte). Le tableau de bord est la destination de
    repli utilisée partout ailleurs dans l'application ; le message flash
    explique ce qui s'est passé.
    """
    return url_for('dashboard_bp.dashboard')


@app.errorhandler(413)
def handle_request_entity_too_large(e):
    """Répond proprement quand l'envoi dépasse la taille maximale autorisée.

    Les routes d'API (ou les appels fetch) reçoivent un JSON en 413 ; les
    formulaires classiques reçoivent un message flash puis une redirection,
    conformément au schéma Post/Redirect/Get utilisé dans l'application.
    """
    taille_max = _taille_max_lisible()
    message = (
        f"Envoi trop volumineux : la taille totale des fichiers ne doit pas "
        f"dépasser {taille_max}. Compressez le document ou envoyez-le en "
        f"plusieurs fois."
    )
    logger.warning(
        "Envoi refusé (413) : path=%s method=%s user_id=%s taille_max=%s",
        request.path, request.method, session.get('user_id'), taille_max,
    )
    if _attend_du_json():
        return jsonify({'ok': False, 'error': message}), 413
    flash(message, 'error')
    return redirect(_url_retour_sure())


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    """Gestion des erreurs CSRF : redirige vers login avec message explicite."""
    # Trace l'echec CSRF (sinon invisible) : un POST AJAX rejete est redirige
    # vers /login (HTML), ce que le navigateur affiche a tort comme une
    # "Erreur reseau". La raison (jeton expire / absent / non concordant) aide
    # a diagnostiquer ces echecs d'enregistrement.
    logger.warning(
        "Echec CSRF: %s | endpoint=%s method=%s path=%s user_id=%s",
        getattr(e, 'description', 'inconnu'),
        request.endpoint, request.method, request.path, session.get('user_id'),
    )
    session.clear()
    flash('Votre session a expiré ou est invalide. Veuillez vous reconnecter.', 'error')
    return redirect(url_for('auth.login'))


@app.after_request
def set_cache_headers(response):
    """Désactive le cache sur les pages HTML pour garantir des tokens CSRF frais."""
    if response.content_type and 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
    return response


if __name__ == '__main__':
    init_db()

    host = '0.0.0.0'
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'

    print("=" * 60)
    print("Application de Gestion du Temps de Travail")
    print("   Architecture Blueprints Flask")
    print("=" * 60)
    print(f"\nAcces: http://localhost:{port}")
    print(f"   ou http://192.168.X.X:{port} (depuis un autre PC)\n")

    if debug:
        print("   MODE DEVELOPPEMENT (Flask debug)\n")
        print("=" * 60)
        app.run(debug=True, host=host, port=port)
    else:
        from waitress import create_server
        print("   Serveur : Waitress (production)")
        print("   Threads : 4\n")
        print("=" * 60)
        server = create_server(app, host=host, port=port, threads=4)
        server.run()
