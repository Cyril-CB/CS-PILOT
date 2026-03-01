"""
Service d'envoi d'emails via SMTP (Gmail).

Utilise les parametres stockes dans app_settings (chiffres).
Aucune dependance externe requise : utilise smtplib et email de la stdlib.
"""
import smtplib
import logging
import html as html_module
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from utils import get_setting, save_setting
from database import get_db

logger = logging.getLogger(__name__)

# Cles utilisees dans app_settings
EMAIL_SETTINGS_KEYS = {
    'smtp_server': 'email_smtp_server',
    'smtp_port': 'email_smtp_port',
    'sender': 'email_sender',
    'password': 'email_password',
    'sender_name': 'email_sender_name',
    'enabled': 'email_enabled',
}

DEFAULTS = {
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': '587',
    'sender_name': 'CS-PILOT',
}


def get_email_config():
    """Recupere la configuration email depuis app_settings."""
    config = {}
    for key, setting_key in EMAIL_SETTINGS_KEYS.items():
        val = get_setting(setting_key)
        if val is None and key in DEFAULTS:
            val = DEFAULTS[key]
        config[key] = val
    return config


def save_email_config(smtp_server, smtp_port, sender, password, sender_name):
    """Sauvegarde la configuration email dans app_settings (chiffree)."""
    save_setting(EMAIL_SETTINGS_KEYS['smtp_server'], smtp_server)
    save_setting(EMAIL_SETTINGS_KEYS['smtp_port'], str(smtp_port))
    save_setting(EMAIL_SETTINGS_KEYS['sender'], sender)
    save_setting(EMAIL_SETTINGS_KEYS['password'], password)
    save_setting(EMAIL_SETTINGS_KEYS['sender_name'], sender_name)
    save_setting(EMAIL_SETTINGS_KEYS['enabled'], 'true')


def set_email_enabled(enabled):
    """Active ou desactive l'envoi d'emails."""
    save_setting(EMAIL_SETTINGS_KEYS['enabled'], 'true' if enabled else 'false')


def is_email_configured():
    """Verifie que la configuration email est complete."""
    config = get_email_config()
    return all([
        config.get('sender'),
        config.get('password'),
        config.get('smtp_server'),
        config.get('smtp_port'),
        config.get('enabled') == 'true',
    ])


def _build_html_email(sujet, contenu_html, destinataire_prenom=''):
    """Construit le corps HTML de l'email avec un template simple et professionnel."""
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;padding:24px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    <!-- Header -->
    <tr>
        <td style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);padding:24px 32px;text-align:center;">
            <h1 style="color:#ffffff;margin:0;font-size:22px;font-weight:700;letter-spacing:1px;">CS-PILOT</h1>
            <p style="color:rgba(255,255,255,0.85);margin:4px 0 0;font-size:13px;">Gestion du Temps de Travail</p>
        </td>
    </tr>
    <!-- Contenu -->
    <tr>
        <td style="padding:28px 32px;">
            {f'<p style="color:#374151;font-size:15px;margin:0 0 16px;">Bonjour <strong>{html_module.escape(destinataire_prenom)}</strong>,</p>' if destinataire_prenom else ''}
            <div style="color:#374151;font-size:14px;line-height:1.7;">
                {contenu_html}
            </div>
        </td>
    </tr>
    <!-- Footer -->
    <tr>
        <td style="background:#f9fafb;padding:16px 32px;border-top:1px solid #e5e7eb;text-align:center;">
            <p style="color:#9ca3af;font-size:11px;margin:0;">
                Ce message a ete envoye automatiquement par CS-PILOT.<br>
                Merci de ne pas repondre directement a cet email.
            </p>
        </td>
    </tr>
