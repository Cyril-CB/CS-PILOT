"""
Blueprint factures_bp - Gestion des factures avec pre-traitement IA.

Fonctionnalites :
- Import de factures (PDF) avec extraction IA des informations
- Renommage automatique au format AAAA-MM-JJ_FACTURE_Fournisseur_NumeroFacture
- Tableau avec badges statut, assignation aux secteurs ou direction
- Detail de facture avec historique et commentaires
- Circuit de validation (approbation par responsable/direction)
Acces comptable/directeur pour gestion, responsable pour approbation de son secteur.
"""
import os
import re
import json
import unicodedata
from datetime import datetime
from flask import (Blueprint, render_template, request, session, flash,
                   redirect, url_for, jsonify, send_file)
from database import get_db, DATA_DIR
from utils import login_required, get_setting
from blueprints.pesee_alisfa import call_ai, _extract_json_from_response
from blueprints.api_keys import get_available_models
from email_service import is_email_configured, envoyer_email

factures_bp = Blueprint('factures_bp', __name__)

PROFILS_GESTION = ['directeur', 'comptable']
PROFILS_CONSULTATION = ['directeur', 'comptable', 'responsable']

FACTURES_DIR = os.path.join(DATA_DIR, 'factures')


def _ensure_factures_dir():
    os.makedirs(FACTURES_DIR, exist_ok=True)
    return FACTURES_DIR


def _sanitize_filename(text):
    """Nettoie un texte pour l'utiliser dans un nom de fichier."""
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
    text = re.sub(r'[^a-zA-Z0-9_-]', '-', text)
    text = re.sub(r'-+', '-', text).strip('-')
    return text


def _add_historique(conn, facture_id, action, details=None, user_id=None):
    """Ajoute une entrée dans l'historique de la facture."""
    if user_id is None:
        user_id = session.get('user_id')
    conn.execute(
        'INSERT INTO facture_historique (facture_id, action, details, user_id) VALUES (?, ?, ?, ?)',
        (facture_id, action, details, user_id)
    )


EXTRACT_SYSTEM_PROMPT = """Tu es un assistant comptable expert en extraction d'informations de factures.
Tu analyses des factures au format PDF et tu extrais les informations suivantes.

Tu DOIS répondre STRICTEMENT au format JSON suivant :
{
  "fournisseur": "Nom du fournisseur (tel qu'il apparait sur la facture)",
  "numero_facture": "Numéro de la facture",
  "date_facture": "AAAA-MM-JJ",
  "date_echeance": "AAAA-MM-JJ ou null si non précisée",
  "montant_ttc": 1234.56,
  "description": "Description courte du contenu de la facture (type de dépense, produits/services)"
}

Règles :
- Le montant TTC est le montant total TTC de la facture. Si la TVA n'est pas mentionnée, prends le montant total.
- La date doit être au format AAAA-MM-JJ.
- Si une information n'est pas trouvée, mets null.
- Le numéro de facture est l'identifiant donné par le fournisseur.
- La description doit être concise (1-2 phrases max).
"""


@factures_bp.route('/factures')
@login_required
def liste_factures():
    if session.get('profil') not in PROFILS_GESTION:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    factures = conn.execute('''
        SELECT f.*, fr.nom as fournisseur_nom, s.nom as secteur_nom
        FROM factures f
        LEFT JOIN fournisseurs fr ON f.fournisseur_id = fr.id
        LEFT JOIN secteurs s ON f.secteur_id = s.id
        ORDER BY f.created_at DESC
    ''').fetchall()
    secteurs = conn.execute('SELECT id, nom FROM secteurs ORDER BY nom').fetchall()
    conn.close()

    models = get_available_models()
    has_key = len(models) > 0

    return render_template('factures.html', factures=factures, secteurs=secteurs,
                           available_models=models, has_api_key=has_key)


