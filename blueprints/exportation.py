"""Export comptable : archive immuable, fichier exact et statuts atomiques."""
import hashlib
import json
import os
import sqlite3
import tempfile
from uuid import uuid4

from flask import (Blueprint, Response, current_app, flash, redirect,
                   render_template, request, session, url_for, send_file)
from database import get_db, DATA_DIR
from stockage_restaure import resoudre_fichier
from utils import login_required
from sessions_securite import verifier_action
from exports_comptables import (COLONNES_TXT, ExportRefuse, canonique, evenement,
                                identifiants, reference, selection_export, source_facture, presenter_evenements)

exportation_bp = Blueprint('exportation_bp', __name__)
PROFILS_AUTORISES = ['directeur', 'comptable']
ARCHIVES_DIR = os.path.join(DATA_DIR, 'exports')


def _autoriser(conn=None):
    if conn is not None:
        refus = verifier_action(conn)
        if refus is not None:
            return refus
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    return None


def _produire_fichier(lignes):
    """Vrai fichier temporaire fermé AVANT le commit ; aucun fichier orphelin.

    Les octets deviennent ensuite l'archive SQL, aussi durable que son lot.
    Le téléchargement ne reconstruit rien et ne dépend pas d'une copie disque.
    """
    os.makedirs(ARCHIVES_DIR, exist_ok=True)
    attendu = ''.join('\t'.join(l['colonnes']) + '\n' for l in lignes).encode('utf-8')
    with tempfile.TemporaryFile(mode='w+b', dir=ARCHIVES_DIR) as fichier:
        fichier.write(attendu)
        fichier.flush()
        fichier.seek(0)
        contenu = fichier.read()
        if contenu != attendu:
            raise OSError('Export incomplet')
    return contenu


def _reponse_fichier(archive):
    contenu = bytes(archive['contenu'])
    if hashlib.sha256(contenu).hexdigest() != archive['empreinte']:
        raise ExportRefuse('Le fichier conservé est illisible ou endommagé. Contactez la direction.')
    return Response(contenu, mimetype='text/plain', headers={
        'Content-Disposition': f'attachment; filename="{archive["nom_fichier"]}"'})


@exportation_bp.route('/exportation')
@login_required
def liste_exportation():
    refus = _autoriser()
    if refus is not None:
        return refus
    conn = get_db()
    try:
        conn.execute('BEGIN')
        rows = conn.execute('''SELECT e.* FROM ecritures_comptables e
            JOIN factures f ON f.id=e.facture_id
            WHERE e.statut='validee' AND f.archivee=0 ORDER BY e.date_ecriture, e.id''').fetchall()
        sources = {}
        ecritures = []
        for row in rows:
            fid = row['facture_id']
            if fid not in sources:
                sources[fid] = source_facture(conn, fid)
            ecritures.append({**dict(row), 'reference': reference(row, sources[fid])})
        # Ne pas charger les fichiers binaires pour afficher la liste.
        archives = conn.execute('''SELECT a.id, a.nom_fichier, a.nb_ecritures,
            a.created_at, a.preuve_version, a.total_debit_centimes, a.total_credit_centimes,
            a.auteur_nom, u.prenom, u.nom AS user_nom
            FROM archives_export a LEFT JOIN users u ON u.id=a.created_by
            ORDER BY a.id DESC''').fetchall()
    finally:
        conn.close()
    return render_template('exportation.html', ecritures=ecritures, archives=archives)


