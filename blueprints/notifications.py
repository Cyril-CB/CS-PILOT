"""
Blueprint notifications_bp.
Configuration email et envoi de notifications manuelles.
Acces : directeur, comptable.
"""
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from database import get_db
from blueprints.delegations import MISSION_SUIVI_VALIDATIONS_RELANCES, user_has_delegation
from utils import login_required, get_setting, NOMS_MOIS
from email_service import (
    get_email_config, save_email_config, set_email_enabled,
    is_email_configured, envoyer_email,
    get_base_url, save_base_url,
)

notifications_bp = Blueprint('notifications_bp', __name__)

PROFILS_AUTORISES = ['directeur', 'comptable']


@notifications_bp.route('/configuration_email', methods=['GET', 'POST'])
@login_required
def configuration_email():
    """Page de configuration du service email."""
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Acces non autorise', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    if request.method == 'POST':
        smtp_server = request.form.get('smtp_server', 'smtp.gmail.com').strip()
        smtp_port = request.form.get('smtp_port', '587').strip()
        sender = request.form.get('sender', '').strip()
        password = request.form.get('password', '').strip()
        sender_name = request.form.get('sender_name', 'CS-PILOT').strip()
        base_url = request.form.get('base_url', '').strip()

        # Mot de passe conservé si le champ est laissé vide : on peut modifier
        # un autre réglage (domaine, expéditeur…) sans avoir à ressaisir le mot
        # de passe d'application — évite les erreurs de re-saisie / l'autofill.
        est_gmail = 'gmail' in smtp_server.lower()
        password_saisi = bool(password)
        if not password:
            password = (get_email_config().get('password') or '').strip()
        elif est_gmail:
            # Les mots de passe d'application Google se collent souvent avec les
            # espaces d'affichage (« xxxx xxxx xxxx xxxx »), ce que Gmail refuse.
            password = password.replace(' ', '')

        if not sender or not password:
            flash('L\'adresse email et le mot de passe sont obligatoires', 'error')
            return redirect(url_for('notifications_bp.configuration_email'))

        save_email_config(smtp_server, smtp_port, sender, password, sender_name)
        save_base_url(base_url)

        # Un mot de passe d'application Google fait exactement 16 caractères. Une
        # autre longueur trahit presque toujours la cause d'un échec d'authentif :
        # espaces oubliés, ou mot de passe habituel saisi/autofillé à la place.
        if password_saisi and est_gmail and len(password) != 16:
            flash(
                f'Attention : un mot de passe d\'application Google fait 16 caracteres, '
                f'or celui saisi en fait {len(password)}. Verifiez que vous avez colle le '
                f'mot de passe d\'application (et non votre mot de passe habituel).',
                'warning',
            )
        flash('Configuration email enregistree avec succes', 'success')
        return redirect(url_for('notifications_bp.configuration_email'))

    config = get_email_config()
    config['base_url'] = get_base_url() or ''
    # Masquer le mot de passe
    if config.get('password'):
        config['password_display'] = '*' * 8
    else:
        config['password_display'] = ''

    return render_template('configuration_email.html', config=config)


@notifications_bp.route('/api/email/toggle', methods=['POST'])
@login_required
def toggle_email():
    """Active ou desactive l'envoi d'emails."""
    if session.get('profil') not in PROFILS_AUTORISES:
        return jsonify({'error': 'Acces non autorise'}), 403

    data = request.get_json()
    enabled = data.get('enabled', False)
    set_email_enabled(enabled)
    return jsonify({'success': True, 'enabled': enabled})


@notifications_bp.route('/api/email/test', methods=['POST'])
@login_required
def test_email():
    """Envoie un email de test a l'adresse de l'expediteur."""
    if session.get('profil') not in PROFILS_AUTORISES:
        return jsonify({'error': 'Acces non autorise'}), 403

    config = get_email_config()
    if not config.get('sender') or not config.get('password'):
        return jsonify({'error': 'Configuration email incomplete'}), 400

    contenu = """
    <h3 style="color:#059669;margin:0 0 12px;font-size:16px;">Test de configuration reussi !</h3>
    <p>Si vous recevez cet email, la configuration SMTP de CS-PILOT est correcte.</p>
    <p>Les notifications par email sont maintenant operationnelles.</p>
    """

    ok, msg = envoyer_email(config['sender'], "Test de configuration email", contenu)

    if ok:
        return jsonify({'success': True, 'message': f'Email de test envoye a {config["sender"]}'})
    else:
        return jsonify({'error': msg}), 400


