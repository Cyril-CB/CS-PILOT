"""Notes de service et informations de la direction aux salariés."""
import logging
from datetime import date
from functools import wraps

from flask import (
    Blueprint, abort, flash, jsonify, redirect, render_template, request,
    session, url_for,
)

from database import get_db
from email_service import (
    is_email_configured, notifier_publication_direction, peut_envoyer_email,
)
from utils import aujourd_hui, login_required, maintenant

messages_direction_bp = Blueprint('messages_direction_bp', __name__)
logger = logging.getLogger(__name__)
PROFILS_GESTION = ('directeur', 'comptable')
PROFILS_LECTURE = ('salarie', 'responsable', 'directeur', 'comptable')


def gestion_required(f):
    """Le menu ne remplace pas le contrôle d'accès aux écritures et archives."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('profil') not in PROFILS_GESTION:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def _archiver_messages_expires(conn):
    """L'appelant conserve la transaction et son commit."""
    conn.execute('''
        UPDATE messages_direction SET statut = 'archive',
            archive_le = COALESCE(archive_le, ?)
        WHERE statut = 'actif' AND date_validite < ?
    ''', (maintenant().strftime('%Y-%m-%d %H:%M:%S'), aujourd_hui().isoformat()))


def get_message_actif(conn, user_id=None):
    """Exclut aussi les messages expirés avant leur archivage matériel."""
    return conn.execute('''
        SELECT m.*, u.prenom AS auteur_prenom, u.nom AS auteur_nom
        FROM messages_direction m LEFT JOIN users u ON u.id = m.cree_par
        WHERE m.statut = 'actif' AND m.date_validite >= ?
          AND (? IS NULL OR NOT EXISTS (
              SELECT 1 FROM messages_direction_lectures l
              WHERE l.message_id = m.id AND l.user_id = ?
          ))
        ORDER BY m.created_at DESC, m.id DESC LIMIT 1
    ''', (aujourd_hui().isoformat(), user_id, user_id)).fetchone()


def _notifier_publication_par_email(conn, titre, contenu, date_validite, auteur_id):
    """Même audience et consentement que le CSE ; aucun envoi ne bloque la note."""
    try:
        if not is_email_configured():
            return 0
        candidats = conn.execute('''
            SELECT id, prenom FROM users WHERE actif = 1
              AND profil IN ('salarie', 'responsable', 'directeur', 'comptable')
              AND email IS NOT NULL AND TRIM(email) != ''
        ''').fetchall()
        destinataires = []
        for candidat in candidats:
            peut, email = peut_envoyer_email(candidat['id'])
            if peut and email:
                destinataires.append((email, candidat['prenom']))
        if not destinataires:
            return 0
        auteur = conn.execute('SELECT prenom, nom FROM users WHERE id = ?',
                              (auteur_id,)).fetchone()
        auteur_nom = f"{auteur['prenom']} {auteur['nom']}".strip() if auteur else ''
        succes, _, _ = notifier_publication_direction(
            destinataires, titre, contenu, date_validite, auteur_nom)
        return succes
    except Exception:
        logger.warning('Notification de publication direction indisponible.')
        return 0


@messages_direction_bp.route('/direction/messages')
@login_required
@gestion_required
def messages():
    """Publication et archives réservées à la direction et à la comptabilité."""
    conn = get_db()
    try:
        _archiver_messages_expires(conn)
        conn.commit()
        message_actif = get_message_actif(conn)
        archives = conn.execute('''
            SELECT m.*, u.prenom AS auteur_prenom, u.nom AS auteur_nom
            FROM messages_direction m LEFT JOIN users u ON u.id = m.cree_par
            WHERE m.statut = 'archive' ORDER BY m.created_at DESC, m.id DESC
        ''').fetchall()
    finally:
        conn.close()
    return render_template('messages_direction.html', message_actif=message_actif,
                           archives=archives, aujourd_hui=aujourd_hui().isoformat())


