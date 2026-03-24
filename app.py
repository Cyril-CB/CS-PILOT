"""
Application de Gestion du Temps de Travail - Point d'entrée principal.
Architecture en Blueprints Flask.
"""
import os
import sys
import secrets
from dotenv import load_dotenv
from flask import Flask, session, render_template, flash, redirect, url_for
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix
from database import init_db, get_db, DATA_DIR
from extensions import csrf, limiter


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

# ==================== Initialisation des extensions ====================
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
from blueprints.alsh import alsh_bp
from blueprints.mise_a_jour import mise_a_jour_bp
from blueprints.rh_statistiques import rh_statistiques_bp
from blueprints.dashboard_responsable import dashboard_responsable_bp
from blueprints.dashboard_comptable import dashboard_comptable_bp
from blueprints.chatbot import chatbot_bp
from blueprints.compte_resultat import compte_resultat_bp
from blueprints.indicateurs_financiers import indicateurs_financiers_bp
from blueprints.import_bi import import_bi_bp

app.register_blueprint(auth)
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
app.register_blueprint(alsh_bp)
app.register_blueprint(mise_a_jour_bp)
app.register_blueprint(rh_statistiques_bp)
app.register_blueprint(chatbot_bp)
app.register_blueprint(compte_resultat_bp)
app.register_blueprint(indicateurs_financiers_bp)
app.register_blueprint(import_bi_bp)


# ==================== Context Processors ====================
_cached_app_version = None

@app.context_processor
def inject_version():
    """Injecte la version de l'application dans tous les templates (mise en cache)."""
    global _cached_app_version
    if _cached_app_version is None:
        from migration_manager import get_version_actuelle
        version_db = get_version_actuelle()
        try:
            _cached_app_version = f'1.1.{int(version_db)}'
        except (ValueError, TypeError):
            _cached_app_version = '1.1.0'
    return {'app_version': _cached_app_version}


def invalidate_version_cache():
    """Invalide le cache de version (a appeler apres une migration)."""
    global _cached_app_version
    _cached_app_version = None


@app.context_processor
def inject_pending_counts():
    """Injecte le nombre de demandes en attente dans tous les templates."""
    if 'user_id' not in session:
        return {'pending_count': 0, 'chatbot_enabled': False}

    profil = session.get('profil', '')
    conn = None
    try:
        conn = get_db()

        if profil == 'directeur' or profil == 'comptable':
            row = conn.execute(
                "SELECT COUNT(*) as nb FROM demandes_recup WHERE statut IN ('en_attente_direction', 'en_attente_responsable')"
            ).fetchone()
        elif profil == 'responsable':
            user = conn.execute("SELECT secteur_id FROM users WHERE id = ?", (session['user_id'],)).fetchone()
            sid = user['secteur_id'] if user else None
            if sid:
                row = conn.execute(
                    """SELECT COUNT(*) as nb FROM demandes_recup d
                       JOIN users u ON d.user_id = u.id
                       WHERE u.secteur_id = ? AND d.statut = 'en_attente_responsable'""",
                    (sid,)
                ).fetchone()
            else:
                row = {'nb': 0}
        else:
            row = {'nb': 0}

        count = row['nb'] if row else 0
        chatbot_on = False
        try:
            from utils import get_setting as _gs
            chatbot_on = _gs('chatbot_model') is not None
        except Exception:
            pass
        return {'pending_count': count, 'chatbot_enabled': chatbot_on}
    except Exception:
        return {'pending_count': 0, 'chatbot_enabled': False}
    finally:
        if conn:
            conn.close()


@app.errorhandler(429)
def ratelimit_handler(e):
    """Affiche un message clair quand la limite de tentatives est atteinte."""
    flash('Trop de tentatives. Veuillez patienter avant de réessayer.', 'error')
    return render_template('login.html'), 429


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    """Gestion des erreurs CSRF : redirige vers login avec message explicite."""
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