@exportation_bp.route('/exportation/exporter', methods=['POST'])
@login_required
def exporter():
    refus = _autoriser()
    if refus is not None:
        return refus
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        refus = _autoriser(conn)
        if refus is not None:
            return refus
        ids = identifiants(request.form.getlist('ecriture_ids'))
        lignes, debit, credit = selection_export(conn, ids, request.form)
        contenu = _produire_fichier(lignes)
        nom = f'export_ecritures_{uuid4().hex}.txt'
        auteur = f"{session.get('prenom', '')} {session.get('nom', '')}".strip()
        archive_id = conn.execute('''INSERT INTO archives_export
            (nom_fichier, fichier_path, nb_ecritures, created_by, preuve_version,
             contenu, empreinte, format, total_debit_centimes, total_credit_centimes, auteur_nom)
            VALUES (?, '', ?, ?, 1, ?, ?, 'aiga-txt-v1', ?, ?, ?)''',
            (nom, len(lignes), session['user_id'], contenu, hashlib.sha256(contenu).hexdigest(),
             debit, credit, auteur)).lastrowid
        factures = set()
        for position, ligne in enumerate(lignes, 1):
            e = ligne['ecriture']
            conn.execute('''INSERT INTO export_lignes
                (archive_id, ecriture_id, facture_id, revision, position, contenu)
                VALUES (?, ?, ?, ?, ?, ?)''',
                (archive_id, e['id'], e['facture_id'], e['revision'], position, canonique(ligne)))
            conn.execute("UPDATE ecritures_comptables SET statut='exportee', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (e['id'],))
            factures.add(e['facture_id'])
        evenement(conn, 'export', {'fichier': nom, 'lignes': len(lignes)}, archive_id=archive_id)
        from blueprints.factures import _add_historique
        for fid in factures:
            _add_historique(conn, fid, 'Export comptable', f'Lot #{archive_id} — {nom}')
        archive = conn.execute('SELECT * FROM archives_export WHERE id=?', (archive_id,)).fetchone()
        response = _reponse_fichier(archive)
        conn.commit()
        return response
    except ExportRefuse as exc:
        conn.rollback()
        flash(str(exc), 'warning')
    except (OSError, sqlite3.Error):
        conn.rollback()
        current_app.logger.warning('Échec de création de l’export comptable ; transaction annulée.')
        flash('Export non réalisé. Aucun nouveau lot n’a été enregistré. Vérifiez le stockage puis réessayez.', 'error')
    finally:
        conn.close()
    return redirect(url_for('exportation_bp.liste_exportation'))


@exportation_bp.route('/exportation/archives/<int:archive_id>')
@login_required
def detail_archive(archive_id):
    refus = _autoriser()
    if refus is not None:
        return refus
    conn = get_db()
    try:
        conn.execute('BEGIN')
        archive = conn.execute('SELECT * FROM archives_export WHERE id=?', (archive_id,)).fetchone()
        if not archive:
            flash('Archive introuvable.', 'error')
            return redirect(url_for('exportation_bp.liste_exportation'))
        lignes = [json.loads(r['contenu']) for r in conn.execute(
            'SELECT contenu FROM export_lignes WHERE archive_id=? ORDER BY position', (archive_id,))]
        historique = conn.execute('SELECT * FROM comptabilite_evenements WHERE archive_id=? ORDER BY id',
                                  (archive_id,)).fetchall()
    finally:
        conn.close()
    return render_template('export_archive.html', archive=archive, lignes=lignes,
                           colonnes=COLONNES_TXT, historique=presenter_evenements(historique))


@exportation_bp.route('/exportation/archives/<int:archive_id>/telecharger', methods=['GET', 'POST'])
@login_required
def telecharger_archive(archive_id):
    refus = _autoriser()
    if refus is not None:
        return refus
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE' if request.method == 'POST' else 'BEGIN')
        refus = _autoriser(conn)
        if refus is not None:
            return refus
        archive = conn.execute('SELECT * FROM archives_export WHERE id=?', (archive_id,)).fetchone()
        if not archive:
            raise ExportRefuse('Archive introuvable.')
        if archive['preuve_version'] == 0:
            # Fichier historique référencé par 0023 ; aucun rapprochement inventé.
            chemin = resoudre_fichier(archive['fichier_path'], 'exports')
            if not chemin or not os.path.isfile(chemin):
                raise ExportRefuse('Fichier historique introuvable. Son contenu ne peut pas être reconstitué.')
            response = send_file(chemin, as_attachment=True, download_name=archive['nom_fichier'])
            # Le GET historique reste compatible ; l'action est un téléchargement.
            conn.rollback()
            conn.execute('BEGIN IMMEDIATE')
            refus = _autoriser(conn)
            if refus is not None:
                return refus
        elif request.method == 'GET':
            return redirect(url_for('exportation_bp.detail_archive', archive_id=archive_id))
        else:
            if request.form.get('confirmer') != '1':
                raise ExportRefuse('Confirmez le téléchargement du fichier déjà exporté.')
            response = _reponse_fichier(archive)
        evenement(conn, 'retelechargement', {'fichier': archive['nom_fichier'],
                  'historique': archive['preuve_version'] == 0}, archive_id=archive_id)
        conn.commit()
        return response
    except (ExportRefuse, OSError) as exc:
        conn.rollback()
        flash(str(exc) if isinstance(exc, ExportRefuse) else 'Fichier indisponible.', 'error')
    except sqlite3.Error:
        conn.rollback()
        flash('Téléchargement non réalisé : impossible de conserver sa trace. Réessayez.', 'error')
    finally:
        conn.close()
    return redirect(url_for('exportation_bp.liste_exportation'))


@exportation_bp.route('/exportation/archives/<int:archive_id>/supprimer', methods=['POST'])
@login_required
def supprimer_archive(archive_id):
    refus = _autoriser()
    if refus is not None:
        return refus
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        refus = _autoriser(conn)
        if refus is not None:
            return refus
        if conn.execute('SELECT 1 FROM archives_export WHERE id=?', (archive_id,)).fetchone():
            evenement(conn, 'suppression_archive_refusee', {}, archive_id=archive_id)
            conn.commit()
        flash('Les archives comptables sont conservées pour garantir la traçabilité des exports.', 'warning')
    finally:
        conn.close()
    return redirect(url_for('exportation_bp.liste_exportation'))