@messages_direction_bp.route('/direction/messages/creer', methods=['POST'])
@login_required
@gestion_required
def creer_message():
    """Archive le précédent et publie son remplacement dans la même transaction."""
    titre = (request.form.get('titre') or '').strip()
    contenu = (request.form.get('contenu') or '').strip()
    valeur_date = (request.form.get('date_validite') or '').strip()
    erreur = None
    try:
        date_validite = date.fromisoformat(valeur_date)
        if date_validite.isoformat() != valeur_date:
            raise ValueError
        if date_validite < aujourd_hui():
            erreur = "La date de validité doit être aujourd'hui ou dans le futur."
    except ValueError:
        erreur = 'La date de validité est invalide.'
    if not contenu:
        erreur = 'Le contenu du message est obligatoire.'
    elif len(titre) > 150 or len(contenu) > 20000:
        erreur = 'Limitez le titre à 150 caractères et le message à 20 000 caractères.'
    if erreur:
        flash(erreur, 'error')
        return redirect(url_for('messages_direction_bp.messages'))

    conn = get_db()
    try:
        conn.execute('''
            UPDATE messages_direction SET statut = 'archive',
                archive_le = COALESCE(archive_le, ?) WHERE statut = 'actif'
        ''', (maintenant().strftime('%Y-%m-%d %H:%M:%S'),))
        conn.execute('''
            INSERT INTO messages_direction (titre, contenu, date_validite, cree_par)
            VALUES (?, ?, ?, ?)
        ''', (titre or None, contenu, valeur_date, session['user_id']))
        conn.commit()
        nb_notifies = 0
        if request.form.get('notifier_email'):
            nb_notifies = _notifier_publication_par_email(
                conn, titre, contenu, valeur_date, session['user_id'])
        if nb_notifies:
            flash(f'Le message a été publié et {nb_notifies} personne(s) notifiée(s) par e-mail.', 'success')
        else:
            flash('Le message a été publié.', 'success')
    finally:
        conn.close()
    return redirect(url_for('messages_direction_bp.messages'))


@messages_direction_bp.route('/direction/messages/<int:message_id>/archiver', methods=['POST'])
@login_required
@gestion_required
def archiver_message(message_id):
    conn = get_db()
    try:
        message = conn.execute('SELECT id FROM messages_direction WHERE id = ?',
                               (message_id,)).fetchone()
        if not message:
            abort(404)
        conn.execute('''
            UPDATE messages_direction SET statut = 'archive',
                archive_le = COALESCE(archive_le, ?) WHERE id = ?
        ''', (maintenant().strftime('%Y-%m-%d %H:%M:%S'), message_id))
        conn.commit()
    finally:
        conn.close()
    flash('Le message a été retiré et archivé.', 'success')
    return redirect(url_for('messages_direction_bp.messages'))


@messages_direction_bp.route('/direction/messages/<int:message_id>/lire', methods=['POST'])
@login_required
def lire_message(message_id):
    """La confirmation ne masque que le message pour l'utilisateur connecté."""
    if session.get('profil') not in PROFILS_LECTURE:
        return jsonify({'ok': False, 'erreur': 'Accès refusé.'}), 403
    conn = get_db()
    try:
        user_id = session['user_id']
        utilisateur = conn.execute('''
            SELECT id FROM users WHERE id = ? AND actif = 1
              AND profil IN ('salarie', 'responsable', 'directeur', 'comptable')
        ''', (user_id,)).fetchone()
        message = conn.execute('''
            SELECT id FROM messages_direction
            WHERE id = ? AND statut = 'actif' AND date_validite >= ?
        ''', (message_id, aujourd_hui().isoformat())).fetchone()
        if not utilisateur or not message:
            return jsonify({'ok': False, 'erreur': 'Message indisponible.'}), 404
        conn.execute('''
            INSERT OR IGNORE INTO messages_direction_lectures (message_id, user_id)
            VALUES (?, ?)
        ''', (message_id, user_id))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()
