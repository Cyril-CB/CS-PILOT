"""
Blueprint generation_contrat_bp.
Module de generation de contrats a partir de modeles DOCX.
"""
import os
import re
import html
import zipfile
from io import BytesIO
from datetime import datetime
from reportlab.pdfgen import canvas
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file
from database import get_db
from utils import login_required
from blueprints.pesee_alisfa import CRITERE_FIELDS, CRITERES_ALISFA

generation_contrat_bp = Blueprint('generation_contrat_bp', __name__)

CONTRACT_TYPES = ['CDI', 'CDD de remplacement', "CDD accroissement d'activite", 'CEE', 'Autres']
MODEL_EXTENSIONS = {'.docx'}
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELES_DIR = os.path.join(BASE_DIR, 'documents', 'contrats_modeles')
GEN_DIR = os.path.join(BASE_DIR, 'documents', 'contrats_generes')


def _peut_gerer():
    return session.get('profil') in ['comptable', 'directeur']


def _ensure_dirs():
    os.makedirs(MODELES_DIR, exist_ok=True)
    os.makedirs(GEN_DIR, exist_ok=True)


def _safe_path(base_dir, rel_path):
    path = os.path.realpath(os.path.join(base_dir, rel_path))
    base = os.path.realpath(base_dir)
    if not path.startswith(base + os.sep):
        return None
    return path


def _sanitize_name(name):
    return re.sub(r'[^a-zA-Z0-9_-]', '_', name or '')


def _replace_docx_placeholders(path, replacements):
    with open(path, 'rb') as f:
        source = f.read()
    src_zip = zipfile.ZipFile(BytesIO(source), 'r')
    out_buffer = BytesIO()
    out_zip = zipfile.ZipFile(out_buffer, 'w', zipfile.ZIP_DEFLATED)
    for item in src_zip.infolist():
        data = src_zip.read(item.filename)
        if item.filename.endswith('.xml'):
            try:
                text = data.decode('utf-8')
                for key, val in replacements.items():
                    text = text.replace(f'***{key}***', str(val or ''))
                data = text.encode('utf-8')
            except Exception:
                pass
        out_zip.writestr(item, data)
    src_zip.close()
    out_zip.close()
    return out_buffer.getvalue()


def _extract_docx_text(docx_bytes):
    try:
        zf = zipfile.ZipFile(BytesIO(docx_bytes), 'r')
        xml = zf.read('word/document.xml').decode('utf-8', errors='ignore')
        zf.close()
    except Exception:
        return ''
    parts = re.findall(r'<w:t[^>]*>(.*?)</w:t>', xml)
    return html.unescape(' '.join(parts))


def _build_pdf(text, pdf_path, title):
    c = canvas.Canvas(pdf_path)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, 800, title)
    c.setFont("Helvetica", 10)
    y = 780
    for chunk in re.findall(r'.{1,110}(?:\s+|$)', text or ''):
        c.drawString(40, y, chunk.strip())
        y -= 14
        if y < 50:
            c.showPage()
            c.setFont("Helvetica", 10)
            y = 800
    c.save()


def _get_critere_points(poste_row):
    points = {}
    for i, field in enumerate(CRITERE_FIELDS, start=1):
        niveau = poste_row[field] if poste_row else None
        val = ''
        if niveau is not None:
            criteres = CRITERES_ALISFA[i - 1]['niveaux']
            for niv in criteres:
                if niv['niveau'] == niveau:
                    val = str(niv['points'])
                    break
        points[f'CRITERE{i}'] = val
    return points