def _relances_fiches(responsable_id=None):
    """Relance uniquement l'acteur de l'étape courante, jamais les anciens verrous."""
    if session.get('profil') != 'directeur' and not user_has_delegation(
            session.get('user_id'), MISSION_SUIVI_VALIDATIONS_RELANCES):
        return jsonify({'error': 'Accès réservé à la direction ou aux utilisateurs délégués'}), 403
    data = request.get_json(silent=True) or {}
    try:
        mois, annee = int(data.get('mois')), int(data.get('annee'))
    except (ValueError, TypeError):
        return jsonify({'error': 'Mois et année requis'}), 400
    from utils import maintenant
    if not 1 <= mois <= 12 or not 1 <= annee <= 9998 or (annee, mois) >= (maintenant().year, maintenant().month):
        return jsonify({'error': 'Choisissez un mois terminé'}), 400
    if responsable_id is not None:
        try:
            responsable_id = int(responsable_id)
        except (ValueError, TypeError):
            return jsonify({'error': 'Responsable invalide'}), 400
    if not is_email_configured():
        return jsonify({'error': 'Service email non configuré'}), 400
    from fiches_circuit import destinataires_etape
    from email_service import peut_envoyer_email, notifier_relance_fiche
    conn = get_db()
    envoyes, echecs, sans_destinataire = 0, 0, 0
    try:
        salaries = conn.execute("SELECT id, prenom, nom FROM users WHERE actif=1 AND profil NOT IN ('directeur','prestataire')").fetchall()
        for sal in salaries:
            v = conn.execute('SELECT * FROM validations WHERE user_id=? AND mois=? AND annee=?',
                             (sal['id'], mois, annee)).fetchone()
            etape, acteurs = destinataires_etape(conn, sal['id'], v)
            if etape == 'termine':
                continue
            if not acteurs:
                sans_destinataire += 1
            for acteur in acteurs:
                if responsable_id is not None and (etape != 'responsable' or acteur['id'] != responsable_id):
                    continue
                peut, email = peut_envoyer_email(acteur['id'])
                if not peut:
                    continue
                ok, _ = notifier_relance_fiche(email, acteur['prenom'], mois, annee,
                                               f"{sal['prenom']} {sal['nom']}", sal['id'], etape)
                envoyes += int(ok)
                echecs += int(not ok)
    finally:
        conn.close()
    return jsonify({'success': not echecs, 'nb_envoyes': envoyes, 'nb_echecs': echecs,
                    'sans_responsable': sans_destinataire,
                    'message': f'{envoyes} relance(s) envoyée(s) aux acteurs attendus. '
                               f'{sans_destinataire} fiche(s) sans responsable applicable.'}), (500 if echecs else 200)


@notifications_bp.route('/api/email/relance_validation', methods=['POST'])
@login_required
def relance_validation():
    return _relances_fiches()


@notifications_bp.route('/api/email/relance_responsable', methods=['POST'])
@login_required
def relance_responsable():
    data = request.get_json(silent=True) or {}
    # Une valeur absente ne doit pas transformer une relance individuelle en lot.
    return _relances_fiches(data.get('responsable_id', ''))


@notifications_bp.route('/relancer_fiche_historique', methods=['POST'])
@login_required
def relancer_fiche_historique():
    if session.get('profil') != 'directeur':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    from fiches_circuit import historique_a_confirmer
    from email_service import peut_envoyer_email, notifier_relance_fiche
    uid = request.form.get('user_id', type=int)
    mois, annee = request.form.get('mois', type=int), request.form.get('annee', type=int)
    conn = get_db()
    try:
        v = conn.execute('SELECT * FROM validations WHERE user_id=? AND mois=? AND annee=?', (uid, mois, annee)).fetchone()
        sal = conn.execute('SELECT * FROM users WHERE id=? AND actif=1', (uid,)).fetchone()
        if not sal or not historique_a_confirmer(conn, v):
            flash('Aucune confirmation historique à relancer pour cette fiche.', 'info')
        else:
            peut, email = peut_envoyer_email(uid)
            if not peut or not is_email_configured():
                flash('Invitation non envoyée : vérifiez les notifications du salarié et la configuration email.', 'warning')
            else:
                ok, _ = notifier_relance_fiche(email, sal['prenom'], mois, annee,
                                               f"{sal['prenom']} {sal['nom']}", uid, 'salarie', historique=True)
                flash('Invitation à confirmer envoyée.' if ok else "L'invitation n'a pas pu être envoyée.",
                      'success' if ok else 'warning')
    finally:
        conn.close()
    return redirect(url_for('validation_bp.fiches_historiques'))
