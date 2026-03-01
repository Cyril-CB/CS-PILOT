"""
Blueprint infos_salaries_bp.
Fiche de renseignement salarie : email, contrats, documents
(carte d'identite, carte vitale, diplome, fiche de renseignement, etc.).
"""
import os
import re
import unicodedata
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, send_file)
from database import get_db
from utils import login_required

infos_salaries_bp = Blueprint('infos_salaries_bp', __name__)

DOCUMENTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'documents'
)

TYPES_CONTRAT = ['CDI', 'CDD', 'CEE', 'Autre']

TYPES_DOCUMENT = [
    ('FICHE-RENSEIGNEMENT', 'Fiche de renseignement'),
    ('CARTE-ID-RECTO', "Carte d'identite (recto)"),
    ('CARTE-ID-VERSO', "Carte d'identite (verso)"),
    ('CARTE-VITALE', 'Carte vitale'),
    ('DIPLOME', 'Diplome'),
    ('AUTRE-1', 'Autre document 1'),
    ('AUTRE-2', 'Autre document 2'),
]

EXTENSIONS_PDF = {'.pdf'}
EXTENSIONS_IMAGE = {'.jpg', '.jpeg', '.png', '.gif', '.bmp'}
EXTENSIONS_TOUTES = EXTENSIONS_PDF | EXTENSIONS_IMAGE


def _get_documents_dir():
    if not os.path.exists(DOCUMENTS_DIR):
        os.makedirs(DOCUMENTS_DIR, exist_ok=True)
    return DOCUMENTS_DIR


def _peut_gerer():
    return session.get('profil') in ['comptable', 'directeur']


def _nettoyer_nom(texte):
    """Retire les accents et les caracteres speciaux d'un texte pour les noms de fichiers."""
    # Retirer les accents
    nfkd = unicodedata.normalize('NFKD', texte)
    sans_accents = ''.join(c for c in nfkd if not unicodedata.combining(c))
    # Ne garder que les caracteres alphanumeriques, tirets et underscores
    return re.sub(r'[^a-zA-Z0-9_-]', '', sans_accents)


def _construire_nom_document(type_doc, nom, prenom, ext):
    """Construit le nom de fichier : TYPE-DOCUMENT_Nom_Prenom.ext"""
    nom_clean = _nettoyer_nom(nom)
    prenom_clean = _nettoyer_nom(prenom)
    return f"{type_doc}_{nom_clean}_{prenom_clean}{ext}"


def _construire_nom_contrat(date_debut, nom, prenom, type_contrat, ext):
    """Construit le nom de fichier : JJ-MM-AAAA_CONTRAT_Nom_Prenom_Type.ext"""
    # date_debut est au format YYYY-MM-DD, on le convertit en JJ-MM-AAAA
    parts = date_debut.split('-')
    date_fmt = f"{parts[2]}-{parts[1]}-{parts[0]}"
    nom_clean = _nettoyer_nom(nom)
    prenom_clean = _nettoyer_nom(prenom)
    type_clean = _nettoyer_nom(type_contrat)
    return f"{date_fmt}_CONTRAT_{nom_clean}_{prenom_clean}_{type_clean}{ext}"


def _sauvegarder_fichier(fichier, nom_fichier):
    """Sauvegarde un fichier uploade dans le dossier documents. Gere les doublons."""
    docs_dir = _get_documents_dir()
    base, ext = os.path.splitext(nom_fichier)
    chemin = os.path.join(docs_dir, nom_fichier)

    compteur = 1
    while os.path.exists(chemin):
        nom_fichier = f"{base}_{compteur}{ext}"
        chemin = os.path.join(docs_dir, nom_fichier)
        compteur += 1

    fichier.save(chemin)
    return nom_fichier


def _supprimer_fichier(fichier_path):
    """Supprime un fichier du dossier documents."""
    if fichier_path:
        chemin = os.path.join(_get_documents_dir(), fichier_path)
        if os.path.exists(chemin):
            os.remove(chemin)


def _extensions_acceptees(type_doc):
    """Retourne les extensions acceptees selon le type de document."""
    if type_doc == 'FICHE-RENSEIGNEMENT' or type_doc == 'DIPLOME':
        return EXTENSIONS_PDF
    if type_doc in ('CARTE-ID-RECTO', 'CARTE-ID-VERSO', 'CARTE-VITALE'):
        return EXTENSIONS_TOUTES
    if type_doc in ('AUTRE-1', 'AUTRE-2'):
        return EXTENSIONS_PDF
    return EXTENSIONS_TOUTES


