"""Compte courant et révocation de toutes ses sessions, sans cache de droits."""
from flask import flash, redirect, session, url_for


CHAMPS_COMPTE = ('id, nom, prenom, profil, secteur_id, actif, '
                 'force_password_change, session_version')


def creer_schema(conn):
    colonnes = {r[1] for r in conn.execute('PRAGMA table_info(users)')}
    if 'session_version' not in colonnes:
        conn.execute('ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1')
    # Couvre aussi les écritures SQL hors des formulaires d'administration.
    # Réactiver un compte ne doit jamais rendre ses anciens cookies valides.
    conn.execute('''
        CREATE TRIGGER IF NOT EXISTS users_revoquer_sessions
        AFTER UPDATE OF actif, password ON users
        WHEN NEW.actif IS NOT OLD.actif OR NEW.password IS NOT OLD.password
        BEGIN
            UPDATE users SET session_version = OLD.session_version + 1 WHERE id = NEW.id;
        END
    ''')


def charger_compte(conn, user_id):
    return conn.execute(f'SELECT {CHAMPS_COMPTE} FROM users WHERE id = ?', (user_id,)).fetchone()


def actualiser_session(user):
    """Ces champs ne sont jamais une source autonome d'autorisation."""
    for cle in ('nom', 'prenom', 'profil', 'secteur_id'):
        session[cle] = user[cle]
    session['force_password_change'] = bool(user['force_password_change'])


def verifier_session(conn):
    """Vérifie et rafraîchit le compte dans la connexion de l'appelant.

    Renvoie False pour un cookie antérieur à cette protection. Ne renouvelle
    jamais son compteur : seule une authentification réussie le peut.
    Sans commit ni journal indépendant : utilisable sous BEGIN IMMEDIATE.
    """
    user = charger_compte(conn, session.get('user_id'))
    if (not user or user['actif'] != 1
            or session.get('session_version') != user['session_version']):
        return False
    actualiser_session(user)
    return True


def session_expiree():
    session.clear()
    flash('Votre session a expiré. Veuillez vous reconnecter.', 'warning')
    return redirect(url_for('auth.login'))


def verifier_action(conn):
    """Recontrôle sous le verrou d'écriture avant une décision sensible."""
    if not verifier_session(conn):
        return session_expiree()
    if session.get('force_password_change'):
        flash('Veuillez définir votre mot de passe personnel avant de continuer.', 'warning')
        return redirect(url_for('auth.changer_mot_de_passe'))
    return None
