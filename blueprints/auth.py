"""
Blueprint Authentification : login, logout, index, setup initial.
"""
import hashlib
import html
import logging
import secrets
import string

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db
from email_service import envoyer_email, is_email_configured
from extensions import limiter
from utils import validate_password_strength

auth = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)
SPECIAL_PASSWORD_CHARACTERS = '!@#$%^&*()-_=+[]{};:,.?'


def _has_any_user():
    """Vérifie s'il existe au moins un utilisateur dans la base."""
    conn = get_db()
    try:
        row = conn.execute('SELECT COUNT(*) as nb FROM users').fetchone()
        return row['nb'] > 0
    finally:
        conn.close()


def _verify_password(conn, user, password):
    """Vérifie un mot de passe et migre les anciens hash SHA256 si nécessaire."""
    stored = user['password']
    if len(stored) == 64 and all(c in '0123456789abcdef' for c in stored):
        if hashlib.sha256(password.encode()).hexdigest() == stored:
            conn.execute(
                'UPDATE users SET password = ? WHERE id = ?',
                (generate_password_hash(password), user['id'])
            )
            return True
        return False
    return check_password_hash(stored, password)


def _populate_session(user):
    """Charge les informations essentielles de l'utilisateur en session."""
    session['user_id'] = user['id']
    session['nom'] = user['nom']
    session['prenom'] = user['prenom']
    session['profil'] = user['profil']
    session['force_password_change'] = bool(user['force_password_change'])


def _redirect_after_login(profil):
    """Redirige vers la page d'accueil du profil."""
    if profil == 'prestataire':
        return redirect(url_for('prepa_paie_bp.prepa_paie'))
    return redirect(url_for('dashboard_bp.dashboard'))


def _generate_temporary_password(length=12):
    """Génère un mot de passe temporaire conforme à la politique de sécurité."""
    alphabet = string.ascii_letters + string.digits + SPECIAL_PASSWORD_CHARACTERS
    password_chars = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(SPECIAL_PASSWORD_CHARACTERS),
    ]
    while len(password_chars) < max(length, 8):
        password_chars.append(secrets.choice(alphabet))
    secrets.SystemRandom().shuffle(password_chars)
    return ''.join(password_chars)


@auth.before_app_request
def enforce_password_change():
    """Force le changement du mot de passe initial avant tout autre accès."""
    if 'user_id' not in session or not session.get('force_password_change'):
        return None

    endpoint = request.endpoint or ''
    allowed_endpoints = {
        'auth.changer_mot_de_passe',
        'auth.logout',
        'static',
    }
    if endpoint in allowed_endpoints or endpoint.startswith('static'):
        return None

    if endpoint != 'auth.login':
        flash('Veuillez définir votre mot de passe personnel avant de continuer.', 'warning')
    return redirect(url_for('auth.changer_mot_de_passe'))


@auth.route('/')
def index():
    """Page d'accueil - redirige selon le profil"""
    if not _has_any_user():
        return redirect(url_for('auth.setup'))
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    return _redirect_after_login(session.get('profil'))


@auth.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    """Page de connexion"""
    if not _has_any_user():
        return redirect(url_for('auth.setup'))

    if request.method == 'POST':
        login_val = request.form.get('login', '').strip()
        password = request.form.get('password', '')

        if not login_val or not password:
            flash('Identifiants incorrects', 'error')
            return render_template('login.html')

        conn = get_db()
        try:
            user = conn.execute(
                'SELECT id, nom, prenom, profil, password, force_password_change '
                'FROM users WHERE login = ? AND actif = 1',
                (login_val,)
            ).fetchone()

            password_ok = bool(user and _verify_password(conn, user, password))
            if password_ok:
                conn.commit()
        finally:
            conn.close()

        if password_ok:
            _populate_session(user)
            flash(f'Bienvenue {user["prenom"]} {user["nom"]} !', 'success')
            if user['force_password_change']:
                flash('Votre mot de passe temporaire doit être remplacé avant de continuer.', 'warning')
                return redirect(url_for('auth.changer_mot_de_passe'))
            return _redirect_after_login(user['profil'])

        flash('Identifiants incorrects', 'error')

    return render_template('login.html')