@infos_salaries_bp.route('/infos_salaries')
@login_required
def infos_salaries():
    """Page principale : selection d'un salarie et affichage de sa fiche."""
    if not _peut_gerer():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()

    salaries = conn.execute('''
        SELECT u.id, u.nom, u.prenom, u.profil, u.email,
               COALESCE(s.nom, '') AS secteur_nom
        FROM users u
        LEFT JOIN secteurs s ON u.secteur_id = s.id
        WHERE u.actif = 1 AND u.profil != 'prestataire'
        ORDER BY u.nom, u.prenom
    ''').fetchall()

    selected_id = request.args.get('user_id', type=int)
    salarie = None
    contrats = []
    documents = []

    if selected_id:
        salarie = conn.execute('''
            SELECT u.*, COALESCE(s.nom, '') AS secteur_nom
            FROM users u
            LEFT JOIN secteurs s ON u.secteur_id = s.id
            WHERE u.id = ?
        ''', (selected_id,)).fetchone()

        if salarie:
            contrats = conn.execute('''
                SELECT c.*, su.nom AS saisi_par_nom, su.prenom AS saisi_par_prenom
                FROM contrats c
                LEFT JOIN users su ON c.saisi_par = su.id
                WHERE c.user_id = ?
                ORDER BY c.date_debut DESC
            ''', (selected_id,)).fetchall()

            documents = conn.execute('''
                SELECT d.*, su.nom AS saisi_par_nom, su.prenom AS saisi_par_prenom
                FROM documents_salaries d
                LEFT JOIN users su ON d.saisi_par = su.id
                WHERE d.user_id = ?
                ORDER BY d.type_document
            ''', (selected_id,)).fetchall()

    conn.close()

    # Construire un dict des documents existants par type pour le template
    docs_par_type = {}
    for doc in documents:
        docs_par_type[doc['type_document']] = dict(doc)

    return render_template('infos_salaries.html',
                           salaries=salaries,
                           selected_id=selected_id,
                           salarie=salarie,
                           contrats=contrats,
                           documents=documents,
                           docs_par_type=docs_par_type,
                           types_contrat=TYPES_CONTRAT,
                           types_document=TYPES_DOCUMENT)


@infos_salaries_bp.route('/infos_salaries/email', methods=['POST'])
@login_required
def modifier_email():
    """Modifier l'email d'un salarie."""
    if not _peut_gerer():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    user_id = request.form.get('user_id', type=int)
    email = request.form.get('email', '').strip() or None

    if not user_id:
        flash("Salarie invalide.", 'error')
        return redirect(url_for('infos_salaries_bp.infos_salaries'))

    conn = get_db()
    conn.execute('UPDATE users SET email = ? WHERE id = ?', (email, user_id))
    conn.commit()
    conn.close()

    flash("Email mis a jour.", 'success')
    return redirect(url_for('infos_salaries_bp.infos_salaries', user_id=user_id))


@infos_salaries_bp.route('/infos_salaries/pesee', methods=['POST'])
@login_required
def modifier_pesee():
    """Modifier la pesee d'un salarie."""
    if not _peut_gerer():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    user_id = request.form.get('user_id', type=int)
    pesee_val = request.form.get('pesee', '').strip()
    pesee = int(pesee_val) if pesee_val else None

    if not user_id:
        flash("Salarie invalide.", 'error')
        return redirect(url_for('infos_salaries_bp.infos_salaries'))

    conn = get_db()
    conn.execute('UPDATE users SET pesee = ? WHERE id = ?', (pesee, user_id))
    conn.commit()
    conn.close()

    flash("Pesee mise a jour.", 'success')
    return redirect(url_for('infos_salaries_bp.infos_salaries', user_id=user_id))