@generation_contrat_bp.route('/generation_contrat')
@login_required
def generation_contrat():
    if not _peut_gerer():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    salaries = conn.execute(
        "SELECT id, nom, prenom FROM users WHERE actif = 1 AND profil != 'prestataire' ORDER BY nom, prenom"
    ).fetchall()
    modeles = conn.execute("SELECT * FROM contrats_modeles ORDER BY nom_modele").fetchall()
    postes = conn.execute("SELECT id, intitule, total_points FROM postes_alisfa ORDER BY intitule").fetchall()
    responsables = conn.execute(
        "SELECT id, nom, prenom FROM users WHERE actif = 1 AND profil IN ('responsable', 'directeur') ORDER BY nom, prenom"
    ).fetchall()
    lieux = conn.execute("SELECT id, nom, adresse FROM contrats_lieux ORDER BY nom").fetchall()
    forfaits = conn.execute("SELECT id, montant, condition_label FROM contrats_forfaits ORDER BY montant").fetchall()
    socle = conn.execute("SELECT salaire_socle FROM contrats_settings WHERE id = 1").fetchone()
    selected_user_id = request.args.get('user_id', type=int)
    selected_salarie = None
    if selected_user_id:
        selected_salarie = conn.execute(
            "SELECT * FROM users WHERE id = ?", (selected_user_id,)
        ).fetchone()
    conn.close()

    return render_template(
        'generation_contrat.html',
        contract_types=CONTRACT_TYPES,
        salaries=salaries,
        modeles=modeles,
        postes=postes,
        responsables=responsables,
        lieux=lieux,
        forfaits=forfaits,
        socle=(socle['salaire_socle'] if socle else 23000),
        selected_user_id=selected_user_id,
        selected_salarie=selected_salarie,
    )


@generation_contrat_bp.route('/generation_contrat/modeles', methods=['POST'])
@login_required
def upload_modele():
    if not _peut_gerer():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    fichier = request.files.get('fichier_modele')
    nom_modele = request.form.get('nom_modele', '').strip()
    modele_id = request.form.get('modele_id', type=int)
    if not fichier or not fichier.filename:
        flash("Veuillez selectionner un modele DOCX.", 'error')
        return redirect(url_for('generation_contrat_bp.generation_contrat', tab='modeles'))
    ext = os.path.splitext(fichier.filename)[1].lower()
    if ext not in MODEL_EXTENSIONS:
        flash("Le modele doit etre au format DOCX.", 'error')
        return redirect(url_for('generation_contrat_bp.generation_contrat', tab='modeles'))

    _ensure_dirs()
    if not nom_modele:
        nom_modele = os.path.splitext(fichier.filename)[0]
    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{_sanitize_name(nom_modele)}.docx"
    fichier_path = os.path.join(MODELES_DIR, filename)
    fichier.save(fichier_path)

    conn = get_db()
    if modele_id:
        existing = conn.execute("SELECT fichier_path FROM contrats_modeles WHERE id = ?", (modele_id,)).fetchone()
        if existing:
            old_path = _safe_path(MODELES_DIR, existing['fichier_path'])
            if old_path and os.path.exists(old_path):
                os.remove(old_path)
        conn.execute(
            "UPDATE contrats_modeles SET nom_modele = ?, fichier_path = ?, saisi_par = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (nom_modele, filename, session['user_id'], modele_id)
        )
    else:
        conn.execute(
            "INSERT INTO contrats_modeles (nom_modele, fichier_path, saisi_par) VALUES (?, ?, ?)",
            (nom_modele, filename, session['user_id'])
        )
    conn.commit()
    conn.close()
    flash("Modele enregistre.", 'success')
    return redirect(url_for('generation_contrat_bp.generation_contrat', tab='modeles'))


@generation_contrat_bp.route('/generation_contrat/modeles/<int:modele_id>/telecharger')
@login_required
def telecharger_modele(modele_id):
    if not _peut_gerer():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    conn = get_db()
    modele = conn.execute("SELECT * FROM contrats_modeles WHERE id = ?", (modele_id,)).fetchone()
    conn.close()
    if not modele:
        flash("Modele introuvable.", 'error')
        return redirect(url_for('generation_contrat_bp.generation_contrat', tab='modeles'))
    file_path = _safe_path(MODELES_DIR, modele['fichier_path'])
    if not file_path or not os.path.exists(file_path):
        flash("Fichier introuvable.", 'error')
        return redirect(url_for('generation_contrat_bp.generation_contrat', tab='modeles'))
    return send_file(file_path, as_attachment=True, download_name=os.path.basename(modele['fichier_path']))


@generation_contrat_bp.route('/generation_contrat/modeles/<int:modele_id>/supprimer', methods=['POST'])
@login_required
def supprimer_modele(modele_id):
    if not _peut_gerer():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    conn = get_db()
    modele = conn.execute("SELECT * FROM contrats_modeles WHERE id = ?", (modele_id,)).fetchone()
    if modele:
        file_path = _safe_path(MODELES_DIR, modele['fichier_path'])
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        conn.execute("DELETE FROM contrats_modeles WHERE id = ?", (modele_id,))
        conn.commit()
        flash("Modele supprime.", 'success')
    conn.close()
    return redirect(url_for('generation_contrat_bp.generation_contrat', tab='modeles'))