</table>
</td></tr>
</table>
</body>
</html>"""
    return html


def envoyer_email(destinataire, sujet, contenu_html, destinataire_prenom=''):
    """Envoie un email via SMTP.

    Args:
        destinataire: adresse email du destinataire
        sujet: sujet de l'email
        contenu_html: contenu HTML du corps de l'email (sera encapsule dans le template)
        destinataire_prenom: prenom du destinataire (optionnel, pour la salutation)

    Returns:
        (success: bool, message: str)
    """
    if not destinataire:
        return False, "Adresse email du destinataire manquante"

    config = get_email_config()

    if config.get('enabled') != 'true':
        return False, "L'envoi d'emails est desactive"

    if not config.get('sender') or not config.get('password'):
        return False, "Configuration email incomplete"

    msg = MIMEMultipart('alternative')
    msg['From'] = f"{config.get('sender_name', 'CS-PILOT')} <{config['sender']}>"
    msg['To'] = destinataire
    msg['Subject'] = f"[CS-PILOT] {sujet}"

    html_body = _build_html_email(sujet, contenu_html, destinataire_prenom)
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    try:
        server = smtplib.SMTP(config['smtp_server'], int(config['smtp_port']), timeout=15)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(config['sender'], config['password'])
        server.send_message(msg)
        server.quit()
        logger.info("Email envoye a %s : %s", destinataire, sujet)
        return True, "Email envoye avec succes"
    except smtplib.SMTPAuthenticationError:
        logger.error("Echec authentification SMTP pour %s", config['sender'])
        return False, "Echec d'authentification SMTP. Verifiez l'adresse email et le mot de passe d'application."
    except smtplib.SMTPException as e:
        logger.error("Erreur SMTP : %s", str(e))
        return False, f"Erreur SMTP : {str(e)}"
    except Exception as e:
        logger.error("Erreur envoi email : %s", str(e))
        return False, f"Erreur : {str(e)}"


def envoyer_email_multiple(destinataires, sujet, contenu_html):
    """Envoie un meme email a plusieurs destinataires.

    Args:
        destinataires: liste de tuples (email, prenom)
        sujet: sujet de l'email
        contenu_html: contenu HTML

    Returns:
        (nb_succes: int, nb_echecs: int, erreurs: list)
    """
    nb_succes = 0
    nb_echecs = 0
    erreurs = []

    for email, prenom in destinataires:
        if not email:
            nb_echecs += 1
            erreurs.append(f"{prenom}: pas d'adresse email")
            continue

        ok, msg = envoyer_email(email, sujet, contenu_html, prenom)
        if ok:
            nb_succes += 1
        else:
            nb_echecs += 1
            erreurs.append(f"{prenom} ({email}): {msg}")

    return nb_succes, nb_echecs, erreurs


# ── Consentement salaries ──

# Profils qui n'ont pas besoin de consentement (mail professionnel)
PROFILS_SANS_CONSENTEMENT = ('directeur', 'comptable', 'responsable')


def peut_envoyer_email(user_id):
    """Verifie si un utilisateur peut recevoir des emails.

    Les directeurs, comptables et responsables recoivent toujours les mails.
    Les salaries doivent avoir explicitement accepte les notifications.

    Returns:
        (peut_envoyer: bool, email: str or None)
    """
    conn = get_db()
    try:
        user = conn.execute(
            'SELECT email, profil, email_notifications_enabled FROM users WHERE id = ?',
            (user_id,)
        ).fetchone()
    except Exception:
        # Colonne pas encore creee (migration pas appliquee)
        user = conn.execute(
            'SELECT email, profil FROM users WHERE id = ?',
            (user_id,)
        ).fetchone()
    conn.close()

    if not user or not user['email']:
        return False, None

    if user['profil'] in PROFILS_SANS_CONSENTEMENT:
        return True, user['email']

    try:
        if user['email_notifications_enabled']:
            return True, user['email']
    except (IndexError, KeyError):
        pass

    return False, user['email']


# ── Notifications pre-construites ──

def notifier_nouvelle_demande_recup(demande_user, responsable_email, responsable_prenom,
                                     date_debut, date_fin, nb_jours, nb_heures):
    """Notifie le responsable d'une nouvelle demande de recuperation."""
    _e = html_module.escape
    contenu = f"""
    <h3 style="color:#667eea;margin:0 0 12px;font-size:16px;">Nouvelle demande de recuperation</h3>
    <p><strong>{_e(demande_user)}</strong> a depose une demande de recuperation.</p>
    <table style="width:100%;border-collapse:collapse;margin:12px 0;">
        <tr><td style="padding:8px 12px;background:#f3f4f6;border-radius:4px;font-weight:600;width:40%;">Periode</td>
            <td style="padding:8px 12px;">{_e(date_debut)} au {_e(date_fin)}</td></tr>
        <tr><td style="padding:8px 12px;background:#f3f4f6;border-radius:4px;font-weight:600;">Duree</td>
            <td style="padding:8px 12px;">{nb_jours} jour(s) - {nb_heures:.2f}h</td></tr>
    </table>
    <p style="margin-top:16px;">Connectez-vous a CS-PILOT pour valider ou refuser cette demande.</p>
    """
    return envoyer_email(responsable_email, "Nouvelle demande de recuperation", contenu, responsable_prenom)


