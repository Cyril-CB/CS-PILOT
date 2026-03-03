"""
Blueprint fournisseurs_bp - Gestion des fournisseurs pour le module factures.

Repertoire des fournisseurs avec aliases (pour l'IA) et code comptable.
Acces : directeur, comptable.
"""
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from database import get_db
from utils import login_required

fournisseurs_bp = Blueprint('fournisseurs_bp', __name__)

PROFILS_AUTORISES = ['directeur', 'comptable']


@fournisseurs_bp.route('/fournisseurs')
@login_required
def liste_fournisseurs():
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    fournisseurs = conn.execute('''
        SELECT f.*,
               (SELECT COUNT(*) FROM factures WHERE fournisseur_id = f.id) as nb_factures
        FROM fournisseurs f
        ORDER BY f.nom
    ''').fetchall()
    conn.close()

    return render_template('fournisseurs.html', fournisseurs=fournisseurs)


@fournisseurs_bp.route('/fournisseurs/ajouter', methods=['POST'])
@login_required
def ajouter_fournisseur():
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    nom = request.form.get('nom', '').strip()
    alias1 = request.form.get('alias1', '').strip() or None
    alias2 = request.form.get('alias2', '').strip() or None
    code_comptable = request.form.get('code_comptable', '').strip().upper() or None
    email_contact = request.form.get('email_contact', '').strip() or None

    if not nom:
        flash('Le nom du fournisseur est obligatoire.', 'error')
        return redirect(url_for('fournisseurs_bp.liste_fournisseurs'))

    # Valider que le code comptable ne contient que des lettres majuscules
    if code_comptable:
        import re
        if not re.match(r'^[A-Z]+$', code_comptable):
            flash('Le code comptable doit contenir uniquement des lettres majuscules.', 'error')
            return redirect(url_for('fournisseurs_bp.liste_fournisseurs'))

    conn = get_db()
    conn.execute(
        'INSERT INTO fournisseurs (nom, alias1, alias2, code_comptable, email_contact) VALUES (%s, %s, %s, %s, %s)',
        (nom, alias1, alias2, code_comptable, email_contact)
    )
    conn.commit()
    conn.close()

    flash(f'Fournisseur "{nom}" ajouté avec succès.', 'success')
    return redirect(url_for('fournisseurs_bp.liste_fournisseurs'))


@fournisseurs_bp.route('/fournisseurs/<int:fournisseur_id>/modifier', methods=['POST'])
@login_required
def modifier_fournisseur(fournisseur_id):
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    nom = request.form.get('nom', '').strip()
    alias1 = request.form.get('alias1', '').strip() or None
    alias2 = request.form.get('alias2', '').strip() or None
    code_comptable = request.form.get('code_comptable', '').strip().upper() or None
    email_contact = request.form.get('email_contact', '').strip() or None

    if not nom:
        flash('Le nom du fournisseur est obligatoire.', 'error')
        return redirect(url_for('fournisseurs_bp.liste_fournisseurs'))

    if code_comptable:
        import re
        if not re.match(r'^[A-Z]+$', code_comptable):
            flash('Le code comptable doit contenir uniquement des lettres majuscules.', 'error')
            return redirect(url_for('fournisseurs_bp.liste_fournisseurs'))

    conn = get_db()
    conn.execute(
        'UPDATE fournisseurs SET nom=%s, alias1=%s, alias2=%s, code_comptable=%s, email_contact=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s',
        (nom, alias1, alias2, code_comptable, email_contact, fournisseur_id)
    )
    conn.commit()
    conn.close()

    flash(f'Fournisseur "{nom}" modifié avec succès.', 'success')
    return redirect(url_for('fournisseurs_bp.liste_fournisseurs'))


@fournisseurs_bp.route('/fournisseurs/<int:fournisseur_id>/supprimer', methods=['POST'])
@login_required
def supprimer_fournisseur(fournisseur_id):
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    # Vérifier qu'il n'y a pas de factures liées
    nb = conn.execute('SELECT COUNT(*) as nb FROM factures WHERE fournisseur_id = %s', (fournisseur_id,)).fetchone()['nb']
    if nb > 0:
        conn.close()
        flash(f'Impossible de supprimer : {nb} facture(s) liée(s) à ce fournisseur.', 'error')
        return redirect(url_for('fournisseurs_bp.liste_fournisseurs'))

    conn.execute('DELETE FROM fournisseurs WHERE id = %s', (fournisseur_id,))
    conn.commit()
    conn.close()

    flash('Fournisseur supprimé.', 'success')
    return redirect(url_for('fournisseurs_bp.liste_fournisseurs'))
