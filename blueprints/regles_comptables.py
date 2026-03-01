"""
Blueprint regles_comptables_bp - Gestion des regles comptables pour l'IA.

Les regles definissent comment l'IA genere les ecritures comptables :
- Basees sur un type de depense ou sur un fournisseur
- Compte de charge, code(s) analytique(s), modele de libelle
Acces : directeur, comptable.
"""
from flask import Blueprint, render_template, request, session, flash, redirect, url_for
from database import get_db
from utils import login_required

regles_comptables_bp = Blueprint('regles_comptables_bp', __name__)

PROFILS_AUTORISES = ['directeur', 'comptable']


@regles_comptables_bp.route('/regles-comptables')
@login_required
def liste_regles():
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    regles_rows = conn.execute('SELECT * FROM regles_comptables ORDER BY nom').fetchall()
    fournisseurs = conn.execute('SELECT id, nom FROM fournisseurs ORDER BY nom').fetchall()
    conn.close()

    # Convertir les Row en dicts pour que tojson fonctionne dans le template
    regles = [dict(r) for r in regles_rows]

    return render_template('regles_comptables.html', regles=regles, fournisseurs=fournisseurs)


@regles_comptables_bp.route('/regles-comptables/ajouter', methods=['POST'])
@login_required
def ajouter_regle():
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    nom = request.form.get('nom', '').strip()
    type_regle = request.form.get('type_regle', '').strip()
    cible = request.form.get('cible', '').strip()
    compte_comptable = request.form.get('compte_comptable', '').strip()
    code_analytique_1 = request.form.get('code_analytique_1', '').strip() or None
    code_analytique_2 = request.form.get('code_analytique_2', '').strip() or None
    pct1 = request.form.get('pourcentage_analytique_1', '100')
    pct2 = request.form.get('pourcentage_analytique_2', '0')
    modele_libelle = request.form.get('modele_libelle', '').strip() or '{supplier} {invoice_number} {date} {period}'
    statut = request.form.get('statut', 'active')

    if not nom or not type_regle or not cible or not compte_comptable:
        flash('Tous les champs obligatoires doivent être remplis.', 'error')
        return redirect(url_for('regles_comptables_bp.liste_regles'))

    try:
        pct1 = float(pct1)
        pct2 = float(pct2)
    except ValueError:
        pct1, pct2 = 100.0, 0.0

    # Si un seul analytique, 100% sur le premier
    if not code_analytique_2:
        pct1, pct2 = 100.0, 0.0

    conn = get_db()
    conn.execute(
        '''INSERT INTO regles_comptables
           (nom, type_regle, cible, compte_comptable, code_analytique_1, code_analytique_2,
            pourcentage_analytique_1, pourcentage_analytique_2, modele_libelle, statut)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (nom, type_regle, cible, compte_comptable, code_analytique_1, code_analytique_2,
         pct1, pct2, modele_libelle, statut)
    )
    conn.commit()
    conn.close()

    flash(f'Règle "{nom}" ajoutée avec succès.', 'success')
    return redirect(url_for('regles_comptables_bp.liste_regles'))


@regles_comptables_bp.route('/regles-comptables/<int:regle_id>/modifier', methods=['POST'])
@login_required
def modifier_regle(regle_id):
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    nom = request.form.get('nom', '').strip()
    type_regle = request.form.get('type_regle', '').strip()
    cible = request.form.get('cible', '').strip()
    compte_comptable = request.form.get('compte_comptable', '').strip()
    code_analytique_1 = request.form.get('code_analytique_1', '').strip() or None
    code_analytique_2 = request.form.get('code_analytique_2', '').strip() or None
    pct1 = request.form.get('pourcentage_analytique_1', '100')
    pct2 = request.form.get('pourcentage_analytique_2', '0')
    modele_libelle = request.form.get('modele_libelle', '').strip() or '{supplier} {invoice_number} {date} {period}'
    statut = request.form.get('statut', 'active')

    if not nom or not type_regle or not cible or not compte_comptable:
        flash('Tous les champs obligatoires doivent être remplis.', 'error')
        return redirect(url_for('regles_comptables_bp.liste_regles'))

    try:
        pct1 = float(pct1)
        pct2 = float(pct2)
    except ValueError:
        pct1, pct2 = 100.0, 0.0

    if not code_analytique_2:
        pct1, pct2 = 100.0, 0.0

    conn = get_db()
    conn.execute(
        '''UPDATE regles_comptables SET nom=?, type_regle=?, cible=?, compte_comptable=?,
           code_analytique_1=?, code_analytique_2=?, pourcentage_analytique_1=?,
           pourcentage_analytique_2=?, modele_libelle=?, statut=?, updated_at=CURRENT_TIMESTAMP
           WHERE id=?''',
        (nom, type_regle, cible, compte_comptable, code_analytique_1, code_analytique_2,
         pct1, pct2, modele_libelle, statut, regle_id)
    )
    conn.commit()
    conn.close()

    flash(f'Règle "{nom}" modifiée avec succès.', 'success')
    return redirect(url_for('regles_comptables_bp.liste_regles'))


@regles_comptables_bp.route('/regles-comptables/<int:regle_id>/supprimer', methods=['POST'])
@login_required
def supprimer_regle(regle_id):
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    conn.execute('DELETE FROM regles_comptables WHERE id = ?', (regle_id,))
    conn.commit()
    conn.close()

    flash('Règle supprimée.', 'success')
    return redirect(url_for('regles_comptables_bp.liste_regles'))
