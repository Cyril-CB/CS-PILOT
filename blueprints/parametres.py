"""
Blueprint parametres_bp.
Page de parametres personnels accessible a tous les salaries.
Permet de modifier son email et de gerer le consentement aux notifications.
"""
from flask import Blueprint, render_template, request, session, flash, redirect, url_for
from database import get_db
from utils import login_required

parametres_bp = Blueprint('parametres_bp', __name__)


def _has_notif_column(conn):
    """Verifie si la colonne email_notifications_enabled existe."""
    cols = [row['column_name'] for row in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='users' AND table_schema='public'"
    ).fetchall()]
    return 'email_notifications_enabled' in cols


PROFILS_AUTORISES = ('salarie', 'prestataire')


@parametres_bp.route('/parametres', methods=['GET', 'POST'])
@login_required
def parametres():
    """Page de parametres personnels du salarie."""
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Cette page est reservee aux salaries', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    has_notif = _has_notif_column(conn)

    if request.method == 'POST':
        email = request.form.get('email', '').strip() or None
        notif_enabled = 1 if request.form.get('email_notifications_enabled') else 0

        if has_notif:
            conn.execute(
                'UPDATE users SET email = %s, email_notifications_enabled = %s WHERE id = %s',
                (email, notif_enabled, session['user_id'])
            )
        else:
            conn.execute(
                'UPDATE users SET email = %s WHERE id = %s',
                (email, session['user_id'])
            )
        conn.commit()
        conn.close()

        flash('Parametres enregistres avec succes', 'success')
        return redirect(url_for('parametres_bp.parametres'))

    if has_notif:
        user = conn.execute(
            'SELECT email, email_notifications_enabled FROM users WHERE id = %s',
            (session['user_id'],)
        ).fetchone()
    else:
        row = conn.execute(
            'SELECT email FROM users WHERE id = %s',
            (session['user_id'],)
        ).fetchone()
        user = {'email': row['email'] if row else None, 'email_notifications_enabled': 0}
    conn.close()

    return render_template('parametres.html', user=user)
