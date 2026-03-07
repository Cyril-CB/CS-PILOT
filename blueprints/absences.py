"""
Blueprint absences_bp.
Gestion des arrets maladie, conges et absences.
"""
import os
import json
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, send_file, current_app)
from datetime import datetime, timedelta
from database import get_db, DATA_DIR
from utils import (login_required, get_user_info, get_heures_theoriques_jour,
                   get_type_periode, get_planning_valide_a_date)

absences_bp = Blueprint('absences_bp', __name__)

MOTIFS_ABSENCE = [
    'Congé payé',
    'Congé conventionnel',
    'Arrêt maladie',
    'Congé parental',
    'Jour enfant malade',
    'Accident du travail',
    'Evènement familial',
    'Sans solde',
    'Mi-temps thérapeutique',
    'Autre',
]

DOCUMENTS_DIR = os.path.join(DATA_DIR, 'documents')


def _get_documents_dir():
    """Retourne le chemin du dossier documents, le cree si necessaire."""
    if not os.path.exists(DOCUMENTS_DIR):
        os.makedirs(DOCUMENTS_DIR, exist_ok=True)
    return DOCUMENTS_DIR


def _calculer_jours_ouvres_sans_feries(date_debut_str, date_fin_str):
    """Calcule le nombre de jours ouvres entre deux dates, en excluant weekends ET jours feries."""
    date_debut = datetime.strptime(date_debut_str, '%Y-%m-%d')
    date_fin = datetime.strptime(date_fin_str, '%Y-%m-%d')

    if date_debut > date_fin:
        return 0

    # Recuperer tous les jours feries entre les deux dates
    conn = get_db()
    feries_rows = conn.execute('''
        SELECT date FROM jours_feries
        WHERE date >= ? AND date <= ?
    ''', (date_debut_str, date_fin_str)).fetchall()
    conn.close()

    jours_feries = {row['date'] for row in feries_rows}

    nb_jours = 0
    jour_actuel = date_debut
    while jour_actuel <= date_fin:
        date_str = jour_actuel.strftime('%Y-%m-%d')
        # Compter uniquement les jours ouvres (lundi-vendredi) qui ne sont pas feries
        if jour_actuel.weekday() < 5 and date_str not in jours_feries:
            nb_jours += 1
        jour_actuel += timedelta(days=1)

    return nb_jours


def _peut_gerer_absences():
    """Verifie si l'utilisateur connecte peut gerer les absences."""
    return session.get('profil') in ['comptable', 'directeur']


def _actualiser_compteurs_conges(conn, user_id, motif, jours_ouvres, ajout=True):
    """Actualise les compteurs de conges d'un salarie lors d'une saisie ou suppression.

    Args:
        conn: connexion DB active (pas de commit ici)
        user_id: id du salarie
        motif: motif d'absence ('Congé payé' ou 'Congé conventionnel')
        jours_ouvres: nombre de jours ouvres
        ajout: True pour une nouvelle absence, False pour une suppression
    """
    if motif == 'Congé payé':
        user = conn.execute('SELECT cp_a_prendre, cp_pris FROM users WHERE id = ?', (user_id,)).fetchone()
        if not user:
            return
        cp_pris = (user['cp_pris'] or 0)
        cp_a_prendre = (user['cp_a_prendre'] or 0)

        if ajout:
            cp_pris += jours_ouvres
        else:
            cp_pris -= jours_ouvres
            if cp_pris < 0:
                # After monthly closure, cp_pris was absorbed into cp_a_prendre
                # (cp_a_prendre -= cp_pris, cp_pris = 0). The negative remainder
                # represents days already folded into cp_a_prendre that must be
                # credited back to undo the original deduction.
                cp_a_prendre += abs(cp_pris)
                cp_pris = 0

        conn.execute('UPDATE users SET cp_pris = ?, cp_a_prendre = ? WHERE id = ?',
                     (cp_pris, cp_a_prendre, user_id))

    elif motif == 'Congé conventionnel':
        user = conn.execute('SELECT cc_solde FROM users WHERE id = ?', (user_id,)).fetchone()
        if not user:
            return
        cc_solde = (user['cc_solde'] or 0)

        if ajout:
            cc_solde -= jours_ouvres
        else:
            cc_solde += jours_ouvres

        conn.execute('UPDATE users SET cc_solde = ? WHERE id = ?', (cc_solde, user_id))


