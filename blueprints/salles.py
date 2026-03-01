"""
Blueprint salles_bp.
Gestion des reservations de salles avec recurrences.
"""
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify)
from datetime import datetime, timedelta
from database import get_db
from utils import login_required, get_user_info

salles_bp = Blueprint('salles_bp', __name__)

JOURS_SEMAINE = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']


# ── Helpers ──────────────────────────────────────────────────────────────

def _est_admin():
    """Verifie si l'utilisateur est directeur ou comptable."""
    return session.get('profil') in ('directeur', 'comptable')


def _get_dates_exclues(conn, date_debut_str, date_fin_str, exclure_vacances, exclure_feries):
    """Retourne l'ensemble des dates a exclure (vacances + feries) dans la plage."""
    dates_exclues = set()

    if exclure_vacances:
        periodes = conn.execute('''
            SELECT date_debut, date_fin FROM periodes_vacances
            WHERE date_fin >= ? AND date_debut <= ?
        ''', (date_debut_str, date_fin_str)).fetchall()
        for p in periodes:
            d = max(datetime.strptime(p['date_debut'], '%Y-%m-%d'),
                    datetime.strptime(date_debut_str, '%Y-%m-%d'))
            fin = min(datetime.strptime(p['date_fin'], '%Y-%m-%d'),
                      datetime.strptime(date_fin_str, '%Y-%m-%d'))
            while d <= fin:
                dates_exclues.add(d.strftime('%Y-%m-%d'))
                d += timedelta(days=1)

    if exclure_feries:
        rows = conn.execute('''
            SELECT date FROM jours_feries
            WHERE date >= ? AND date <= ?
        ''', (date_debut_str, date_fin_str)).fetchall()
        for r in rows:
            dates_exclues.add(r['date'])

    return dates_exclues