@infos_salaries_bp.route('/infos_salaries/contrat', methods=['POST'])
@login_required
def ajouter_contrat():
    """Ajouter un contrat pour un salarie."""
    if not _peut_gerer():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    user_id = request.form.get('user_id', type=int)
    type_contrat = request.form.get('type_contrat', '').strip()
    date_debut = request.form.get('date_debut', '').strip()
    date_fin = request.form.get('date_fin', '').strip() or None
    forfait = request.form.get('forfait', '').strip() or None
    nbr_jours = request.form.get('nbr_jours', type=float) if request.form.get('nbr_jours', '').strip() else None

    if not user_id or not type_contrat or not date_debut:
        flash("Veuillez remplir les champs obligatoires du contrat.", 'error')
        return redirect(url_for('infos_salaries_bp.infos_salaries', user_id=user_id))

    if type_contrat not in TYPES_CONTRAT:
        flash("Type de contrat invalide.", 'error')
        return redirect(url_for('infos_salaries_bp.infos_salaries', user_id=user_id))

    conn = get_db()
    salarie = conn.execute('SELECT nom, prenom FROM users WHERE id = ?', (user_id,)).fetchone()
    if not salarie:
        flash("Salarie introuvable.", 'error')
        conn.close()
        return redirect(url_for('infos_salaries_bp.infos_salaries'))

    fichier_path = None
    fichier_nom = None
    fichier = request.files.get('fichier_contrat')

    if fichier and fichier.filename:
        ext = os.path.splitext(fichier.filename)[1].lower()
        if ext not in EXTENSIONS_PDF:
            flash("Le contrat doit etre un fichier PDF.", 'error')
            conn.close()
            return redirect(url_for('infos_salaries_bp.infos_salaries', user_id=user_id))

        nom_fichier = _construire_nom_contrat(
            date_debut, salarie['nom'], salarie['prenom'], type_contrat, ext
        )
        fichier_path = _sauvegarder_fichier(fichier, nom_fichier)
        fichier_nom = fichier.filename

    try:
        conn.execute('''
            INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin,
                                  fichier_path, fichier_nom, saisi_par, forfait, nbr_jours)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, type_contrat, date_debut, date_fin,
              fichier_path, fichier_nom, session['user_id'], forfait, nbr_jours))
        conn.commit()
        flash(f"Contrat {type_contrat} ajoute avec succes.", 'success')
    except Exception as e:
        flash(f"Erreur : {str(e)}", 'error')
    finally:
        conn.close()

    return redirect(url_for('infos_salaries_bp.infos_salaries', user_id=user_id))


@infos_salaries_bp.route('/infos_salaries/document', methods=['POST'])
@login_required
def ajouter_document():
    """Ajouter ou remplacer un document pour un salarie."""
    if not _peut_gerer():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    user_id = request.form.get('user_id', type=int)
    type_document = request.form.get('type_document', '').strip()
    description = request.form.get('description', '').strip() or None

    types_valides = [t[0] for t in TYPES_DOCUMENT]
    if not user_id or type_document not in types_valides:
        flash("Type de document invalide.", 'error')
        return redirect(url_for('infos_salaries_bp.infos_salaries', user_id=user_id))

    fichier = request.files.get('fichier_document')
    if not fichier or not fichier.filename:
        flash("Veuillez selectionner un fichier.", 'error')
        return redirect(url_for('infos_salaries_bp.infos_salaries', user_id=user_id))

    ext = os.path.splitext(fichier.filename)[1].lower()
    extensions_ok = _extensions_acceptees(type_document)
    if ext not in extensions_ok:
        formats = ', '.join(sorted(e.upper().replace('.', '') for e in extensions_ok))
        flash(f"Format non accepte pour ce type de document. Formats acceptes : {formats}.", 'error')
        return redirect(url_for('infos_salaries_bp.infos_salaries', user_id=user_id))

    conn = get_db()
    salarie = conn.execute('SELECT nom, prenom FROM users WHERE id = ?', (user_id,)).fetchone()
    if not salarie:
        flash("Salarie introuvable.", 'error')
        conn.close()
        return redirect(url_for('infos_salaries_bp.infos_salaries'))

    # Si un document du meme type existe deja, le remplacer
    existing = conn.execute(
        'SELECT id, fichier_path FROM documents_salaries WHERE user_id = ? AND type_document = ?',
        (user_id, type_document)
    ).fetchone()

    nom_fichier = _construire_nom_document(
        type_document, salarie['nom'], salarie['prenom'], ext
    )
    fichier_path = _sauvegarder_fichier(fichier, nom_fichier)

    try:
        if existing:
            # Supprimer l'ancien fichier
            _supprimer_fichier(existing['fichier_path'])
            conn.execute('''
                UPDATE documents_salaries
                SET fichier_path = ?, fichier_nom = ?, description = ?,
                    saisi_par = ?, created_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (fichier_path, fichier.filename, description,
                  session['user_id'], existing['id']))
        else:
            conn.execute('''
                INSERT INTO documents_salaries
                (user_id, type_document, description, fichier_path, fichier_nom, saisi_par)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, type_document, description, fichier_path,
                  fichier.filename, session['user_id']))
        conn.commit()
        label = dict(TYPES_DOCUMENT).get(type_document, type_document)
        flash(f"Document '{label}' enregistre.", 'success')
    except Exception as e:
        flash(f"Erreur : {str(e)}", 'error')
    finally:
        conn.close()

    return redirect(url_for('infos_salaries_bp.infos_salaries', user_id=user_id))


@infos_salaries_bp.route('/infos_salaries/telecharger_document/<int:doc_id>')
@login_required
def telecharger_document(doc_id):
    """Telecharger un document salarie."""
    if not _peut_gerer():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    doc = conn.execute(
        'SELECT fichier_path, fichier_nom, user_id FROM documents_salaries WHERE id = ?',
        (doc_id,)
    ).fetchone()
    conn.close()

    if not doc or not doc['fichier_path']:
        flash("Document introuvable.", 'error')
        return redirect(url_for('infos_salaries_bp.infos_salaries'))

    chemin = os.path.join(_get_documents_dir(), doc['fichier_path'])
    chemin_reel = os.path.realpath(chemin)
    dossier_reel = os.path.realpath(_get_documents_dir())
    if not chemin_reel.startswith(dossier_reel) or not os.path.exists(chemin):
        flash("Fichier introuvable sur le serveur.", 'error')
        return redirect(url_for('infos_salaries_bp.infos_salaries', user_id=doc['user_id']))

    return send_file(chemin, as_attachment=True,
                     download_name=doc['fichier_nom'] or doc['fichier_path'])


@infos_salaries_bp.route('/infos_salaries/supprimer_document/<int:doc_id>', methods=['POST'])
@login_required
def supprimer_document(doc_id):
    """Supprimer un document salarie."""
    if not _peut_gerer():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    doc = conn.execute('SELECT * FROM documents_salaries WHERE id = ?', (doc_id,)).fetchone()
    if not doc:
        flash("Document introuvable.", 'error')
        conn.close()
        return redirect(url_for('infos_salaries_bp.infos_salaries'))

    user_id = doc['user_id']
    _supprimer_fichier(doc['fichier_path'])
    conn.execute('DELETE FROM documents_salaries WHERE id = ?', (doc_id,))
    conn.commit()
    conn.close()

    flash("Document supprime.", 'success')
    return redirect(url_for('infos_salaries_bp.infos_salaries', user_id=user_id))


@infos_salaries_bp.route('/infos_salaries/telecharger_contrat/<int:contrat_id>')
@login_required
def telecharger_contrat(contrat_id):
    """Telecharger le PDF d'un contrat."""
    if not _peut_gerer() and session.get('profil') != 'prestataire':
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    contrat = conn.execute(
        'SELECT fichier_path, fichier_nom, user_id FROM contrats WHERE id = ?',
        (contrat_id,)
    ).fetchone()
    conn.close()

    if not contrat or not contrat['fichier_path']:
        flash("Aucun fichier associe a ce contrat.", 'error')
        return redirect(url_for('infos_salaries_bp.infos_salaries'))

    chemin = os.path.join(_get_documents_dir(), contrat['fichier_path'])
    chemin_reel = os.path.realpath(chemin)
    dossier_reel = os.path.realpath(_get_documents_dir())
    if not chemin_reel.startswith(dossier_reel) or not os.path.exists(chemin):
        flash("Fichier introuvable sur le serveur.", 'error')
        return redirect(url_for('infos_salaries_bp.infos_salaries', user_id=contrat['user_id']))

    return send_file(chemin, as_attachment=True,
                     download_name=contrat['fichier_nom'] or contrat['fichier_path'])


@infos_salaries_bp.route('/infos_salaries/supprimer_contrat/<int:contrat_id>', methods=['POST'])
@login_required
def supprimer_contrat(contrat_id):
    """Supprimer un contrat."""
    if not _peut_gerer():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    contrat = conn.execute('SELECT * FROM contrats WHERE id = ?', (contrat_id,)).fetchone()
    if not contrat:
        flash("Contrat introuvable.", 'error')
        conn.close()
        return redirect(url_for('infos_salaries_bp.infos_salaries'))

    user_id = contrat['user_id']
    _supprimer_fichier(contrat['fichier_path'])
    conn.execute('DELETE FROM contrats WHERE id = ?', (contrat_id,))
    conn.commit()
    conn.close()

    flash("Contrat supprime.", 'success')
    return redirect(url_for('infos_salaries_bp.infos_salaries', user_id=user_id))