def _reporter_absence_sur_calendrier(conn, absence_id, user_id, date_debut_str, date_fin_str, motif):
    """Reporte les jours d'absence sur heures_reelles avec declaration conforme (heures theoriques)."""
    date_debut = datetime.strptime(date_debut_str, '%Y-%m-%d')
    date_fin = datetime.strptime(date_fin_str, '%Y-%m-%d')

    # Recuperer les jours feries
    feries_rows = conn.execute('''
        SELECT date FROM jours_feries
        WHERE date >= ? AND date <= ?
    ''', (date_debut_str, date_fin_str)).fetchall()
    jours_feries = {row['date'] for row in feries_rows}

    jour_actuel = date_debut
    while jour_actuel <= date_fin:
        date_str = jour_actuel.strftime('%Y-%m-%d')
        jour_semaine = jour_actuel.weekday()

        # Uniquement jours ouvres et non feries
        if jour_semaine < 5 and date_str not in jours_feries:
            commentaire = f"Absence #{absence_id} - {motif}"

            # Inserer ou remplacer dans heures_reelles avec declaration_conforme
            conn.execute('''
                INSERT OR REPLACE INTO heures_reelles
                (user_id, date, heure_debut_matin, heure_fin_matin,
                 heure_debut_aprem, heure_fin_aprem, commentaire, type_saisie, declaration_conforme)
                VALUES (?, ?, NULL, NULL, NULL, NULL, ?, 'absence', 1)
            ''', (user_id, date_str, commentaire))

        jour_actuel += timedelta(days=1)


def _supprimer_absence_du_calendrier(conn, absence_id, user_id, date_debut_str, date_fin_str):
    """Supprime les entrees heures_reelles liees a une absence."""
    conn.execute('''
        DELETE FROM heures_reelles
        WHERE user_id = ? AND date >= ? AND date <= ?
        AND type_saisie = 'absence'
        AND commentaire LIKE ?
    ''', (user_id, date_debut_str, date_fin_str, f"Absence #{absence_id}%"))


