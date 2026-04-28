"""
Commandes de fournitures pour les salariés.
"""
from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from database import get_db
from delegations import MISSION_SUIVI_COMMANDES_FOURNITURES, user_has_delegation
from utils import login_required

commandes_salaries_bp = Blueprint('commandes_salaries_bp', __name__)

GROUPES = [
    {'key': 'en_cours', 'label': 'Demandes en cours', 'color': '#fdab3d'},
    {'key': 'commandee', 'label': 'Commandées', 'color': '#00c875'},
    {'key': 'annulee', 'label': 'Annulées', 'color': '#c4c4c4'},
]

GROUPES_MAP = {g['key']: g for g in GROUPES}

URGENCES = [
    {'key': 'peut_attendre', 'label': 'Peut attendre', 'color': '#c4c4c4'},
    {'key': 'normal', 'label': 'Normal', 'color': '#579bfc'},
    {'key': 'urgent', 'label': 'Urgent', 'color': '#e2445c'},
]

URGENCES_MAP = {u['key']: u for u in URGENCES}

PROFILS_AUTORISES = {'directeur', 'comptable', 'responsable', 'salarie'}


def _peut_acceder():
    return session.get('profil') in PROFILS_AUTORISES


def _peut_suivre_globalement():
    profil = session.get('profil')
    if profil in ('directeur', 'comptable'):
        return True
    return user_has_delegation(
        session.get('user_id'),
        MISSION_SUIVI_COMMANDES_FOURNITURES
    )


def _parse_prix(raw_value):
    value = (raw_value or '').strip().replace(' ', '').replace(',', '.')
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _format_prix(value):
    if value is None:
        return '—'
    return f"{value:,.2f}".replace(',', ' ').replace('.', ',') + ' €'


@commandes_salaries_bp.route('/commandes-salaries', methods=['GET', 'POST'])
@login_required
def commandes_salaries():
    if not _peut_acceder():
        flash("Accès non autorisé.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))

    if request.method == 'POST':
        description = (request.form.get('description') or '').strip()
        reference = (request.form.get('reference') or '').strip()
        urgence = request.form.get('urgence', 'normal')
        prix = _parse_prix(request.form.get('prix'))
        prix_raw = (request.form.get('prix') or '').strip()

        if not description:
            flash("La description de la demande est obligatoire.", "error")
            return redirect(url_for('commandes_salaries_bp.commandes_salaries'))
        if urgence not in URGENCES_MAP:
            flash("Le niveau d'urgence sélectionné est invalide.", "error")
            return redirect(url_for('commandes_salaries_bp.commandes_salaries'))
        if prix_raw and prix is None:
            flash("Le prix saisi est invalide.", "error")
            return redirect(url_for('commandes_salaries_bp.commandes_salaries'))

        conn = get_db()
        try:
            conn.execute(
                '''
                INSERT INTO commandes_salaries (
                    user_id, date_demande, description, reference, prix, urgence, groupe
                ) VALUES (?, ?, ?, ?, ?, ?, 'en_cours')
                ''',
                (
                    session['user_id'],
                    date.today().isoformat(),
                    description,
                    reference or None,
                    prix,
                    urgence,
                )
            )
            conn.commit()
        finally:
            conn.close()

        flash("Votre demande de fournitures a bien été enregistrée.", "success")
        return redirect(url_for('commandes_salaries_bp.commandes_salaries'))

    conn = get_db()
    try:
        if _peut_suivre_globalement():
            commandes = conn.execute(
                '''
                SELECT c.*, u.nom, u.prenom
                FROM commandes_salaries c
                JOIN users u ON u.id = c.user_id
                ORDER BY c.date_demande DESC, c.id DESC
                '''
            ).fetchall()
        else:
            commandes = conn.execute(
                '''
                SELECT c.*, u.nom, u.prenom
                FROM commandes_salaries c
                JOIN users u ON u.id = c.user_id
                WHERE c.user_id = ?
                ORDER BY c.date_demande DESC, c.id DESC
                ''',
                (session['user_id'],)
            ).fetchall()
    finally:
        conn.close()

    commandes_data = []
    for commande in commandes:
        commande_dict = dict(commande)
        commande_dict['demandeur'] = f"{commande['prenom']} {commande['nom']}"
        commande_dict['prix_affiche'] = _format_prix(commande['prix'])
        commandes_data.append(commande_dict)

    groupes = []
    for groupe in GROUPES:
        lignes = [commande for commande in commandes_data if commande['groupe'] == groupe['key']]
        groupes.append({
            'key': groupe['key'],
            'label': groupe['label'],
            'color': groupe['color'],
            'lignes': lignes,
        })

    return render_template(
        'commandes_salaries.html',
        groupes=groupes,
        groupes_config=GROUPES,
        urgences_config=URGENCES,
        aujourd_hui=date.today().isoformat(),
        peut_suivre=_peut_suivre_globalement(),
    )


@commandes_salaries_bp.route('/commandes-salaries/<int:commande_id>/statut', methods=['POST'])
@login_required
def modifier_statut_commande(commande_id):
    if not _peut_suivre_globalement():
        flash("Accès non autorisé.", "error")
        return redirect(url_for('commandes_salaries_bp.commandes_salaries'))

    groupe = request.form.get('groupe', 'en_cours')
    if groupe not in GROUPES_MAP:
        flash("Statut invalide.", "error")
        return redirect(url_for('commandes_salaries_bp.commandes_salaries'))

    conn = get_db()
    try:
        conn.execute(
            '''
            UPDATE commandes_salaries
            SET groupe = ?, traite_par = ?, date_traitement = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (groupe, session['user_id'], commande_id)
        )
        conn.commit()
    finally:
        conn.close()

    flash("Le statut de la demande a été mis à jour.", "success")
    return redirect(url_for('commandes_salaries_bp.commandes_salaries'))