@auth.route('/setup', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def setup():
    """Configuration initiale - création du premier compte administrateur."""
    if _has_any_user():
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        nom = request.form.get('nom', '').strip()
        prenom = request.form.get('prenom', '').strip()
        login_val = request.form.get('login', '').strip()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')

        errors = []
        if not nom or not prenom or not login_val:
            errors.append('Tous les champs sont obligatoires')

        if not password:
            errors.append('Le mot de passe est obligatoire')
        else:
            errors.extend(validate_password_strength(password))

        if password != password_confirm:
            errors.append('Les mots de passe ne correspondent pas')

        if errors:
            for err in errors:
                flash(err, 'error')
            return render_template('setup.html')

        conn = get_db()
        try:
            row = conn.execute('SELECT COUNT(*) as nb FROM users').fetchone()
            if row['nb'] > 0:
                flash('Un compte existe déjà. Veuillez vous connecter.', 'warning')
                return redirect(url_for('auth.login'))

            password_hash = generate_password_hash(password)
            conn.execute('''
                INSERT INTO users (nom, prenom, login, password, profil)
                VALUES (?, ?, ?, ?, ?)
            ''', (nom, prenom, login_val, password_hash, 'directeur'))
            conn.commit()
        finally:
            conn.close()

        flash('Compte administrateur créé avec succès. Vous pouvez maintenant vous connecter.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('setup.html')


@auth.route('/changer_mot_de_passe', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def changer_mot_de_passe():
    """Permet à l'utilisateur connecté de définir son mot de passe personnel."""
    if 'user_id' not in session:
        flash('Veuillez vous connecter', 'warning')
        return redirect(url_for('auth.login'))

    conn = get_db()
    try:
        user = conn.execute(
            'SELECT id, nom, prenom, profil, password, force_password_change '
            'FROM users WHERE id = ? AND actif = 1',
            (session['user_id'],)
        ).fetchone()
        if not user:
            session.clear()
            flash('Votre session a expiré. Veuillez vous reconnecter.', 'warning')
            return redirect(url_for('auth.login'))

        if request.method == 'POST':
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            password_confirm = request.form.get('password_confirm', '')

            errors = []
            if not _verify_password(conn, user, current_password):
                errors.append('Le mot de passe actuel est incorrect')

            errors.extend(validate_password_strength(new_password))

            if new_password != password_confirm:
                errors.append('Les mots de passe ne correspondent pas')

            if current_password and current_password == new_password:
                errors.append("Le nouveau mot de passe doit être différent de l'actuel")

            if errors:
                for err in errors:
                    flash(err, 'error')
                return render_template('changer_mot_de_passe.html', force_change=bool(user['force_password_change']))

            conn.execute(
                'UPDATE users SET password = ?, force_password_change = 0 WHERE id = ?',
                (generate_password_hash(new_password), user['id'])
            )
            conn.commit()
            session['force_password_change'] = False
            flash('Votre mot de passe a été mis à jour.', 'success')
            return _redirect_after_login(user['profil'])
    finally:
        conn.close()

    return render_template('changer_mot_de_passe.html', force_change=bool(user['force_password_change']))


@auth.route('/mot-de-passe-oublie', methods=['GET', 'POST'])
@limiter.limit("3 per hour", methods=["POST"])
def mot_de_passe_oublie():
    """Envoie un mot de passe temporaire par email."""
    if not _has_any_user():
        return redirect(url_for('auth.setup'))

    if request.method == 'POST':
        login_val = request.form.get('login', '').strip()
        if not login_val:
            flash('Veuillez saisir votre identifiant.', 'error')
            return render_template('forgot_password.html')

        if not is_email_configured():
            flash("La récupération par email n'est pas disponible. Contactez la direction.", 'error')
            return render_template('forgot_password.html')

        conn = get_db()
        try:
            user = conn.execute(
                'SELECT id, login, prenom, email FROM users WHERE login = ? AND actif = 1',
                (login_val,)
            ).fetchone()

            generic_message = (
                "Si un compte actif avec une adresse email existe pour cet identifiant, "
                "un mot de passe temporaire vient d'être envoyé."
            )

            if not user or not user['email']:
                flash(generic_message, 'info')
                return redirect(url_for('auth.login'))

            temporary_password = _generate_temporary_password()
            contenu = f"""
            <h3 style="color:#667eea;margin:0 0 12px;font-size:16px;">Réinitialisation de votre mot de passe</h3>
            <p>Voici votre mot de passe temporaire :</p>
            <div style="background:#f3f4f6;border-radius:6px;padding:14px 16px;font-size:18px;font-weight:700;letter-spacing:1px;margin:16px 0;">
                {html.escape(temporary_password)}
            </div>
            <p>Connectez-vous avec ce mot de passe temporaire puis définissez immédiatement votre mot de passe personnel.</p>
            """

            conn.execute(
                'UPDATE users SET password = ?, force_password_change = 1 WHERE id = ?',
                (generate_password_hash(temporary_password), user['id'])
            )
            ok, message = envoyer_email(
                user['email'],
                'Réinitialisation de votre mot de passe',
                contenu,
                user['prenom']
            )
            if ok:
                conn.commit()
                flash(generic_message, 'info')
                return redirect(url_for('auth.login'))

            conn.rollback()
            logger.warning(
                "Impossible d'envoyer l'email de réinitialisation pour %s: %s",
                login_val,
                message
            )
            flash("Impossible d'envoyer l'email de réinitialisation pour le moment.", 'error')
        finally:
            conn.close()

    return render_template('forgot_password.html')


@auth.route('/logout')
def logout():
    """Déconnexion"""
    session.clear()
    flash('Vous êtes déconnecté', 'info')
    return redirect(url_for('auth.login'))