@absences_bp.route('/absences', methods=['GET', 'POST'])
@login_required
def absences():
    """Page principale de saisie et liste des absences."""
    if not _peut_gerer_absences():
        flash('Accès non autorisé. Seuls le comptable et la direction peuvent saisir les absences.', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()

    if request.method == 'POST':
        user_id = request.form.get('user_id', type=int)
        motif = request.form.get('motif', '').strip()
        date_debut = request.form.get('date_debut', '').strip()
        date_fin = request.form.get('date_fin', '').strip()
        date_reprise = request.form.get('date_reprise', '').strip() or None
        commentaire = request.form.get('commentaire', '').strip() or None

        # Validations
        if not user_id or not motif or not date_debut or not date_fin:
            flash('Veuillez remplir tous les champs obligatoires.', 'error')
            conn.close()
            return redirect(url_for('absences_bp.absences'))

        if motif not in MOTIFS_ABSENCE:
            flash('Motif d\'absence invalide.', 'error')
            conn.close()
            return redirect(url_for('absences_bp.absences'))

        if date_debut > date_fin:
            flash('La date de fin doit être postérieure ou égale à la date de début.', 'error')
            conn.close()
            return redirect(url_for('absences_bp.absences'))

        # Calculer jours ouvres (sans feries)
        jours_ouvres = _calculer_jours_ouvres_sans_feries(date_debut, date_fin)

        if jours_ouvres == 0:
            flash('Aucun jour ouvré dans la période sélectionnée.', 'error')
            conn.close()
            return redirect(url_for('absences_bp.absences'))

        # Gerer le justificatif
        justificatif_path = None
        justificatif_nom = None
        fichier = request.files.get('justificatif')

        if fichier and fichier.filename:
            # Verifier l'extension
            ext = os.path.splitext(fichier.filename)[1].lower()
            if ext not in ['.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp']:
                flash('Format de fichier non autorisé. Formats acceptés : PDF, JPG, PNG, GIF, BMP.', 'error')
                conn.close()
                return redirect(url_for('absences_bp.absences'))

            # Recuperer les infos du salarie pour le nom de fichier
            salarie = conn.execute('SELECT nom, prenom FROM users WHERE id = ?', (user_id,)).fetchone()
            if salarie:
                date_fmt = datetime.strptime(date_debut, '%Y-%m-%d').strftime('%d-%m-%Y')
                nom_fichier = f"{date_fmt}_{salarie['nom']}_{salarie['prenom']}_{motif.replace(' ', '_')}{ext}"
                # Nettoyer le nom de fichier
                nom_fichier = "".join(c for c in nom_fichier if c.isalnum() or c in '-_.')

                docs_dir = _get_documents_dir()
                chemin_complet = os.path.join(docs_dir, nom_fichier)

                # Eviter les doublons
                compteur = 1
                base_nom = os.path.splitext(nom_fichier)[0]
                while os.path.exists(chemin_complet):
                    nom_fichier = f"{base_nom}_{compteur}{ext}"
                    chemin_complet = os.path.join(docs_dir, nom_fichier)
                    compteur += 1

                fichier.save(chemin_complet)
                justificatif_path = nom_fichier
                justificatif_nom = fichier.filename

        try:
            cursor = conn.execute('''
                INSERT INTO absences
                (user_id, motif, date_debut, date_fin, date_reprise, commentaire,
                 jours_ouvres, justificatif_path, justificatif_nom, saisi_par)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, motif, date_debut, date_fin, date_reprise, commentaire,
                  jours_ouvres, justificatif_path, justificatif_nom, session['user_id']))

            absence_id = cursor.lastrowid

            # Reporter sur le calendrier
            _reporter_absence_sur_calendrier(conn, absence_id, user_id, date_debut, date_fin, motif)

            # Actualiser les compteurs de conges si applicable
            if motif in ('Congé payé', 'Congé conventionnel'):
                _actualiser_compteurs_conges(conn, user_id, motif, jours_ouvres, ajout=True)

            # Historique
            conn.execute('''
                INSERT INTO historique_modifications
                (user_id_modifie, date_concernee, modifie_par, action, anciennes_valeurs, nouvelles_valeurs)
                VALUES (?, ?, ?, ?, NULL, ?)
            ''', (user_id, date_debut, session['user_id'], 'creation_absence',
                  json.dumps({
                      'motif': motif,
                      'date_debut': date_debut,
                      'date_fin': date_fin,
                      'jours_ouvres': jours_ouvres,
                      'commentaire': commentaire
                  })))

            conn.commit()
            flash(f'Absence enregistrée avec succès ({jours_ouvres} jours ouvrés). Les jours ont été reportés sur le calendrier.', 'success')
        except Exception as e:
            flash(f'Erreur lors de l\'enregistrement : {str(e)}', 'error')
        finally:
            conn.close()

        return redirect(url_for('absences_bp.absences'))

    # GET : afficher la page
    # Liste des salaries actifs
    salaries = conn.execute('''
        SELECT id, nom, prenom, profil FROM users
        WHERE actif = 1 AND profil != 'prestataire'
        ORDER BY nom, prenom
    ''').fetchall()

    # Recherche par salarie
    search_user_id = request.args.get('search_user_id', type=int)

    if search_user_id:
        absences_list = conn.execute('''
            SELECT a.*, u.nom as salarie_nom, u.prenom as salarie_prenom,
                   s.nom as saisi_par_nom, s.prenom as saisi_par_prenom
            FROM absences a
            JOIN users u ON a.user_id = u.id
            JOIN users s ON a.saisi_par = s.id
            WHERE a.user_id = ?
            ORDER BY a.date_debut DESC
        ''', (search_user_id,)).fetchall()
    else:
        # Derniers 20 enregistrements
        absences_list = conn.execute('''
            SELECT a.*, u.nom as salarie_nom, u.prenom as salarie_prenom,
                   s.nom as saisi_par_nom, s.prenom as saisi_par_prenom
            FROM absences a
            JOIN users u ON a.user_id = u.id
            JOIN users s ON a.saisi_par = s.id
            ORDER BY a.created_at DESC
            LIMIT 20
        ''').fetchall()

    conn.close()

    return render_template('absences.html',
                           salaries=salaries,
                           motifs=MOTIFS_ABSENCE,
                           absences_list=absences_list,
                           search_user_id=search_user_id)


@absences_bp.route('/absences/supprimer/<int:absence_id>', methods=['POST'])
@login_required
def supprimer_absence(absence_id):
    """Supprimer une absence et retirer les entrees du calendrier."""
    if not _peut_gerer_absences():
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    absence = conn.execute('SELECT * FROM absences WHERE id = ?', (absence_id,)).fetchone()

    if not absence:
        flash('Absence introuvable.', 'error')
        conn.close()
        return redirect(url_for('absences_bp.absences'))

    try:
        # Supprimer du calendrier
        _supprimer_absence_du_calendrier(conn, absence_id, absence['user_id'],
                                         absence['date_debut'], absence['date_fin'])

        # Actualiser les compteurs de conges si applicable
        if absence['motif'] in ('Congé payé', 'Congé conventionnel'):
            _actualiser_compteurs_conges(conn, absence['user_id'], absence['motif'],
                                         absence['jours_ouvres'], ajout=False)

        # Supprimer le justificatif si present
        if absence['justificatif_path']:
            docs_dir = _get_documents_dir()
            chemin = os.path.join(docs_dir, absence['justificatif_path'])
            chemin_reel = os.path.realpath(chemin)
            dossier_reel = os.path.realpath(docs_dir)
            if chemin_reel.startswith(dossier_reel + os.sep) and os.path.exists(chemin):
                os.remove(chemin)

        # Historique
        conn.execute('''
            INSERT INTO historique_modifications
            (user_id_modifie, date_concernee, modifie_par, action, anciennes_valeurs, nouvelles_valeurs)
            VALUES (?, ?, ?, ?, ?, NULL)
        ''', (absence['user_id'], absence['date_debut'], session['user_id'], 'suppression_absence',
              json.dumps({
                  'motif': absence['motif'],
                  'date_debut': absence['date_debut'],
                  'date_fin': absence['date_fin'],
                  'jours_ouvres': absence['jours_ouvres']
              })))

        conn.execute('DELETE FROM absences WHERE id = ?', (absence_id,))
        conn.commit()
        flash('Absence supprimée et calendrier mis à jour.', 'success')
    except Exception as e:
        flash(f'Erreur : {str(e)}', 'error')
    finally:
        conn.close()

    return redirect(url_for('absences_bp.absences'))


@absences_bp.route('/absences/justificatif/<int:absence_id>')
@login_required
def telecharger_justificatif(absence_id):
    """Telecharger le justificatif d'une absence."""
    if not _peut_gerer_absences() and session.get('profil') != 'prestataire':
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    absence = conn.execute('SELECT justificatif_path, justificatif_nom FROM absences WHERE id = ?',
                           (absence_id,)).fetchone()
    conn.close()

    if not absence or not absence['justificatif_path']:
        flash('Aucun justificatif pour cette absence.', 'error')
        return redirect(url_for('absences_bp.absences'))

    chemin = os.path.join(_get_documents_dir(), absence['justificatif_path'])

    if not os.path.exists(chemin):
        flash('Le fichier justificatif est introuvable sur le serveur.', 'error')
        return redirect(url_for('absences_bp.absences'))

    # Securite : verifier que le chemin est bien dans le dossier documents
    chemin_reel = os.path.realpath(chemin)
    dossier_reel = os.path.realpath(_get_documents_dir())
    if not chemin_reel.startswith(dossier_reel + os.sep):
        flash('Accès non autorisé au fichier.', 'error')
        return redirect(url_for('absences_bp.absences'))

    return send_file(chemin, as_attachment=True,
                     download_name=absence['justificatif_nom'] or absence['justificatif_path'])


@absences_bp.route('/absences/ouvrir_dossier')
@login_required
def ouvrir_dossier():
    """Renvoie le chemin du dossier documents (pour copier/coller dans l'explorateur)."""
    if not _peut_gerer_absences():
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    docs_dir = os.path.realpath(_get_documents_dir())
    flash(f'Chemin du dossier documents : {docs_dir}', 'success')
    return redirect(url_for('absences_bp.absences'))


@absences_bp.route('/api/absences/jours_ouvres')
@login_required
def api_jours_ouvres():
    """API pour calculer les jours ouvres (AJAX)."""
    date_debut = request.args.get('date_debut', '')
    date_fin = request.args.get('date_fin', '')

    if not date_debut or not date_fin:
        return {'jours_ouvres': 0}

    try:
        jours = _calculer_jours_ouvres_sans_feries(date_debut, date_fin)
        return {'jours_ouvres': jours}
    except Exception:
        return {'jours_ouvres': 0}


@absences_bp.route('/api/absences/compteurs_conges')
@login_required
def api_compteurs_conges():
    """API pour recuperer les compteurs de conges d'un salarie (AJAX)."""
    if not _peut_gerer_absences():
        return {'error': 'non autorise'}, 403

    user_id = request.args.get('user_id', type=int)
    if not user_id:
        return {'error': 'user_id requis'}, 400

    conn = get_db()
    user = conn.execute('''
        SELECT cp_acquis, cp_a_prendre, cp_pris, cc_solde
        FROM users WHERE id = ?
    ''', (user_id,)).fetchone()
    conn.close()

    if not user:
        return {'error': 'utilisateur introuvable'}, 404

    cp_acquis = user['cp_acquis'] or 0
    cp_a_prendre = user['cp_a_prendre'] or 0
    cp_pris = user['cp_pris'] or 0
    cp_solde = cp_a_prendre - cp_pris
    cc_solde = user['cc_solde'] or 0

    return {
        'cp_acquis': cp_acquis,
        'cp_a_prendre': cp_a_prendre,
        'cp_pris': cp_pris,
        'cp_solde': cp_solde,
        'cc_solde': cc_solde
    }