@generation_contrat_bp.route('/generation_contrat/lieu', methods=['POST'])
@login_required
def ajouter_lieu():
    if not _peut_gerer():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    nom = request.form.get('nom_lieu', '').strip()
    adresse = request.form.get('adresse_lieu', '').strip() or None
    if not nom:
        flash("Nom du lieu obligatoire.", 'error')
    else:
        conn = get_db()
        conn.execute("INSERT OR IGNORE INTO contrats_lieux (nom, adresse) VALUES (?, ?)", (nom, adresse))
        conn.commit()
        conn.close()
        flash("Lieu enregistre.", 'success')
    return redirect(url_for('generation_contrat_bp.generation_contrat'))


@generation_contrat_bp.route('/generation_contrat/forfait', methods=['POST'])
@login_required
def ajouter_forfait():
    if not _peut_gerer():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    montant = request.form.get('montant_forfait', '').strip()
    condition = request.form.get('condition_forfait', '').strip() or None
    if not montant:
        flash("Montant du forfait obligatoire.", 'error')
    else:
        conn = get_db()
        conn.execute(
            "INSERT INTO contrats_forfaits (montant, condition_label) VALUES (?, ?)",
            (montant, condition)
        )
        conn.commit()
        conn.close()
        flash("Forfait enregistre.", 'success')
    return redirect(url_for('generation_contrat_bp.generation_contrat'))