def _generer_reservations_recurrence(conn, recurrence):
    """Genere toutes les reservations individuelles pour une recurrence."""
    date_debut = datetime.strptime(recurrence['date_debut'], '%Y-%m-%d')
    date_fin = datetime.strptime(recurrence['date_fin'], '%Y-%m-%d')
    jour_semaine = recurrence['jour_semaine']

    dates_exclues = _get_dates_exclues(
        conn,
        recurrence['date_debut'],
        recurrence['date_fin'],
        recurrence['exclure_vacances'],
        recurrence['exclure_feries']
    )

    # Trouver le premier jour correspondant au jour_semaine
    d = date_debut
    # En Python : lundi=0 ... dimanche=6 (meme convention que notre champ)
    while d.weekday() != jour_semaine:
        d += timedelta(days=1)

    reservations = []
    while d <= date_fin:
        date_str = d.strftime('%Y-%m-%d')
        if date_str not in dates_exclues:
            # Verifier qu'il n'y a pas de conflit
            conflit = conn.execute('''
                SELECT id FROM reservations_salles
                WHERE salle_id = ? AND date = ?
                AND heure_debut < ? AND heure_fin > ?
            ''', (recurrence['salle_id'], date_str,
                  recurrence['heure_fin'], recurrence['heure_debut'])).fetchone()
            if not conflit:
                reservations.append(date_str)
        d += timedelta(days=7)

    for date_str in reservations:
        conn.execute('''
            INSERT INTO reservations_salles
            (salle_id, titre, description, date, heure_debut, heure_fin,
             recurrence_id, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (recurrence['salle_id'], recurrence['titre'],
              recurrence['description'], date_str,
              recurrence['heure_debut'], recurrence['heure_fin'],
              recurrence['id'], recurrence['created_by']))

    return len(reservations)


def _verifier_conflit(conn, salle_id, date, heure_debut, heure_fin, exclure_id=None):
    """Verifie s'il y a un conflit de reservation."""
    query = '''
        SELECT r.*, u.prenom, u.nom as nom_user
        FROM reservations_salles r
        LEFT JOIN users u ON r.created_by = u.id
        WHERE r.salle_id = ? AND r.date = ?
        AND r.heure_debut < ? AND r.heure_fin > ?
    '''
    params = [salle_id, date, heure_fin, heure_debut]
    if exclure_id:
        query += ' AND r.id != ?'
        params.append(exclure_id)
    return conn.execute(query, params).fetchone()


# ── Routes principales ───────────────────────────────────────────────────

@salles_bp.route('/salles')
@login_required
def salles():
    """Page principale : liste des salles et disponibilites."""
    conn = get_db()
    try:
        salles_list = conn.execute(
            'SELECT * FROM salles WHERE active = 1 ORDER BY nom'
        ).fetchall()

        # Date selectionnee (par defaut aujourd'hui)
        date_sel = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))

        # Reservations du jour selectionne
        reservations = conn.execute('''
            SELECT r.*, s.nom as salle_nom, s.couleur,
                   u.prenom, u.nom as nom_user
            FROM reservations_salles r
            JOIN salles s ON r.salle_id = s.id
            LEFT JOIN users u ON r.created_by = u.id
            WHERE r.date = ?
            ORDER BY r.heure_debut, s.nom
        ''', (date_sel,)).fetchall()

        # Recurrences actives
        recurrences = conn.execute('''
            SELECT rc.*, s.nom as salle_nom, u.prenom, u.nom as nom_user
            FROM recurrences_salles rc
            JOIN salles s ON rc.salle_id = s.id
            LEFT JOIN users u ON rc.created_by = u.id
            WHERE rc.active = 1
            ORDER BY rc.jour_semaine, rc.heure_debut
        ''').fetchall()

        # Utilisateurs pour le formulaire
        users = conn.execute(
            'SELECT id, prenom, nom FROM users WHERE actif = 1 ORDER BY prenom, nom'
        ).fetchall()

        return render_template('salles.html',
                               salles=salles_list,
                               reservations=reservations,
                               recurrences=recurrences,
                               users=users,
                               date_sel=date_sel,
                               jours_semaine=JOURS_SEMAINE,
                               is_admin=_est_admin(),
                               today=datetime.now().strftime('%Y-%m-%d'))
    finally:
        conn.close()


@salles_bp.route('/salles/calendrier/<int:salle_id>')
@login_required
def calendrier_salle(salle_id):
    """Vue calendrier mensuel pour une salle."""
    conn = get_db()
    try:
        salle = conn.execute('SELECT * FROM salles WHERE id = ?', (salle_id,)).fetchone()
        if not salle:
            flash('Salle introuvable.', 'error')
            return redirect(url_for('salles_bp.salles'))

        # Mois selectionne
        mois_str = request.args.get('mois', datetime.now().strftime('%Y-%m'))
        try:
            annee, mois = int(mois_str[:4]), int(mois_str[5:7])
        except (ValueError, IndexError):
            annee, mois = datetime.now().year, datetime.now().month

        # Premier et dernier jour du mois
        premier_jour = datetime(annee, mois, 1)
        if mois == 12:
            dernier_jour = datetime(annee + 1, 1, 1) - timedelta(days=1)
        else:
            dernier_jour = datetime(annee, mois + 1, 1) - timedelta(days=1)

        date_debut_str = premier_jour.strftime('%Y-%m-%d')
        date_fin_str = dernier_jour.strftime('%Y-%m-%d')

        # Reservations du mois
        reservations = conn.execute('''
            SELECT r.*, u.prenom, u.nom as nom_user
            FROM reservations_salles r
            LEFT JOIN users u ON r.created_by = u.id
            WHERE r.salle_id = ? AND r.date >= ? AND r.date <= ?
            ORDER BY r.date, r.heure_debut
        ''', (salle_id, date_debut_str, date_fin_str)).fetchall()

        # Organiser par date
        resa_par_date = {}
        for r in reservations:
            if r['date'] not in resa_par_date:
                resa_par_date[r['date']] = []
            resa_par_date[r['date']].append(r)

        # Construire le calendrier (semaines)
        semaines = []
        # Commencer au lundi de la semaine du premier jour
        d = premier_jour - timedelta(days=premier_jour.weekday())
        while d <= dernier_jour or d.weekday() != 0:
            if d.weekday() == 0:
                semaines.append([])
            date_str = d.strftime('%Y-%m-%d')
            semaines[-1].append({
                'date': date_str,
                'jour': d.day,
                'mois_courant': d.month == mois,
                'aujourd_hui': date_str == datetime.now().strftime('%Y-%m-%d'),
                'reservations': resa_par_date.get(date_str, [])
            })
            if d.weekday() == 6 and d > dernier_jour:
                break
            d += timedelta(days=1)

        # Navigation mois precedent/suivant
        if mois == 1:
            mois_prec = f'{annee - 1}-12'
        else:
            mois_prec = f'{annee}-{mois - 1:02d}'
        if mois == 12:
            mois_suiv = f'{annee + 1}-01'
        else:
            mois_suiv = f'{annee}-{mois + 1:02d}'

        mois_noms = ['', 'Janvier', 'Fevrier', 'Mars', 'Avril', 'Mai', 'Juin',
                     'Juillet', 'Aout', 'Septembre', 'Octobre', 'Novembre', 'Decembre']

        # Toutes les salles pour navigation
        toutes_salles = conn.execute(
            'SELECT id, nom FROM salles WHERE active = 1 ORDER BY nom'
        ).fetchall()

        return render_template('salles_calendrier.html',
                               salle=salle,
                               toutes_salles=toutes_salles,
                               semaines=semaines,
                               mois_nom=mois_noms[mois],
                               annee=annee,
                               mois=mois,
                               mois_str=mois_str,
                               mois_prec=mois_prec,
                               mois_suiv=mois_suiv,
                               is_admin=_est_admin())
    finally:
        conn.close()


# ── Gestion des salles (admin) ───────────────────────────────────────────

@salles_bp.route('/salles/ajouter', methods=['POST'])
@login_required
def ajouter_salle():
    """Ajouter une nouvelle salle."""
    if not _est_admin():
        flash('Acces refuse.', 'error')
        return redirect(url_for('salles_bp.salles'))

    nom = request.form.get('nom', '').strip()
    capacite = request.form.get('capacite', '').strip()
    description = request.form.get('description', '').strip()
    couleur = request.form.get('couleur', '#2563eb').strip()

    if not nom:
        flash('Le nom de la salle est obligatoire.', 'error')
        return redirect(url_for('salles_bp.salles'))

    conn = get_db()
    try:
        conn.execute('''
            INSERT INTO salles (nom, capacite, description, couleur)
            VALUES (?, ?, ?, ?)
        ''', (nom, int(capacite) if capacite else None, description, couleur))
        conn.commit()
        flash(f'Salle "{nom}" ajoutee.', 'success')
    finally:
        conn.close()

    return redirect(url_for('salles_bp.salles'))


@salles_bp.route('/salles/modifier/<int:salle_id>', methods=['POST'])
@login_required
def modifier_salle(salle_id):
    """Modifier une salle existante."""
    if not _est_admin():
        flash('Acces refuse.', 'error')
        return redirect(url_for('salles_bp.salles'))

    nom = request.form.get('nom', '').strip()
    capacite = request.form.get('capacite', '').strip()
    description = request.form.get('description', '').strip()
    couleur = request.form.get('couleur', '#2563eb').strip()

    if not nom:
        flash('Le nom de la salle est obligatoire.', 'error')
        return redirect(url_for('salles_bp.salles'))

    conn = get_db()
    try:
        conn.execute('''
            UPDATE salles SET nom = ?, capacite = ?, description = ?, couleur = ?
            WHERE id = ?
        ''', (nom, int(capacite) if capacite else None, description, couleur, salle_id))
        conn.commit()
        flash(f'Salle "{nom}" modifiee.', 'success')
    finally:
        conn.close()

    return redirect(url_for('salles_bp.salles'))


@salles_bp.route('/salles/supprimer/<int:salle_id>', methods=['POST'])
@login_required
def supprimer_salle(salle_id):
    """Desactiver une salle (soft delete)."""
    if not _est_admin():
        flash('Acces refuse.', 'error')
        return redirect(url_for('salles_bp.salles'))

    conn = get_db()
    try:
        conn.execute('UPDATE salles SET active = 0 WHERE id = ?', (salle_id,))
        conn.commit()
        flash('Salle desactivee.', 'success')
    finally:
        conn.close()

    return redirect(url_for('salles_bp.salles'))


# ── Reservations ponctuelles ─────────────────────────────────────────────

@salles_bp.route('/salles/reserver', methods=['POST'])
@login_required
def reserver():
    """Creer une reservation ponctuelle."""
    salle_id = request.form.get('salle_id', type=int)
    titre = request.form.get('titre', '').strip()
    description = request.form.get('description_resa', '').strip()
    date = request.form.get('date', '').strip()
    heure_debut = request.form.get('heure_debut', '').strip()
    heure_fin = request.form.get('heure_fin', '').strip()

    if not all([salle_id, titre, date, heure_debut, heure_fin]):
        flash('Tous les champs obligatoires doivent etre remplis.', 'error')
        return redirect(url_for('salles_bp.salles'))

    if heure_fin <= heure_debut:
        flash("L'heure de fin doit etre apres l'heure de debut.", 'error')
        return redirect(url_for('salles_bp.salles'))

    conn = get_db()
    try:
        conflit = _verifier_conflit(conn, salle_id, date, heure_debut, heure_fin)
        if conflit:
            flash(f'Conflit : cette salle est deja reservee de {conflit["heure_debut"]} '
                  f'a {conflit["heure_fin"]} par {conflit["prenom"]} {conflit["nom_user"]} '
                  f'("{conflit["titre"]}").', 'error')
            return redirect(url_for('salles_bp.salles', date=date))

        conn.execute('''
            INSERT INTO reservations_salles
            (salle_id, titre, description, date, heure_debut, heure_fin, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (salle_id, titre, description, date, heure_debut, heure_fin,
              session.get('user_id')))
        conn.commit()
        flash(f'Reservation "{titre}" creee pour le {date[8:10]}/{date[5:7]}/{date[:4]}.', 'success')
    finally:
        conn.close()

    return redirect(url_for('salles_bp.salles', date=date))


@salles_bp.route('/salles/supprimer_reservation/<int:resa_id>', methods=['POST'])
@login_required
def supprimer_reservation(resa_id):
    """Supprimer une reservation ponctuelle."""
    conn = get_db()
    try:
        resa = conn.execute('SELECT * FROM reservations_salles WHERE id = ?', (resa_id,)).fetchone()
        if not resa:
            flash('Reservation introuvable.', 'error')
            return redirect(url_for('salles_bp.salles'))

        # Seul l'auteur ou un admin peut supprimer
        if resa['created_by'] != session.get('user_id') and not _est_admin():
            flash('Vous ne pouvez supprimer que vos propres reservations.', 'error')
            return redirect(url_for('salles_bp.salles'))

        date = resa['date']
        conn.execute('DELETE FROM reservations_salles WHERE id = ?', (resa_id,))
        conn.commit()
        flash('Reservation supprimee.', 'success')
    finally:
        conn.close()

    return redirect(url_for('salles_bp.salles', date=date))


# ── Recurrences ──────────────────────────────────────────────────────────

@salles_bp.route('/salles/recurrence', methods=['POST'])
@login_required
def creer_recurrence():
    """Creer une recurrence et generer les reservations."""
    if not _est_admin():
        flash('Seuls les administrateurs peuvent creer des recurrences.', 'error')
        return redirect(url_for('salles_bp.salles'))

    salle_id = request.form.get('salle_id', type=int)
    titre = request.form.get('titre_rec', '').strip()
    description = request.form.get('description_rec', '').strip()
    jour_semaine = request.form.get('jour_semaine', type=int)
    heure_debut = request.form.get('heure_debut_rec', '').strip()
    heure_fin = request.form.get('heure_fin_rec', '').strip()
    date_debut = request.form.get('date_debut_rec', '').strip()
    date_fin = request.form.get('date_fin_rec', '').strip()
    exclure_vacances = 1 if request.form.get('exclure_vacances') else 0
    exclure_feries = 1 if request.form.get('exclure_feries') else 0

    if not all([salle_id, titre, jour_semaine is not None, heure_debut, heure_fin,
                date_debut, date_fin]):
        flash('Tous les champs obligatoires doivent etre remplis.', 'error')
        return redirect(url_for('salles_bp.salles'))

    if heure_fin <= heure_debut:
        flash("L'heure de fin doit etre apres l'heure de debut.", 'error')
        return redirect(url_for('salles_bp.salles'))

    if date_fin <= date_debut:
        flash('La date de fin doit etre apres la date de debut.', 'error')
        return redirect(url_for('salles_bp.salles'))

    conn = get_db()
    try:
        cursor = conn.execute('''
            INSERT INTO recurrences_salles
            (salle_id, titre, description, jour_semaine, heure_debut, heure_fin,
             date_debut, date_fin, exclure_vacances, exclure_feries, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (salle_id, titre, description, jour_semaine, heure_debut, heure_fin,
              date_debut, date_fin, exclure_vacances, exclure_feries,
              session.get('user_id')))

        recurrence_id = cursor.lastrowid
        recurrence = conn.execute(
            'SELECT * FROM recurrences_salles WHERE id = ?', (recurrence_id,)
        ).fetchone()

        nb = _generer_reservations_recurrence(conn, recurrence)
        conn.commit()

        flash(f'Recurrence "{titre}" creee : {nb} reservation(s) generee(s) '
              f'(le {JOURS_SEMAINE[jour_semaine]}).', 'success')
    finally:
        conn.close()

    return redirect(url_for('salles_bp.salles'))


@salles_bp.route('/salles/supprimer_recurrence/<int:rec_id>', methods=['POST'])
@login_required
def supprimer_recurrence(rec_id):
    """Supprimer une recurrence et toutes ses reservations futures."""
    if not _est_admin():
        flash('Acces refuse.', 'error')
        return redirect(url_for('salles_bp.salles'))

    conn = get_db()
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        # Supprimer les reservations futures liees
        conn.execute('''
            DELETE FROM reservations_salles
            WHERE recurrence_id = ? AND date >= ?
        ''', (rec_id, today))
        # Desactiver la recurrence
        conn.execute('UPDATE recurrences_salles SET active = 0 WHERE id = ?', (rec_id,))
        conn.commit()
        flash('Recurrence desactivee et reservations futures supprimees.', 'success')
    finally:
        conn.close()

    return redirect(url_for('salles_bp.salles'))


@salles_bp.route('/salles/regenerer_recurrence/<int:rec_id>', methods=['POST'])
@login_required
def regenerer_recurrence(rec_id):
    """Regenerer les reservations d'une recurrence (apres mise a jour des vacances/feries)."""
    if not _est_admin():
        flash('Acces refuse.', 'error')
        return redirect(url_for('salles_bp.salles'))

    conn = get_db()
    try:
        recurrence = conn.execute(
            'SELECT * FROM recurrences_salles WHERE id = ? AND active = 1', (rec_id,)
        ).fetchone()
        if not recurrence:
            flash('Recurrence introuvable ou inactive.', 'error')
            return redirect(url_for('salles_bp.salles'))

        today = datetime.now().strftime('%Y-%m-%d')
        # Supprimer les reservations futures liees
        conn.execute('''
            DELETE FROM reservations_salles
            WHERE recurrence_id = ? AND date >= ?
        ''', (rec_id, today))

        # Ajuster la date de debut pour ne regenerer que le futur
        rec_dict = dict(recurrence)
        if rec_dict['date_debut'] < today:
            rec_dict['date_debut'] = today

        nb = _generer_reservations_recurrence(conn, rec_dict)
        conn.commit()
        flash(f'Recurrence regeneree : {nb} reservation(s) creee(s).', 'success')
    finally:
        conn.close()

    return redirect(url_for('salles_bp.salles'))


# ── API JSON ─────────────────────────────────────────────────────────────

@salles_bp.route('/salles/api/reservations')
@login_required
def api_reservations():
    """Retourne les reservations pour une date donnee (JSON)."""
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    conn = get_db()
    try:
        reservations = conn.execute('''
            SELECT r.id, r.salle_id, r.titre, r.description, r.date,
                   r.heure_debut, r.heure_fin, r.recurrence_id,
                   s.nom as salle_nom, s.couleur,
                   u.prenom, u.nom as nom_user
            FROM reservations_salles r
            JOIN salles s ON r.salle_id = s.id
            LEFT JOIN users u ON r.created_by = u.id
            WHERE r.date = ?
            ORDER BY r.heure_debut, s.nom
        ''', (date,)).fetchall()

        return jsonify([dict(r) for r in reservations])
    finally:
        conn.close()


@salles_bp.route('/salles/api/disponibilite')
@login_required
def api_disponibilite():
    """Verifie la disponibilite d'une salle pour un creneau (JSON)."""
    salle_id = request.args.get('salle_id', type=int)
    date = request.args.get('date', '')
    heure_debut = request.args.get('heure_debut', '')
    heure_fin = request.args.get('heure_fin', '')

    if not all([salle_id, date, heure_debut, heure_fin]):
        return jsonify({'disponible': False, 'erreur': 'Parametres manquants'})

    conn = get_db()
    try:
        conflit = _verifier_conflit(conn, salle_id, date, heure_debut, heure_fin)
        if conflit:
            return jsonify({
                'disponible': False,
                'conflit': {
                    'titre': conflit['titre'],
                    'heure_debut': conflit['heure_debut'],
                    'heure_fin': conflit['heure_fin'],
                    'par': f"{conflit['prenom']} {conflit['nom_user']}"
                }
            })
        return jsonify({'disponible': True})
    finally:
        conn.close()