def notifier_demande_recup_validee_responsable(direction_email, direction_prenom,
                                                demande_user, responsable_nom,
                                                date_debut, date_fin, nb_jours):
    """Notifie la direction qu'une demande a ete validee par le responsable."""
    _e = html_module.escape
    contenu = f"""
    <h3 style="color:#667eea;margin:0 0 12px;font-size:16px;">Demande de recuperation a valider</h3>
    <p>La demande de <strong>{_e(demande_user)}</strong> a ete validee par <strong>{_e(responsable_nom)}</strong>
       et est maintenant en attente de votre validation.</p>
    <table style="width:100%;border-collapse:collapse;margin:12px 0;">
        <tr><td style="padding:8px 12px;background:#f3f4f6;border-radius:4px;font-weight:600;width:40%;">Salarie</td>
            <td style="padding:8px 12px;">{_e(demande_user)}</td></tr>
        <tr><td style="padding:8px 12px;background:#f3f4f6;border-radius:4px;font-weight:600;">Periode</td>
            <td style="padding:8px 12px;">{_e(date_debut)} au {_e(date_fin)}</td></tr>
        <tr><td style="padding:8px 12px;background:#f3f4f6;border-radius:4px;font-weight:600;">Duree</td>
            <td style="padding:8px 12px;">{nb_jours} jour(s)</td></tr>
    </table>
    <p style="margin-top:16px;">Connectez-vous a CS-PILOT pour valider ou refuser cette demande.</p>
    """
    return envoyer_email(direction_email, "Demande de recuperation a valider", contenu, direction_prenom)


def notifier_demande_recup_decision(salarie_email, salarie_prenom, decision,
                                     date_debut, date_fin, nb_jours, motif_refus=''):
    """Notifie le salarie de la decision sur sa demande de recuperation."""
    _e = html_module.escape
    if decision == 'validee':
        statut_html = '<span style="color:#059669;font-weight:700;font-size:16px;">VALIDEE</span>'
        detail = "<p>Vos jours de recuperation ont ete ajoutes automatiquement a votre calendrier.</p>"
    else:
        statut_html = '<span style="color:#dc2626;font-weight:700;font-size:16px;">REFUSEE</span>'
        detail = f"<p><strong>Motif du refus :</strong> {_e(motif_refus)}</p>" if motif_refus else ""

    contenu = f"""
    <h3 style="color:#667eea;margin:0 0 12px;font-size:16px;">Decision sur votre demande de recuperation</h3>
    <p>Votre demande de recuperation du <strong>{_e(date_debut)}</strong> au <strong>{_e(date_fin)}</strong>
       ({nb_jours} jour(s)) a ete : {statut_html}</p>
    {detail}
    """
    sujet = f"Demande de recuperation {decision}"
    return envoyer_email(salarie_email, sujet, contenu, salarie_prenom)


def notifier_relance_validation(responsable_email, responsable_prenom,
                                 mois_nom, annee, nb_fiches, expediteur_nom):
    """Envoie une relance au responsable pour les fiches d'heures non validees."""
    _e = html_module.escape
    contenu = f"""
    <h3 style="color:#667eea;margin:0 0 12px;font-size:16px;">Relance - Validation des fiches d'heures</h3>
    <p><strong>{_e(expediteur_nom)}</strong> vous rappelle que des fiches d'heures sont
       en attente de votre validation pour le mois de <strong>{_e(mois_nom)} {annee}</strong>.</p>
    <div style="background:#fef3c7;border-left:4px solid #f59e0b;padding:12px 16px;border-radius:4px;margin:16px 0;">
        <strong>{nb_fiches} fiche(s)</strong> en attente de validation responsable.
    </div>
    <p>Connectez-vous a CS-PILOT pour proceder a la validation.</p>
    """
    return envoyer_email(responsable_email, f"Relance validation - {_e(mois_nom)} {annee}", contenu, responsable_prenom)