@generation_contrat_bp.route('/generation_contrat/generer', methods=['POST'])
@login_required
def generer_contrat():
    if not _peut_gerer():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    user_id = request.form.get('user_id', type=int)
    template_id = request.form.get('template_id', type=int)
    poste_id = request.form.get('poste_id', type=int)
    responsable_id = request.form.get('responsable_id', type=int)
    type_contrat = request.form.get('type_contrat', '').strip()
    if not user_id or not template_id or not type_contrat:
        flash("Salarie, modele et type de contrat sont obligatoires.", 'error')
        return redirect(url_for('generation_contrat_bp.generation_contrat', user_id=user_id))

    conn = get_db()
    salarie = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    modele = conn.execute("SELECT * FROM contrats_modeles WHERE id = ?", (template_id,)).fetchone()
    poste = conn.execute("SELECT * FROM postes_alisfa WHERE id = ?", (poste_id,)).fetchone() if poste_id else None
    responsable = conn.execute("SELECT nom, prenom FROM users WHERE id = ?", (responsable_id,)).fetchone() if responsable_id else None
    lieux_rows = []
    lieux_ids = request.form.getlist('lieux_ids')
    if lieux_ids:
        placeholders = ','.join(['?'] * min(len(lieux_ids), 3))
        lieux_rows = conn.execute(
            f"SELECT nom, adresse FROM contrats_lieux WHERE id IN ({placeholders}) LIMIT 3",
            tuple(lieux_ids[:3])
        ).fetchall()
    if not salarie or not modele:
        conn.close()
        flash("Donnees invalides pour la generation.", 'error')
        return redirect(url_for('generation_contrat_bp.generation_contrat', user_id=user_id))

    socle_raw = request.form.get('socle', '23000').replace(',', '.').strip() or '23000'
    brutm_raw = request.form.get('brutm', '').replace(',', '.').strip()
    try:
        socle = float(socle_raw)
    except ValueError:
        socle = 23000.0
    try:
        brutm = float(brutm_raw) if brutm_raw else None
    except ValueError:
        brutm = None
    conn.execute(
        "UPDATE contrats_settings SET salaire_socle = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
        (socle,)
    )

    replacements = {
        'NOM': salarie['nom'] or '',
        'PRENOM': salarie['prenom'] or '',
        'ADRESSE': salarie['adresse_postale'] or '',
        'EMAIL': salarie['email'] or '',
        'DATE_NAISSANCE': salarie['date_naissance'] or '',
        'NUMERO_SECURITE_SOCIALE': salarie['numero_securite_sociale'] or '',
        'TYPE_CONTRAT': type_contrat,
        'DEBUT': request.form.get('date_debut', '').strip(),
        'FIN': request.form.get('date_fin', '').strip(),
        'REMPLACE': request.form.get('remplace', '').strip(),
        'POSTE': poste['intitule'] if poste else '',
        'RESPONSABLE': f"{responsable['nom']} {responsable['prenom']}" if responsable else '',
        'HEBDO': request.form.get('hebdo', '').strip(),
        'ESSAI': request.form.get('essai', '').strip(),
        'LIEU': ', '.join([lr['nom'] for lr in lieux_rows]),
        'SOCLE': str(int(socle) if socle.is_integer() else socle),
        'BRUTM': '' if type_contrat == 'CEE' else (
            str(int(brutm) if brutm is not None and brutm.is_integer() else brutm) if brutm is not None else ''
        ),
        'PESEE': str(poste['total_points']) if poste else '',
        'ANCIENNETE': request.form.get('anciennete', '').strip(),
        'FORFAIT': request.form.get('forfait', '').strip(),
        'JOURS': request.form.get('jours', '').strip(),
        'LUNDI': request.form.get('lundi', '').strip(),
        'MARDI': request.form.get('mardi', '').strip(),
        'MERCREDI': request.form.get('mercredi', '').strip(),
        'JEUDI': request.form.get('jeudi', '').strip(),
        'VENDREDI': request.form.get('vendredi', '').strip(),
    }
    replacements.update(_get_critere_points(poste))

    modele_path = _safe_path(MODELES_DIR, modele['fichier_path'])
    if not modele_path or not os.path.exists(modele_path):
        conn.close()
        flash("Modele DOCX introuvable.", 'error')
        return redirect(url_for('generation_contrat_bp.generation_contrat', user_id=user_id))

    _ensure_dirs()
    merged_docx = _replace_docx_placeholders(modele_path, replacements)
    texte = _extract_docx_text(merged_docx)
    now = datetime.now().strftime('%Y%m%d_%H%M%S')
    pdf_name = f"contrat_{_sanitize_name(salarie['nom'])}_{_sanitize_name(salarie['prenom'])}_{now}.pdf"
    pdf_path = os.path.join(GEN_DIR, pdf_name)
    _build_pdf(texte, pdf_path, f"Contrat {type_contrat} - {salarie['nom']} {salarie['prenom']}")

    old = conn.execute("SELECT fichier_pdf_path FROM contrats_generes WHERE user_id = ?", (user_id,)).fetchone()
    if old:
        old_path = _safe_path(GEN_DIR, old['fichier_pdf_path'])
        if old_path and os.path.exists(old_path):
            os.remove(old_path)
    conn.execute(
        '''
        INSERT INTO contrats_generes (user_id, template_id, fichier_pdf_path, fichier_pdf_nom, generated_by)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            template_id = excluded.template_id,
            fichier_pdf_path = excluded.fichier_pdf_path,
            fichier_pdf_nom = excluded.fichier_pdf_nom,
            generated_by = excluded.generated_by,
            generated_at = CURRENT_TIMESTAMP
        ''',
        (user_id, template_id, pdf_name, pdf_name, session['user_id'])
    )
    conn.commit()
    conn.close()

    return send_file(pdf_path, as_attachment=True, download_name=pdf_name, mimetype='application/pdf')


@generation_contrat_bp.route('/generation_contrat/dernier/<int:user_id>')
@login_required
def telecharger_dernier_contrat(user_id):
    if not _peut_gerer():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    conn = get_db()
    row = conn.execute(
        "SELECT fichier_pdf_path, fichier_pdf_nom FROM contrats_generes WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    if not row:
        flash("Aucun contrat genere pour ce salarie.", 'error')
        return redirect(url_for('generation_contrat_bp.generation_contrat', user_id=user_id))
    pdf_path = _safe_path(GEN_DIR, row['fichier_pdf_path'])
    if not pdf_path or not os.path.exists(pdf_path):
        flash("Fichier introuvable.", 'error')
        return redirect(url_for('generation_contrat_bp.generation_contrat', user_id=user_id))
    return send_file(pdf_path, as_attachment=True, download_name=row['fichier_pdf_nom'])
