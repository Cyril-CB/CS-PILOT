"""
Blueprint exportation_bp - Export des ecritures comptables validees.

Genere un fichier .txt tabule au format :
Journal | Date JJMMAAAA | Compte/Code auxiliaire | Libelle MAJUSCULES |
N° facture | Debit | Credit | Compte analytique | Echeance JJMMAAAA

Archive chaque export pour telechargement ulterieur.
Acces : directeur, comptable.
"""
import os
import io
from datetime import datetime
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, Response, send_file
from database import get_db
from utils import login_required

exportation_bp = Blueprint('exportation_bp', __name__)

PROFILS_AUTORISES = ['directeur', 'comptable']

ARCHIVES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'exports')


def _ensure_archives_dir():
    os.makedirs(ARCHIVES_DIR, exist_ok=True)
    return ARCHIVES_DIR


@exportation_bp.route('/exportation')
@login_required
def liste_exportation():
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    ecritures = conn.execute('''
        SELECT e.*, f.fournisseur_id, fr.nom as fournisseur_nom
        FROM ecritures_comptables e
        LEFT JOIN factures f ON e.facture_id = f.id
        LEFT JOIN fournisseurs fr ON f.fournisseur_id = fr.id
        WHERE e.statut = 'validee'
        ORDER BY e.date_ecriture, e.id
    ''').fetchall()

    archives = conn.execute('''
        SELECT a.*, u.prenom, u.nom as user_nom
        FROM archives_export a
        LEFT JOIN users u ON a.created_by = u.id
        ORDER BY a.created_at DESC
    ''').fetchall()

    conn.close()

    return render_template('exportation.html', ecritures=ecritures, archives=archives)


@exportation_bp.route('/exportation/exporter', methods=['POST'])
@login_required
def exporter():
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    ids = request.form.getlist('ecriture_ids')
    if not ids:
        flash('Aucune écriture sélectionnée.', 'warning')
        return redirect(url_for('exportation_bp.liste_exportation'))

    conn = get_db()
    placeholders = ','.join('?' * len(ids))
    ecritures = conn.execute(f'''
        SELECT e.*, f.fournisseur_id, fr.nom as fournisseur_nom
        FROM ecritures_comptables e
        LEFT JOIN factures f ON e.facture_id = f.id
        LEFT JOIN fournisseurs fr ON f.fournisseur_id = fr.id
        WHERE e.id IN ({placeholders})
        ORDER BY e.date_ecriture, e.id
    ''', ids).fetchall()

    # Générer le fichier tabulé
    output = io.StringIO()
    for e in ecritures:
        journal = 'AC'

        date_comptable = ''
        if e['date_ecriture']:
            try:
                dt = datetime.strptime(e['date_ecriture'], '%Y-%m-%d')
                date_comptable = dt.strftime('%d%m%Y')
            except ValueError:
                date_comptable = e['date_ecriture']

        compte = e['compte'] or ''
        libelle = (e['libelle'] or '').upper()
        numero = e['numero_facture'] or ''
        debit = f"{e['debit']:.2f}" if e['debit'] else ''
        credit = f"{e['credit']:.2f}" if e['credit'] else ''
        analytique = e['code_analytique'] or ''
        echeance = e['echeance'] or ''

        line = '\t'.join([journal, date_comptable, compte, libelle, numero,
                          debit, credit, analytique, echeance])
        output.write(line + '\n')

    # Marquer les écritures comme exportées
    conn.execute(
        f"UPDATE ecritures_comptables SET statut='exportee', updated_at=CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
        ids
    )

    # Archiver le fichier sur disque
    content = output.getvalue()
    output.close()

    filename = f"export_ecritures_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    _ensure_archives_dir()
    filepath = os.path.join(ARCHIVES_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    # Enregistrer l'archive en BDD
    conn.execute(
        'INSERT INTO archives_export (nom_fichier, fichier_path, nb_ecritures, created_by) VALUES (?, ?, ?, ?)',
        (filename, filepath, len(ecritures), session.get('user_id'))
    )
    conn.commit()
    conn.close()

    return Response(
        content,
        mimetype='text/plain',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@exportation_bp.route('/exportation/archives/<int:archive_id>/telecharger')
@login_required
def telecharger_archive(archive_id):
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    archive = conn.execute('SELECT * FROM archives_export WHERE id=?', (archive_id,)).fetchone()
    conn.close()

    if not archive or not os.path.exists(archive['fichier_path']):
        flash('Archive introuvable.', 'error')
        return redirect(url_for('exportation_bp.liste_exportation'))

    return send_file(archive['fichier_path'], as_attachment=True, download_name=archive['nom_fichier'])


@exportation_bp.route('/exportation/archives/<int:archive_id>/supprimer', methods=['POST'])
@login_required
def supprimer_archive(archive_id):
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    archive = conn.execute('SELECT * FROM archives_export WHERE id=?', (archive_id,)).fetchone()
    if archive and archive['fichier_path'] and os.path.exists(archive['fichier_path']):
        os.unlink(archive['fichier_path'])
    conn.execute('DELETE FROM archives_export WHERE id=?', (archive_id,))
    conn.commit()
    conn.close()

    flash('Archive supprimée.', 'success')
    return redirect(url_for('exportation_bp.liste_exportation'))
