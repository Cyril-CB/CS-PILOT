"""
Blueprint Authentification : login, logout, index, setup initial.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import hashlib
from werkzeug.security import check_password_hash, generate_password_hash
from database import get_db
from extensions import limiter
from utils import validate_password_strength

auth = Blueprint('auth', __name__)


def _has_any_user():
    """Vérifie s'il existe au moins un utilisateur dans la base."""
    conn = get_db()
    try:
        row = conn.execute('SELECT COUNT(*) as nb FROM users').fetchone()
        return row['nb'] > 0
    finally:
        conn.close()


@auth.route('/')
def index():
    """Page d'accueil - redirige selon le profil"""
    if not _has_any_user():
        return redirect(url_for('auth.setup'))
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    if session.get('profil') == 'prestataire':
        return redirect(url_for('prepa_paie_bp.prepa_paie'))
    return redirect(url_for('dashboard_bp.dashboard'))


@auth.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    """Page de connexion"""
    # Rediriger vers le setup si aucun utilisateur n'existe
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
                'SELECT * FROM users WHERE login = ? AND actif = 1',
                (login_val,)
            ).fetchone()

            password_ok = False
            if user:
                stored = user['password']
                # Détection d'un ancien hash SHA256 (64 caractères hexadécimaux)
                if len(stored) == 64 and all(c in '0123456789abcdef' for c in stored):
                    if hashlib.sha256(password.encode()).hexdigest() == stored:
                        password_ok = True
                        # Migration vers un hash sécurisé (werkzeug)
                        new_hash = generate_password_hash(password)
                        conn.execute('UPDATE users SET password = ? WHERE id = ?',
                                     (new_hash, user['id']))
                        conn.commit()
                else:
                    password_ok = check_password_hash(stored, password)
        finally:
            conn.close()

        if password_ok:
            session['user_id'] = user['id']
            session['nom'] = user['nom']
            session['prenom'] = user['prenom']
            session['profil'] = user['profil']
            flash(f'Bienvenue {user["prenom"]} {user["nom"]} !', 'success')
            if user['profil'] == 'prestataire':
                return redirect(url_for('prepa_paie_bp.prepa_paie'))
            return redirect(url_for('dashboard_bp.dashboard'))
        else:
            flash('Identifiants incorrects', 'error')

    return render_template('login.html')


@auth.route('/setup', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def setup():
    """Configuration initiale - création du premier compte administrateur."""
    # Si des utilisateurs existent déjà, rediriger vers le login
    if _has_any_user():
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        nom = request.form.get('nom', '').strip()
        prenom = request.form.get('prenom', '').strip()
        login_val = request.form.get('login', '').strip()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')

        # Validations
        errors = []
        if not nom or not prenom or not login_val:
            errors.append('Tous les champs sont obligatoires')

        if not password:
            errors.append('Le mot de passe est obligatoire')
        else:
            password_errors = validate_password_strength(password)
            errors.extend(password_errors)

        if password != password_confirm:
            errors.append('Les mots de passe ne correspondent pas')

        if errors:
            for err in errors:
                flash(err, 'error')
            return render_template('setup.html')

        # Vérification finale qu'aucun utilisateur n'a été créé entre-temps
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


@auth.route('/logout')
def logout():
    """Déconnexion"""
    session.clear()
    flash('Vous êtes déconnecté', 'info')
    return redirect(url_for('auth.login'))
