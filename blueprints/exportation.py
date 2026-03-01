"""
Blueprint exportation_bp - Export des ecritures comptables validees.

Genere un fichier .txt tabule au format :
Journal | Date JJMMAAAA | Compte/Code auxiliaire | Libelle MAJUSCULES |
N° facture | Debit | Credit | Compte analytique | Echeance JJMMAAAA

Acces : directeur, comptable.
"""
import io
from datetime import datetime
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, Response
from database import get_db
from utils import login_required

exportation_bp = Blueprint('exportation_bp', __name__)

PROFILS_AUTORISES = ['directeur', 'comptable']


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
    conn.close()

    return render_template('exportation.html', ecritures=ecritures)


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
        # Journal : AC (Achats)
        journal = 'AC'

        # Date : JJMMAAAA
        date_comptable = ''
        if e['date_ecriture']:
            try:
                dt = datetime.strptime(e['date_ecriture'], '%Y-%m-%d')
                date_comptable = dt.strftime('%d%m%Y')
            except ValueError:
                date_comptable = e['date_ecriture']

        # Compte général ou code auxiliaire
        compte = e['compte'] or ''

        # Libellé en majuscules
        libelle = (e['libelle'] or '').upper()

        # N° facture
        numero = e['numero_facture'] or ''

        # Débit / Crédit
        debit = f"{e['debit']:.2f}" if e['debit'] else ''
        credit = f"{e['credit']:.2f}" if e['credit'] else ''

        # Compte analytique (uniquement pour les comptes de charges)
        analytique = e['code_analytique'] or ''

        # Échéance JJMMAAAA
        echeance = e['echeance'] or ''

        # Écrire la ligne tabulée
        line = '\t'.join([journal, date_comptable, compte, libelle, numero,
                          debit, credit, analytique, echeance])
        output.write(line + '\n')

    # Marquer les écritures comme exportées
    conn.execute(
        f"UPDATE ecritures_comptables SET statut='exportee', updated_at=CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
        ids
    )
    conn.commit()
    conn.close()

    # Retourner le fichier
    content = output.getvalue()
    output.close()

    filename = f"export_ecritures_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    return Response(
        content,
        mimetype='text/plain',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )
