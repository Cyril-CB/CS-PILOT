"""
Blueprint notifications_bp.
Configuration email et envoi de notifications manuelles.
Acces : directeur, comptable.
"""
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from database import get_db
from delegations import MISSION_SUIVI_VALIDATIONS_RELANCES, user_has_delegation
from utils import login_required, get_setting, NOMS_MOIS
from email_service import (
    get_email_config, save_email_config, set_email_enabled,
    is_email_configured, envoyer_email, notifier_relance_validation,
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

        if not sender or not password:
            flash('L\'adresse email et le mot de passe sont obligatoires', 'error')
            return redirect(url_for('notifications_bp.configuration_email'))

        save_email_config(smtp_server, smtp_port, sender, password, sender_name)
        flash('Configuration email enregistree avec succes', 'success')
        return redirect(url_for('notifications_bp.configuration_email'))

    config = get_email_config()
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


@notifications_bp.route('/api/email/relance_validation', methods=['POST'])
@login_required
def relance_validation():
    """Envoie une relance aux responsables pour les fiches d'heures non validees."""
    if session.get('profil') != 'directeur' and not user_has_delegation(
        session.get('user_id'),
        MISSION_SUIVI_VALIDATIONS_RELANCES,
    ):
        return jsonify({'error': 'Acces reserve au directeur'}), 403

    if not is_email_configured():
        return jsonify({'error': 'Service email non configure'}), 400

    data = request.get_json()
    mois = data.get('mois')
    annee = data.get('annee')

    if not mois or not annee:
        return jsonify({'error': 'Mois et annee requis'}), 400

    conn = get_db()

    # Trouver les responsables qui ont des fiches non validees dans leur secteur
    responsables = conn.execute('''
        SELECT DISTINCT r.id, r.nom, r.prenom, r.email, r.secteur_id
        FROM users r
        WHERE r.profil = 'responsable' AND r.actif = 1 AND r.email IS NOT NULL AND r.email != ''
    ''').fetchall()

    expediteur = conn.execute('SELECT nom, prenom FROM users WHERE id = ?',
                              (session['user_id'],)).fetchone()
    expediteur_nom = f"{expediteur['prenom']} {expediteur['nom']}" if expediteur else 'La direction'

    nb_envoyes = 0
    nb_echecs = 0
    erreurs = []

    for resp in responsables:
        # Compter les fiches non validees par ce responsable dans son secteur
        fiches_en_attente = conn.execute('''
            SELECT COUNT(*) as nb FROM users u
            WHERE u.actif = 1 AND u.profil = 'salarie' AND u.secteur_id = ?
            AND u.id NOT IN (
                SELECT v.user_id FROM validations v
                WHERE v.mois = ? AND v.annee = ? AND v.validation_responsable IS NOT NULL
            )
        ''', (resp['secteur_id'], mois, annee)).fetchone()

        nb_fiches = fiches_en_attente['nb'] if fiches_en_attente else 0

        if nb_fiches > 0:
            ok, msg = notifier_relance_validation(
                resp['email'], resp['prenom'],
                NOMS_MOIS[int(mois)], annee, nb_fiches, expediteur_nom
            )
            if ok:
                nb_envoyes += 1
            else:
                nb_echecs += 1
                erreurs.append(f"{resp['prenom']} {resp['nom']}: {msg}")

    conn.close()

    if nb_envoyes == 0 and nb_echecs == 0:
        return jsonify({'success': True, 'message': 'Aucun responsable a relancer (toutes les fiches sont validees)'})

    success = nb_envoyes > 0
    result = {'success': success, 'nb_envoyes': nb_envoyes, 'nb_echecs': nb_echecs}
    if nb_envoyes > 0:
        result['message'] = f'Relance envoyee a {nb_envoyes} responsable(s)'
    elif nb_echecs > 0:
        result['message'] = "Echec de l'envoi des relances"
    if erreurs:
        result['erreurs'] = erreurs
    return jsonify(result), 200 if success else 500


@notifications_bp.route('/api/email/relance_responsable', methods=['POST'])
@login_required
def relance_responsable_unique():
    """Envoie une relance a un responsable specifique pour les fiches non validees."""
    if session.get('profil') != 'directeur' and not user_has_delegation(
        session.get('user_id'),
        MISSION_SUIVI_VALIDATIONS_RELANCES,
    ):
        return jsonify({'error': 'Acces reserve au directeur'}), 403

    if not is_email_configured():
        return jsonify({'error': 'Service email non configure'}), 400

    data = request.get_json()
    responsable_id = data.get('responsable_id')
    mois = data.get('mois')
    annee = data.get('annee')

    if not responsable_id or not mois or not annee:
        return jsonify({'error': 'Parametres manquants'}), 400

    conn = get_db()

    resp = conn.execute('''
        SELECT id, nom, prenom, email, secteur_id FROM users
        WHERE id = ? AND profil = 'responsable' AND actif = 1
    ''', (responsable_id,)).fetchone()

    if not resp:
        conn.close()
        return jsonify({'error': 'Responsable introuvable'}), 404

    if not resp['email']:
        conn.close()
        return jsonify({'error': f"{resp['prenom']} {resp['nom']} n'a pas d'adresse email configuree"}), 400

    # Compter les fiches en attente
    fiches_en_attente = conn.execute('''
        SELECT COUNT(*) as nb FROM users u
        WHERE u.actif = 1 AND u.profil = 'salarie' AND u.secteur_id = ?
        AND u.id NOT IN (
            SELECT v.user_id FROM validations v
            WHERE v.mois = ? AND v.annee = ? AND v.validation_responsable IS NOT NULL
        )
    ''', (resp['secteur_id'], mois, annee)).fetchone()

    nb_fiches = fiches_en_attente['nb'] if fiches_en_attente else 0

    expediteur = conn.execute('SELECT nom, prenom FROM users WHERE id = ?',
                              (session['user_id'],)).fetchone()
    expediteur_nom = f"{expediteur['prenom']} {expediteur['nom']}" if expediteur else 'La direction'

    conn.close()

    if nb_fiches == 0:
        return jsonify({'success': True, 'message': f"Toutes les fiches sont deja validees pour le secteur de {resp['prenom']} {resp['nom']}"})

    ok, msg = notifier_relance_validation(
        resp['email'], resp['prenom'],
        NOMS_MOIS[int(mois)], annee, nb_fiches, expediteur_nom
    )

    if ok:
        return jsonify({'success': True, 'message': f"Relance envoyee a {resp['prenom']} {resp['nom']}"})
    else:
        return jsonify({'error': msg}), 400