@factures_bp.route('/factures/importer', methods=['POST'])
@login_required
def importer_facture():
    if session.get('profil') not in PROFILS_GESTION:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    fichiers = request.files.getlist('fichiers')
    model = request.form.get('model', '')

    if not fichiers or all(f.filename == '' for f in fichiers):
        flash('Veuillez sélectionner au moins un fichier.', 'error')
        return redirect(url_for('factures_bp.liste_factures'))

    _ensure_factures_dir()
    nb_ok = 0
    nb_err = 0

    for fichier in fichiers:
        if fichier.filename == '':
            continue

        ext = os.path.splitext(fichier.filename)[1].lower()
        if ext != '.pdf':
            flash(f'Fichier ignoré (non PDF) : {fichier.filename}', 'warning')
            nb_err += 1
            continue

        try:
            # Sauvegarder temporairement pour extraction
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
                fichier.save(tmp.name)
                tmp_path = tmp.name

            # Extraire le texte du PDF
            import pdfplumber
            texte = ""
            with pdfplumber.open(tmp_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        texte += page_text + "\n"

            # Appeler l'IA pour extraire les informations
            info = _extract_invoice_info(texte, model)

            # Trouver ou créer le fournisseur
            fournisseur_id = _match_or_create_fournisseur(info.get('fournisseur'))

            # Générer le nom de fichier normalisé
            date_facture = info.get('date_facture') or datetime.now().strftime('%Y-%m-%d')
            nom_fournisseur = _sanitize_filename(info.get('fournisseur') or 'Inconnu')
            num_facture = _sanitize_filename(info.get('numero_facture') or 'SANS-NUM')
            nouveau_nom = f"{date_facture}_FACTURE_{nom_fournisseur}_{num_facture}.pdf"

            # Gérer les doublons de nom
            dest_path = os.path.join(FACTURES_DIR, nouveau_nom)
            counter = 1
            while os.path.exists(dest_path):
                base = f"{date_facture}_FACTURE_{nom_fournisseur}_{num_facture}_{counter}.pdf"
                dest_path = os.path.join(FACTURES_DIR, base)
                nouveau_nom = base
                counter += 1

            # Déplacer le fichier
            import shutil
            shutil.move(tmp_path, dest_path)

            # Enregistrer en BDD
            conn = get_db()
            cursor = conn.execute(
                '''INSERT INTO factures (fournisseur_id, numero_facture, date_facture, date_echeance,
                   montant_ttc, description, fichier_path, fichier_nom, fichier_original, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (fournisseur_id, info.get('numero_facture'), date_facture,
                 info.get('date_echeance'), info.get('montant_ttc'),
                 info.get('description'), dest_path, nouveau_nom,
                 fichier.filename, session['user_id'])
            )
            facture_id = cursor.lastrowid

            user_nom = f"{session.get('prenom', '')} {session.get('nom', '')}"
            _add_historique(conn, facture_id, 'Création',
                           f'Facture importée par {user_nom} (fichier: {fichier.filename})')
            conn.commit()
            conn.close()
            nb_ok += 1

        except Exception as e:
            nb_err += 1
            flash(f'Erreur sur {fichier.filename}: {str(e)}', 'error')
            # Nettoyer le fichier temporaire
            try:
                if 'tmp_path' in locals() and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass

    if nb_ok:
        flash(f'{nb_ok} facture(s) importée(s) avec succès.', 'success')
    if nb_err and not nb_ok:
        flash('Aucune facture importée.', 'error')

    return redirect(url_for('factures_bp.liste_factures'))


def _extract_invoice_info(texte, model):
    """Utilise l'IA pour extraire les informations d'une facture."""
    if not model:
        # Pas de modèle sélectionné, retourner des valeurs vides
        return {}

    messages = [
        {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": f"Voici le contenu texte d'une facture à analyser :\n\n{texte}"}
    ]

    try:
        raw = call_ai(messages, model)
        return _extract_json_from_response(raw)
    except Exception:
        return {}


def _match_or_create_fournisseur(nom_fournisseur):
    """Cherche un fournisseur par nom/alias ou le crée."""
    if not nom_fournisseur:
        return None

    conn = get_db()
    # Chercher par nom exact ou alias
    row = conn.execute('''
        SELECT id FROM fournisseurs
        WHERE LOWER(nom) = LOWER(?) OR LOWER(alias1) = LOWER(?) OR LOWER(alias2) = LOWER(?)
    ''', (nom_fournisseur, nom_fournisseur, nom_fournisseur)).fetchone()

    if row:
        conn.close()
        return row['id']

    # Créer un nouveau fournisseur
    cursor = conn.execute('INSERT INTO fournisseurs (nom) VALUES (?)', (nom_fournisseur,))
    fournisseur_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return fournisseur_id


@factures_bp.route('/factures/<int:facture_id>/assigner', methods=['POST'])
@login_required
def assigner_facture(facture_id):
    if session.get('profil') not in PROFILS_GESTION:
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json() if request.is_json else None
    if data:
        secteur_id = data.get('secteur_id')
        direction = data.get('direction', False)
    else:
        secteur_id = request.form.get('secteur_id')
        direction = request.form.get('direction') == '1'

    conn = get_db()
    if direction:
        conn.execute(
            'UPDATE factures SET assigned_direction=1, secteur_id=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?',
            (facture_id,)
        )
        _add_historique(conn, facture_id, 'Assignation', 'Assignée à la direction')
    elif secteur_id:
        secteur = conn.execute('SELECT nom FROM secteurs WHERE id=?', (secteur_id,)).fetchone()
        conn.execute(
            'UPDATE factures SET secteur_id=?, assigned_direction=0, updated_at=CURRENT_TIMESTAMP WHERE id=?',
            (secteur_id, facture_id)
        )
        _add_historique(conn, facture_id, 'Assignation',
                        f'Assignée au secteur {secteur["nom"] if secteur else secteur_id}')

    conn.commit()
    conn.close()

    if request.is_json:
        return jsonify({'success': True})

    flash('Facture assignée.', 'success')
    return redirect(url_for('factures_bp.liste_factures'))


@factures_bp.route('/factures/<int:facture_id>/detail')
@login_required
def detail_facture(facture_id):
    if session.get('profil') not in PROFILS_CONSULTATION:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    facture = conn.execute('''
        SELECT f.*, fr.nom as fournisseur_nom, s.nom as secteur_nom
        FROM factures f
        LEFT JOIN fournisseurs fr ON f.fournisseur_id = fr.id
        LEFT JOIN secteurs s ON f.secteur_id = s.id
        WHERE f.id = ?
    ''', (facture_id,)).fetchone()

    if not facture:
        conn.close()
        flash('Facture introuvable.', 'error')
        return redirect(url_for('factures_bp.liste_factures'))

    # Responsable : vérifier que la facture est de son secteur
    if session.get('profil') == 'responsable':
        user = conn.execute('SELECT secteur_id FROM users WHERE id=?', (session['user_id'],)).fetchone()
        if not user or user['secteur_id'] != facture['secteur_id']:
            conn.close()
            flash('Accès non autorisé à cette facture.', 'error')
            return redirect(url_for('factures_bp.approbation_factures'))

    historique = conn.execute('''
        SELECT h.*, u.prenom, u.nom as user_nom
        FROM facture_historique h
        LEFT JOIN users u ON h.user_id = u.id
        WHERE h.facture_id = ?
        ORDER BY h.created_at DESC
    ''', (facture_id,)).fetchall()

    commentaires = conn.execute('''
        SELECT c.*, u.prenom, u.nom as user_nom, u.profil
        FROM facture_commentaires c
        LEFT JOIN users u ON c.user_id = u.id
        WHERE c.facture_id = ?
        ORDER BY c.created_at ASC
    ''', (facture_id,)).fetchall()

    secteurs = conn.execute('SELECT id, nom FROM secteurs ORDER BY nom').fetchall()
    conn.close()

    return render_template('facture_detail.html', facture=facture, historique=historique,
                           commentaires=commentaires, secteurs=secteurs)


@factures_bp.route('/factures/<int:facture_id>/commenter', methods=['POST'])
@login_required
def commenter_facture(facture_id):
    if session.get('profil') not in PROFILS_CONSULTATION:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    commentaire = request.form.get('commentaire', '').strip()
    if not commentaire:
        flash('Le commentaire ne peut pas être vide.', 'error')
        return redirect(url_for('factures_bp.detail_facture', facture_id=facture_id))

    conn = get_db()
    conn.execute(
        'INSERT INTO facture_commentaires (facture_id, user_id, commentaire) VALUES (?, ?, ?)',
        (facture_id, session['user_id'], commentaire)
    )
    user_nom = f"{session.get('prenom', '')} {session.get('nom', '')}"
    _add_historique(conn, facture_id, 'Commentaire', f'Commentaire ajouté par {user_nom}')
    conn.commit()
    conn.close()

    flash('Commentaire ajouté.', 'success')
    return redirect(url_for('factures_bp.detail_facture', facture_id=facture_id))


@factures_bp.route('/factures/<int:facture_id>/telecharger')
@login_required
def telecharger_facture(facture_id):
    if session.get('profil') not in PROFILS_CONSULTATION:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    facture = conn.execute('SELECT fichier_path, fichier_nom, secteur_id FROM factures WHERE id=?', (facture_id,)).fetchone()

    if not facture or not facture['fichier_path'] or not os.path.exists(facture['fichier_path']):
        conn.close()
        flash('Fichier introuvable.', 'error')
        return redirect(url_for('factures_bp.liste_factures'))

    # Responsable : vérifier que la facture est de son secteur
    if session.get('profil') == 'responsable':
        user = conn.execute('SELECT secteur_id FROM users WHERE id=?', (session['user_id'],)).fetchone()
        if not user or user['secteur_id'] != facture['secteur_id']:
            conn.close()
            flash('Accès non autorisé à cette facture.', 'error')
            return redirect(url_for('factures_bp.approbation_factures'))

    conn.close()
    return send_file(facture['fichier_path'], as_attachment=True, download_name=facture['fichier_nom'])


@factures_bp.route('/factures/<int:facture_id>/supprimer', methods=['POST'])
@login_required
def supprimer_facture(facture_id):
    if session.get('profil') not in PROFILS_GESTION:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    facture = conn.execute('SELECT fichier_path FROM factures WHERE id=?', (facture_id,)).fetchone()
    if facture and facture['fichier_path'] and os.path.exists(facture['fichier_path']):
        os.unlink(facture['fichier_path'])

    conn.execute('DELETE FROM facture_historique WHERE facture_id=?', (facture_id,))
    conn.execute('DELETE FROM facture_commentaires WHERE facture_id=?', (facture_id,))
    conn.execute('DELETE FROM ecritures_comptables WHERE facture_id=?', (facture_id,))
    conn.execute('DELETE FROM factures WHERE id=?', (facture_id,))
    conn.commit()
    conn.close()

    flash('Facture supprimée.', 'success')
    return redirect(url_for('factures_bp.liste_factures'))


@factures_bp.route('/factures/<int:facture_id>/approuver', methods=['POST'])
@login_required
def approuver_facture(facture_id):
    """Approuve une facture (responsable de secteur ou direction)."""
    profil = session.get('profil')
    if profil not in PROFILS_CONSULTATION:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    facture = conn.execute('SELECT * FROM factures WHERE id=?', (facture_id,)).fetchone()
    if not facture:
        conn.close()
        flash('Facture introuvable.', 'error')
        return redirect(url_for('factures_bp.approbation_factures'))

    # Vérifier les droits : responsable pour son secteur, directeur pour tout
    if profil == 'responsable':
        user = conn.execute('SELECT secteur_id FROM users WHERE id=?', (session['user_id'],)).fetchone()
        if not user or user['secteur_id'] != facture['secteur_id']:
            conn.close()
            flash('Vous ne pouvez approuver que les factures de votre secteur.', 'error')
            return redirect(url_for('factures_bp.approbation_factures'))

    conn.execute(
        '''UPDATE factures SET approbation='approuvee', approuve_par=?, date_approbation=CURRENT_TIMESTAMP,
           updated_at=CURRENT_TIMESTAMP WHERE id=?''',
        (session['user_id'], facture_id)
    )
    user_nom = f"{session.get('prenom', '')} {session.get('nom', '')}"
    _add_historique(conn, facture_id, 'Approbation', f'Approuvée par {user_nom}')
    conn.commit()
    conn.close()

    flash('Facture approuvée.', 'success')
    return redirect(url_for('factures_bp.approbation_factures'))


@factures_bp.route('/factures/approbation')
@login_required
def approbation_factures():
    """Page d'approbation des factures pour responsables et direction."""
    profil = session.get('profil')
    if profil not in PROFILS_CONSULTATION:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()

    if profil == 'responsable':
        user = conn.execute('SELECT secteur_id FROM users WHERE id=?', (session['user_id'],)).fetchone()
        if user and user['secteur_id']:
            factures = conn.execute('''
                SELECT f.*, fr.nom as fournisseur_nom, s.nom as secteur_nom
                FROM factures f
                LEFT JOIN fournisseurs fr ON f.fournisseur_id = fr.id
                LEFT JOIN secteurs s ON f.secteur_id = s.id
                WHERE f.secteur_id = ? AND f.approbation = 'en_attente'
                ORDER BY f.created_at DESC
            ''', (user['secteur_id'],)).fetchall()
        else:
            factures = []
    else:
        # Directeur/comptable voient tout ce qui est en attente
        factures = conn.execute('''
            SELECT f.*, fr.nom as fournisseur_nom, s.nom as secteur_nom
            FROM factures f
            LEFT JOIN fournisseurs fr ON f.fournisseur_id = fr.id
            LEFT JOIN secteurs s ON f.secteur_id = s.id
            WHERE f.approbation = 'en_attente'
               AND (f.secteur_id IS NOT NULL OR f.assigned_direction = 1)
            ORDER BY f.created_at DESC
        ''').fetchall()

    conn.close()
    return render_template('approbation_factures.html', factures=factures)


@factures_bp.route('/factures/relancer', methods=['POST'])
@login_required
def relancer_secteurs():
    """Envoie un email de relance aux responsables/direction ayant des factures en attente."""
    if session.get('profil') not in PROFILS_GESTION:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('factures_bp.liste_factures'))

    if not is_email_configured():
        flash('Les notifications email ne sont pas configurées.', 'error')
        return redirect(url_for('factures_bp.liste_factures'))

    conn = get_db()

    # Factures en attente assignées à un secteur
    factures_secteurs = conn.execute('''
        SELECT f.secteur_id, s.nom as secteur_nom, COUNT(*) as nb
        FROM factures f
        JOIN secteurs s ON f.secteur_id = s.id
        WHERE f.approbation = 'en_attente' AND f.secteur_id IS NOT NULL
        GROUP BY f.secteur_id
    ''').fetchall()

    # Factures en attente assignées à la direction
    nb_direction = conn.execute('''
        SELECT COUNT(*) as nb FROM factures
        WHERE approbation = 'en_attente' AND assigned_direction = 1
    ''').fetchone()['nb']

    nb_envoyes = 0
    nb_erreurs = 0

    # Relancer les responsables de chaque secteur
    for row in factures_secteurs:
        responsables = conn.execute('''
            SELECT prenom, email FROM users
            WHERE secteur_id = ? AND profil = 'responsable' AND email IS NOT NULL AND email != ''
        ''', (row['secteur_id'],)).fetchall()

        nb = row['nb']
        sujet = f"Factures en attente de validation"
        contenu = f"""
            <p>Vous avez <strong>{nb} facture{'s' if nb > 1 else ''}</strong>
            en attente de validation pour le secteur <strong>{row['secteur_nom']}</strong>.</p>
            <p>Merci de vous connecter à CS-PILOT pour les consulter et les approuver.</p>
        """

        for resp in responsables:
            ok, _ = envoyer_email(resp['email'], sujet, contenu, resp['prenom'])
            if ok:
                nb_envoyes += 1
            else:
                nb_erreurs += 1

    # Relancer la direction si factures assignées
    if nb_direction > 0:
        directeurs = conn.execute('''
            SELECT prenom, email FROM users
            WHERE profil = 'directeur' AND email IS NOT NULL AND email != ''
        ''').fetchall()

        sujet = f"Factures en attente de validation"
        contenu = f"""
            <p>Vous avez <strong>{nb_direction} facture{'s' if nb_direction > 1 else ''}</strong>
            assignée{'s' if nb_direction > 1 else ''} à la direction en attente de validation.</p>
            <p>Merci de vous connecter à CS-PILOT pour les consulter et les approuver.</p>
        """

        for d in directeurs:
            ok, _ = envoyer_email(d['email'], sujet, contenu, d['prenom'])
            if ok:
                nb_envoyes += 1
            else:
                nb_erreurs += 1

    conn.close()

    if nb_envoyes:
        flash(f'{nb_envoyes} relance{"s" if nb_envoyes > 1 else ""} envoyée{"s" if nb_envoyes > 1 else ""} avec succès.', 'success')
    elif nb_erreurs:
        flash('Erreur lors de l\'envoi des relances.', 'error')
    else:
        flash('Aucune facture en attente de validation à relancer.', 'info')

    return redirect(url_for('factures_bp.liste_factures'))
