"""
Commandes de fournitures pour les salariés.
"""
import re
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from database import get_db
from sessions_securite import verifier_action
from sites_acces import (entier_id, est_administrateur, fournitures_globales,
                         peut_creer_fourniture, peut_traiter_fourniture, sites_fournitures)
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
    """Compatibilité historique : ce droit ne couvre que les lignes sans site."""
    conn = get_db()
    try:
        return fournitures_globales(conn, session.get('user_id'))
    finally:
        conn.close()


def _has_multiple_or_mixed_decimal_separators(value):
    return value.count(',') > 1 or value.count('.') > 1 or (',' in value and '.' in value)


def _parse_prix(raw_value):
    value = (raw_value or '').strip().replace(' ', '')
    if not value:
        return None

    if _has_multiple_or_mixed_decimal_separators(value):
        raise ValueError

    normalized = value.replace(',', '.')
    if not re.fullmatch(r'\d+(?:\.\d{1,2})?', normalized):
        raise ValueError

    return float(normalized)


def _format_prix(value):
    if value is None:
        return '—'
    formatted = f"{value:,.2f}"
    formatted = formatted.replace(',', '\u202f').replace('.', ',')
    return f"{formatted} €"


def _parse_quantite(raw_value):
    """Quantité demandée : entier >= 1. Vide -> 1. Invalide -> ValueError."""
    value = (raw_value or '').strip()
    if not value:
        return 1
    if not re.fullmatch(r'\d+', value):
        raise ValueError
    quantite = int(value)
    if quantite < 1 or quantite > 9999:
        raise ValueError
    return quantite


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
        try:
            prix = _parse_prix(request.form.get('prix'))
        except ValueError:
            flash("Le prix saisi est invalide.", "error")
            return redirect(url_for('commandes_salaries_bp.commandes_salaries'))
        try:
            quantite = _parse_quantite(request.form.get('quantite'))
        except ValueError:
            flash("La quantité saisie est invalide (entier positif attendu).", "error")
            return redirect(url_for('commandes_salaries_bp.commandes_salaries'))

        if not description:
            flash("La description de la demande est obligatoire.", "error")
            return redirect(url_for('commandes_salaries_bp.commandes_salaries'))
        if urgence not in URGENCES_MAP:
            flash("Le niveau d'urgence sélectionné est invalide.", "error")
            return redirect(url_for('commandes_salaries_bp.commandes_salaries'))

        conn = get_db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            refus = verifier_action(conn)
            if refus is not None:
                return refus
            try:
                site_id = entier_id(request.form['site_id']) if request.form.get('site_id') else None
            except ValueError:
                abort(400)
            if not peut_creer_fourniture(conn, session['user_id'], site_id):
                abort(403)
            conn.execute(
                '''
                INSERT INTO commandes_salaries (
                    user_id, date_demande, description, reference, quantite, prix, urgence, groupe, site_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'en_cours', ?)
                ''',
                (
                    session['user_id'],
                    date.today().isoformat(),
                    description,
                    reference or None,
                    quantite,
                    prix,
                    urgence,
                    site_id,
                )
            )
            conn.commit()
        finally:
            conn.close()

        flash("Votre demande de fournitures a bien été enregistrée.", "success")
        return redirect(url_for('commandes_salaries_bp.commandes_salaries', site_id=site_id), code=303)

    conn = get_db()
    try:
        uid = session['user_id']
        sites = sites_fournitures(conn, uid)
        sites_configures = bool(conn.execute('SELECT 1 FROM sites LIMIT 1').fetchone())
        filtre = request.args.get('site_id', '')
        filtre_sql, filtre_params = '', []
        if filtre == 'global':
            filtre_sql = 'AND c.site_id IS NULL'
        elif filtre:
            try:
                filtre_id = entier_id(filtre)
            except ValueError:
                abort(400)
            historique_admin = est_administrateur(conn, uid) and conn.execute(
                'SELECT 1 FROM sites WHERE id = ?', (filtre_id,)).fetchone()
            if filtre_id not in {s['id'] for s in sites} and not historique_admin and not conn.execute(
                    'SELECT 1 FROM commandes_salaries WHERE user_id = ? AND site_id = ?', (uid, filtre_id)).fetchone():
                abort(403)
            filtre_sql, filtre_params = 'AND c.site_id = ?', [filtre_id]
        commandes = conn.execute(f'''
            SELECT c.*, u.nom, u.prenom, s.nom AS site_nom
            FROM commandes_salaries c JOIN users u ON u.id = c.user_id
            LEFT JOIN sites s ON s.id = c.site_id
            WHERE (c.user_id = ? OR ? = 1 OR (c.site_id IS NULL AND ? = 1)
                OR (s.actif = 1 AND EXISTS (SELECT 1 FROM sites_responsables_modules r
                    WHERE r.site_id = c.site_id AND r.module = 'fournitures' AND r.user_id = ?)))
                {filtre_sql}
            ORDER BY c.date_demande DESC, c.id DESC
        ''', [uid, int(est_administrateur(conn, uid)), int(fournitures_globales(conn, uid)), uid, *filtre_params]).fetchall()
        commandes_data = []
        for commande in commandes:
            item = dict(commande)
            item['demandeur'] = f"{commande['prenom']} {commande['nom']}"
            item['prix_affiche'] = _format_prix(commande['prix'])
            item['peut_traiter'] = peut_traiter_fourniture(conn, uid, commande['site_id'])
            commandes_data.append(item)
        peut_suivre = any(c['peut_traiter'] for c in commandes_data) or fournitures_globales(conn, uid)
        # Les onglets incluent l'historique personnel d'un site archivé.
        sites_visibles = {s['id']: s['nom'] for s in sites}
        sites_visibles.update({c['site_id']: c['site_nom'] for c in commandes_data if c['site_id']})
    finally:
        conn.close()

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
        peut_suivre=peut_suivre,
        nombre_colonnes_table=10 if peut_suivre else 8,
        sites=sites, sites_visibles=sites_visibles, filtre=filtre,
        sites_configures=sites_configures,
        titre_site=sites_visibles.get(int(filtre)) if filtre.isascii() and filtre.isdigit() else None,
        site_selectionne=int(filtre) if filtre.isascii() and filtre.isdigit() else (sites[0]['id'] if len(sites) == 1 else None),
    )


@commandes_salaries_bp.route('/commandes-salaries/<int:commande_id>/statut', methods=['POST'])
@login_required
def modifier_statut_commande(commande_id):
    groupe = request.form.get('groupe', 'en_cours')
    if groupe not in GROUPES_MAP:
        flash("Statut invalide.", "error")
        return redirect(url_for('commandes_salaries_bp.commandes_salaries'))

    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        refus = verifier_action(conn)
        if refus is not None:
            return refus
        commande = conn.execute('SELECT * FROM commandes_salaries WHERE id = ?', (commande_id,)).fetchone()
        if not commande or not peut_traiter_fourniture(conn, session['user_id'], commande['site_id']):
            abort(403)
        attendu = request.form.get('groupe_actuel')
        if attendu and attendu != commande['groupe'] and groupe != commande['groupe']:
            flash('Cette demande a changé. Rechargez la page.', 'error')
            return redirect(url_for('commandes_salaries_bp.commandes_salaries'), code=303)
        if groupe == commande['groupe']:
            return redirect(url_for('commandes_salaries_bp.commandes_salaries'), code=303)
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
