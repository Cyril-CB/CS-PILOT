"""
Blueprint fournisseurs_bp - Gestion des fournisseurs pour le module factures.

Repertoire des fournisseurs avec aliases (pour l'IA) et code comptable.
Acces : directeur, comptable.
"""
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from database import get_db
from utils import login_required, aujourd_hui

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


@fournisseurs_bp.route('/fournisseurs/<int:fournisseur_id>')
@login_required
def detail_fournisseur(fournisseur_id):
    """Fiche fournisseur : informations, total des factures et liste des
    factures de l'année sélectionnée (année courante par défaut, jusqu'à N-3)."""
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    try:
        fournisseur = conn.execute(
            'SELECT * FROM fournisseurs WHERE id = ?', (fournisseur_id,)
        ).fetchone()
        if not fournisseur:
            flash('Fournisseur introuvable.', 'error')
            return redirect(url_for('fournisseurs_bp.liste_fournisseurs'))

        # Filtre par année : de N-3 à l'année courante (par défaut).
        annee_courante = aujourd_hui().year
        annees = [str(annee_courante - delta) for delta in range(0, 4)]  # N … N-3
        # On borne l'année au menu affiché : une année hors plage passée en URL
        # (ex. ?annee=2020) retombe sur l'année courante, pour que le filtre
        # affiché et les données interrogées restent cohérents.
        annee_param = (request.args.get('annee') or '').strip()
        annee_selected = annee_param if annee_param in annees else str(annee_courante)

        factures = conn.execute('''
            SELECT f.id, f.numero_facture, f.date_facture, f.montant_ttc,
                   f.fichier_path, f.secteur_id, f.assigned_direction,
                   s.nom AS secteur_nom
            FROM factures f
            LEFT JOIN secteurs s ON f.secteur_id = s.id
            WHERE f.fournisseur_id = ?
              AND substr(f.date_facture, 1, 4) = ?
            ORDER BY f.date_facture DESC, f.id DESC
        ''', (fournisseur_id, annee_selected)).fetchall()

        total_ttc = sum((f['montant_ttc'] or 0) for f in factures)
    finally:
        conn.close()

    return render_template(
        'fournisseur_detail.html',
        fournisseur=fournisseur,
        factures=factures,
        total_ttc=total_ttc,
        annees=annees,
        annee_selected=annee_selected,
    )


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
        'INSERT INTO fournisseurs (nom, alias1, alias2, code_comptable, email_contact) VALUES (?, ?, ?, ?, ?)',
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
        'UPDATE fournisseurs SET nom=?, alias1=?, alias2=?, code_comptable=?, email_contact=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
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
    nb = conn.execute('SELECT COUNT(*) as nb FROM factures WHERE fournisseur_id = ?', (fournisseur_id,)).fetchone()['nb']
    if nb > 0:
        conn.close()
        flash(f'Impossible de supprimer : {nb} facture(s) liée(s) à ce fournisseur.', 'error')
        return redirect(url_for('fournisseurs_bp.liste_fournisseurs'))

    conn.execute('DELETE FROM fournisseurs WHERE id = ?', (fournisseur_id,))
    conn.commit()
    conn.close()

    flash('Fournisseur supprimé.', 'success')
    return redirect(url_for('fournisseurs_bp.liste_fournisseurs'))
