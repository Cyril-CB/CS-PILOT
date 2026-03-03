"""
Blueprint mon_equipe_bp.
Vue hebdomadaire des presences/absences de l'equipe (meme secteur + responsable).
Accessible par tous les salaries, responsables, comptables.
Inclut le suivi du taux d'encadrement pour les secteurs creche.
"""
import math
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify)
from datetime import datetime, timedelta
from database import get_db
from utils import (login_required, get_type_periode, get_planning_valide_a_date,
                   calculer_heures)

mon_equipe_bp = Blueprint('mon_equipe_bp', __name__)

JOURS_SEMAINE = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi']
JOURS_COURTS = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven']

# Tranches horaires pour l'affichage des presences (creches / taux d'encadrement)
# Bornes decalees d'1 min pour eviter le double-comptage aux frontieres
TRANCHES_HORAIRES = [
    ('08:00', '08:30', '08:00-08:30'),
    ('08:31', '09:00', '08:31-09:00'),
    ('09:01', '10:00', '09:01-10:00'),
    ('10:01', '12:00', '10:01-12:00'),
    ('12:01', '13:00', '12:01-13:00'),
    ('13:01', '14:30', '13:01-14:30'),
    ('14:31', '17:00', '14:31-17:00'),
    ('17:01', '18:00', '17:01-18:00'),
]

# Tranches horaires specifiques creche (par heure, pour le taux d'encadrement)
# Bornes decalees d'1 min a partir de la 2e tranche pour eviter le double-comptage
TRANCHES_CRECHE = [
    ('08:00', '09:00', '08h00-09h00'),
    ('09:01', '10:00', '09h01-10h00'),
    ('10:01', '11:00', '10h01-11h00'),
    ('11:01', '12:00', '11h01-12h00'),
    ('12:01', '13:00', '12h01-13h00'),
    ('13:01', '14:00', '13h01-14h00'),
    ('14:01', '15:00', '14h01-15h00'),
    ('15:01', '16:00', '15h01-16h00'),
    ('16:01', '17:00', '16h01-17h00'),
    ('17:01', '18:00', '17h01-18h00'),
]

# Ratio encadrement creche : 1 professionnel pour RATIO_ENFANTS enfants, minimum MIN_PRO
RATIO_ENFANTS = 6
MIN_PRO = 2


def _hhmm_to_minutes(hhmm):
    """Convertit 'HH:MM' en minutes depuis minuit."""
    parts = hhmm.split(':')
    return int(parts[0]) * 60 + int(parts[1])


def _plages_se_chevauchent(debut_a, fin_a, debut_b, fin_b):
    """Verifie si deux plages horaires (en minutes) se chevauchent."""
    return debut_a < fin_b and debut_b < fin_a


def _calculer_presences_horaires(grille):
    """Calcule le nombre de salaries presents par tranche horaire et par jour.

    Reutilise les donnees deja presentes dans la grille (pas de requete SQL).
    Retourne une liste de dicts : un par tranche horaire, chaque dict contenant
    le label et les comptes par jour (index 0-4).
    """
    tranches_minutes = []
    for t_debut, t_fin, label in TRANCHES_HORAIRES:
        tranches_minutes.append({
            'label': label,
            'debut': _hhmm_to_minutes(t_debut),
            'fin': _hhmm_to_minutes(t_fin),
            'comptes': [0] * 5,  # Lun-Ven
        })

    for row in grille:
        for jour_idx, jour in enumerate(row['jours']):
            # Ignorer les absences, feries, recup, vides
            if jour.get('type_saisie') in ('ferie', 'absence', 'recup'):
                continue

            # Collecter les plages de presence du salarie ce jour
            plages = []
            if jour.get('matin') and jour['matin'][0] and jour['matin'][1]:
                try:
                    plages.append((
                        _hhmm_to_minutes(jour['matin'][0]),
                        _hhmm_to_minutes(jour['matin'][1]),
                    ))
                except (ValueError, IndexError):
                    pass
            if jour.get('aprem') and jour['aprem'][0] and jour['aprem'][1]:
                try:
                    plages.append((
                        _hhmm_to_minutes(jour['aprem'][0]),
                        _hhmm_to_minutes(jour['aprem'][1]),
                    ))
                except (ValueError, IndexError):
                    pass

            if not plages:
                continue

            # Verifier chaque tranche
            for tranche in tranches_minutes:
                for p_debut, p_fin in plages:
                    if _plages_se_chevauchent(p_debut, p_fin,
                                              tranche['debut'], tranche['fin']):
                        tranche['comptes'][jour_idx] += 1
                        break  # Compter 1 seule fois par salarie par tranche

    return tranches_minutes


def _calculer_presences_creche(grille):
    """Calcule les presences par tranche horaire pour les creches (horaire).

    Exclut les responsables du comptage (ils ne comptent pas dans le ratio).
    Retourne une liste de dicts avec label, comptes[5], et requis (nb pro requis).
    """
    tranches_minutes = []
    for t_debut, t_fin, label in TRANCHES_CRECHE:
        tranches_minutes.append({
            'label': label,
            'debut': _hhmm_to_minutes(t_debut),
            'fin': _hhmm_to_minutes(t_fin),
            'comptes': [0] * 5,
        })

    for row in grille:
        # Exclure la responsable du comptage
        if row.get('profil') == 'responsable':
            continue

        for jour_idx, jour in enumerate(row['jours']):
            if jour.get('type_saisie') in ('ferie', 'absence', 'recup'):
                continue

            plages = []
            if jour.get('matin') and jour['matin'][0] and jour['matin'][1]:
                try:
                    plages.append((
                        _hhmm_to_minutes(jour['matin'][0]),
                        _hhmm_to_minutes(jour['matin'][1]),
                    ))
                except (ValueError, IndexError):
                    pass
            if jour.get('aprem') and jour['aprem'][0] and jour['aprem'][1]:
                try:
                    plages.append((
                        _hhmm_to_minutes(jour['aprem'][0]),
                        _hhmm_to_minutes(jour['aprem'][1]),
                    ))
                except (ValueError, IndexError):
                    pass

            if not plages:
                continue

            for tranche in tranches_minutes:
                for p_debut, p_fin in plages:
                    if _plages_se_chevauchent(p_debut, p_fin,
                                              tranche['debut'], tranche['fin']):
                        tranche['comptes'][jour_idx] += 1
                        break

    return tranches_minutes


def _calculer_presence_responsable(grille):
    """Calcule la presence du responsable par tranche horaire et par jour.

    Retourne un dict {label_tranche: [bool, bool, bool, bool, bool]} (Lun-Ven)
    indiquant si le responsable est present sur chaque creneau chaque jour.
    """
    result = {}
    for t_debut, t_fin, label in TRANCHES_CRECHE:
        result[label] = [0] * 5

    for row in grille:
        if row.get('profil') != 'responsable':
            continue

        for jour_idx, jour in enumerate(row['jours']):
            if jour.get('type_saisie') in ('ferie', 'absence', 'recup'):
                continue

            plages = []
            if jour.get('matin') and jour['matin'][0] and jour['matin'][1]:
                try:
                    plages.append((
                        _hhmm_to_minutes(jour['matin'][0]),
                        _hhmm_to_minutes(jour['matin'][1]),
                    ))
                except (ValueError, IndexError):
                    pass
            if jour.get('aprem') and jour['aprem'][0] and jour['aprem'][1]:
                try:
                    plages.append((
                        _hhmm_to_minutes(jour['aprem'][0]),
                        _hhmm_to_minutes(jour['aprem'][1]),
                    ))
                except (ValueError, IndexError):
                    pass

            if not plages:
                continue

            for t_debut, t_fin, label in TRANCHES_CRECHE:
                d = _hhmm_to_minutes(t_debut)
                f = _hhmm_to_minutes(t_fin)
                for p_debut, p_fin in plages:
                    if _plages_se_chevauchent(p_debut, p_fin, d, f):
                        result[label][jour_idx] = 1
                        break

    return result


def _calculer_requis_creche(nb_enfants):
    """Calcule le nombre de professionnels requis pour un nombre d'enfants.

    Regle : 1 pro pour 6 enfants, arrondi a l'unite superieure, minimum 2.
    La responsable ne compte pas dans les professionnels.
    """
    if nb_enfants <= 0:
        return 0
    return max(MIN_PRO, math.ceil(nb_enfants / RATIO_ENFANTS))


def _lundi_de_la_semaine(date_ref):
    """Retourne le lundi de la semaine contenant date_ref."""
    return date_ref - timedelta(days=date_ref.weekday())


def _peut_voir_equipe():
    """Tous les profils sauf prestataire et directeur."""
    return session.get('profil') in ['salarie', 'responsable', 'comptable']


def _get_equipe(conn, user_id):
    """Retourne les membres de l'equipe ayant un contrat en cours :
    meme secteur + responsable du secteur."""
    today_str = datetime.now().strftime('%Y-%m-%d')

    user = conn.execute(
        'SELECT secteur_id FROM users WHERE id = %s', (user_id,)
    ).fetchone()

    if not user or not user['secteur_id']:
        # Pas de secteur : retourner juste l'utilisateur lui-meme
        return conn.execute('''
            SELECT u.id, u.nom, u.prenom, u.profil,
                   COALESCE(s.nom, '') AS secteur_nom
            FROM users u
            LEFT JOIN secteurs s ON u.secteur_id = s.id
            WHERE u.id = %s AND u.actif = 1
              AND EXISTS (
                  SELECT 1 FROM contrats c
                  WHERE c.user_id = u.id
                    AND c.date_debut <= %s
                    AND (c.date_fin IS NULL OR c.date_fin >= %s)
              )
        ''', (user_id, today_str, today_str)).fetchall()

    secteur_id = user['secteur_id']

    # Salaries du meme secteur avec un contrat en cours
    membres = conn.execute('''
        SELECT u.id, u.nom, u.prenom, u.profil,
               COALESCE(s.nom, '') AS secteur_nom
        FROM users u
        LEFT JOIN secteurs s ON u.secteur_id = s.id
        WHERE u.actif = 1
        AND u.profil != 'prestataire'
        AND u.secteur_id = %s
        AND EXISTS (
            SELECT 1 FROM contrats c
            WHERE c.user_id = u.id
              AND c.date_debut <= %s
              AND (c.date_fin IS NULL OR c.date_fin >= %s)
        )
        ORDER BY
            CASE u.profil WHEN 'responsable' THEN 0 ELSE 1 END,
            u.nom, u.prenom
    ''', (secteur_id, today_str, today_str)).fetchall()

    # Ajouter le responsable du pole s'il n'est pas dans le meme secteur
    # (certains responsables sont dans un autre secteur mais gèrent celui-ci)
    ids_existants = {m['id'] for m in membres}

    # Chercher les responsables qui supervisent des salaries de ce secteur
    responsables_externes = conn.execute('''
        SELECT DISTINCT r.id, r.nom, r.prenom, r.profil,
               COALESCE(s.nom, '') AS secteur_nom
        FROM users u
        JOIN users r ON u.responsable_id = r.id
        LEFT JOIN secteurs s ON r.secteur_id = s.id
        WHERE u.secteur_id = %s AND r.actif = 1 AND r.id NOT IN ({})
          AND EXISTS (
              SELECT 1 FROM contrats c
              WHERE c.user_id = r.id
                AND c.date_debut <= %s
                AND (c.date_fin IS NULL OR c.date_fin >= %s)
          )
    '''.format(','.join('%s' for _ in ids_existants) if ids_existants else '0'),
        (secteur_id, *ids_existants, today_str, today_str) if ids_existants else (secteur_id, today_str, today_str)
    ).fetchall()

    return list(membres) + list(responsables_externes)


def _get_jours_feries(conn, date_debut_str, date_fin_str):
    """Retourne l'ensemble des dates feriees dans la plage."""
    rows = conn.execute('''
        SELECT date FROM jours_feries
        WHERE date >= %s AND date <= %s
    ''', (date_debut_str, date_fin_str)).fetchall()
    return {r['date'] for r in rows}


def _construire_grille(conn, membres, lundi):
    """Construit la grille semaine pour chaque membre."""
    vendredi = lundi + timedelta(days=4)
    lundi_str = lundi.strftime('%Y-%m-%d')
    vendredi_str = vendredi.strftime('%Y-%m-%d')

    jours_feries = _get_jours_feries(conn, lundi_str, vendredi_str)

    # Recuperer toutes les heures reelles de la semaine pour tous les membres
    ids = [m['id'] for m in membres]
    if not ids:
        return []

    placeholders = ','.join('%s' for _ in ids)
    heures_rows = conn.execute(f'''
        SELECT user_id, date, heure_debut_matin, heure_fin_matin,
               heure_debut_aprem, heure_fin_aprem,
               type_saisie, declaration_conforme, commentaire
        FROM heures_reelles
        WHERE user_id IN ({placeholders})
        AND date >= %s AND date <= %s
    ''', (*ids, lundi_str, vendredi_str)).fetchall()

    # Indexer par (user_id, date)
    heures_map = {}
    for h in heures_rows:
        heures_map[(h['user_id'], h['date'])] = dict(h)

    # Recuperer les absences qui chevauchent la semaine
    absences_rows = conn.execute(f'''
        SELECT user_id, motif, date_debut, date_fin, commentaire
        FROM absences
        WHERE user_id IN ({placeholders})
        AND date_debut <= %s AND date_fin >= %s
    ''', (*ids, vendredi_str, lundi_str)).fetchall()

    # Indexer par user_id -> liste
    absences_map = {}
    for a in absences_rows:
        uid = a['user_id']
        if uid not in absences_map:
            absences_map[uid] = []
        absences_map[uid].append(dict(a))

    grille = []
    for membre in membres:
        uid = membre['id']
        jours = []

        for i in range(5):  # Lun -> Ven
            jour_date = lundi + timedelta(days=i)
            date_str = jour_date.strftime('%Y-%m-%d')
            jour_info = {
                'date': date_str,
                'jour_court': JOURS_COURTS[i],
                'jour_num': jour_date.day,
                'ferie': date_str in jours_feries,
                'absence': None,
                'matin': None,
                'aprem': None,
                'type_saisie': None,
                'commentaire': None,
            }

            if jour_info['ferie']:
                jour_info['type_saisie'] = 'ferie'
                jours.append(jour_info)
                continue

            # Verifier absence
            absence_jour = None
            for ab in absences_map.get(uid, []):
                if ab['date_debut'] <= date_str <= ab['date_fin']:
                    absence_jour = ab
                    break

            if absence_jour:
                jour_info['absence'] = absence_jour['motif']
                jour_info['type_saisie'] = 'absence'
                jour_info['commentaire'] = absence_jour.get('commentaire')
                jours.append(jour_info)
                continue

            # Chercher les heures reelles
            hr = heures_map.get((uid, date_str))
            if hr:
                jour_info['type_saisie'] = hr['type_saisie']
                jour_info['commentaire'] = hr.get('commentaire')

                if hr['type_saisie'] == 'absence':
                    # Absence reportee sur le calendrier
                    motif = (hr.get('commentaire') or '').replace('Absence #', '').split(' - ', 1)
                    jour_info['absence'] = motif[1] if len(motif) > 1 else 'Absence'
                    jour_info['type_saisie'] = 'absence'

                elif hr['type_saisie'] == 'recup_journee':
                    jour_info['type_saisie'] = 'recup'

                elif hr['declaration_conforme']:
                    # Utiliser le planning theorique
                    type_p = get_type_periode(date_str)
                    planning = get_planning_valide_a_date(uid, type_p, date_str)
                    if planning:
                        jour_nom = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi'][i]
                        jour_info['matin'] = (
                            planning[f'{jour_nom}_matin_debut'],
                            planning[f'{jour_nom}_matin_fin']
                        )
                        jour_info['aprem'] = (
                            planning[f'{jour_nom}_aprem_debut'],
                            planning[f'{jour_nom}_aprem_fin']
                        )
                    jour_info['type_saisie'] = 'conforme'

                else:
                    # Heures saisies manuellement
                    if hr['heure_debut_matin'] or hr['heure_fin_matin']:
                        jour_info['matin'] = (hr['heure_debut_matin'], hr['heure_fin_matin'])
                    if hr['heure_debut_aprem'] or hr['heure_fin_aprem']:
                        jour_info['aprem'] = (hr['heure_debut_aprem'], hr['heure_fin_aprem'])

            else:
                # Pas de saisie : afficher le planning theorique en grise
                type_p = get_type_periode(date_str)
                planning = get_planning_valide_a_date(uid, type_p, date_str)
                if planning:
                    jour_nom = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi'][i]
                    md = planning[f'{jour_nom}_matin_debut']
                    mf = planning[f'{jour_nom}_matin_fin']
                    ad = planning[f'{jour_nom}_aprem_debut']
                    af = planning[f'{jour_nom}_aprem_fin']
                    if md or mf:
                        jour_info['matin'] = (md, mf)
                    if ad or af:
                        jour_info['aprem'] = (ad, af)
                jour_info['type_saisie'] = 'theorique'

            jours.append(jour_info)

        grille.append({
            'id': uid,
            'nom': membre['nom'],
            'prenom': membre['prenom'],
            'profil': membre['profil'],
            'secteur': membre['secteur_nom'],
            'jours': jours,
        })

    return grille


@mon_equipe_bp.route('/mon_equipe')
@login_required
def mon_equipe():
    """Page principale : vue semaine de l'equipe."""
    if not _peut_voir_equipe():
        flash("Acces non autorise.", 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    today = datetime.now().date()
    lundi_courant = _lundi_de_la_semaine(today)
    lundi_suivant = lundi_courant + timedelta(weeks=1)

    # Parametre semaine : 0 = courante, 1 = suivante
    semaine_offset = request.args.get('semaine', 0, type=int)
    if semaine_offset < 0:
        semaine_offset = 0
    if semaine_offset > 1:
        semaine_offset = 1

    lundi = lundi_courant + timedelta(weeks=semaine_offset)
    vendredi = lundi + timedelta(days=4)

    conn = get_db()
    membres = _get_equipe(conn, session['user_id'])
    grille = _construire_grille(conn, membres, lundi)

    # Nom et type du secteur
    user_row = conn.execute('''
        SELECT u.secteur_id,
               COALESCE(s.nom, '') AS secteur_nom,
               COALESCE(s.type_secteur, '') AS type_secteur
        FROM users u
        LEFT JOIN secteurs s ON u.secteur_id = s.id
        WHERE u.id = %s
    ''', (session['user_id'],)).fetchone()
    secteur_nom = user_row['secteur_nom'] if user_row else ''
    type_secteur = user_row['type_secteur'] if user_row else ''
    secteur_id = user_row['secteur_id'] if user_row else None
    is_creche = type_secteur == 'creche'

    # Presences par tranche horaire
    if is_creche:
        presences_horaires = _calculer_presences_creche(grille)
        resp_presence = _calculer_presence_responsable(grille)

        # Charger la frequentation creche (avec responsable_terrain)
        freq_rows = conn.execute('''
            SELECT tranche, nb_enfants, COALESCE(responsable_terrain, 0) AS responsable_terrain
            FROM frequentation_creche
            WHERE secteur_id = %s
        ''', (secteur_id,)).fetchall()
        freq_map = {r['tranche']: r['nb_enfants'] for r in freq_rows}
        terrain_map = {r['tranche']: bool(r['responsable_terrain']) for r in freq_rows}

        # Enrichir les tranches avec nb_enfants, requis et responsable_terrain
        for tranche in presences_horaires:
            nb_enfants = freq_map.get(tranche['label'], 0)
            resp_terrain = terrain_map.get(tranche['label'], False)
            tranche['nb_enfants'] = nb_enfants
            tranche['responsable_terrain'] = resp_terrain
            tranche['requis'] = _calculer_requis_creche(nb_enfants)

            # Si le responsable est sur le terrain, l'ajouter au comptage
            # (uniquement les jours ou il/elle est effectivement present(e))
            if resp_terrain and tranche['label'] in resp_presence:
                for j in range(5):
                    tranche['comptes'][j] += resp_presence[tranche['label']][j]

        # Compter les membres hors responsable
        nb_pro = sum(1 for m in membres if m['profil'] != 'responsable')
    else:
        presences_horaires = _calculer_presences_horaires(grille)
        nb_pro = len(membres)

    conn.close()

    # Construire les en-tetes de jours
    jours_header = []
    for i in range(5):
        d = lundi + timedelta(days=i)
        jours_header.append({
            'nom': JOURS_SEMAINE[i],
            'court': JOURS_COURTS[i],
            'date': d.strftime('%d/%m'),
            'date_full': d.strftime('%Y-%m-%d'),
            'is_today': d == today,
        })

    return render_template('mon_equipe.html',
                           grille=grille,
                           jours_header=jours_header,
                           lundi=lundi,
                           vendredi=vendredi,
                           semaine_offset=semaine_offset,
                           secteur_nom=secteur_nom,
                           presences_horaires=presences_horaires,
                           nb_membres=len(membres),
                           nb_pro=nb_pro,
                           is_creche=is_creche,
                           secteur_id=secteur_id,
                           today=today)


@mon_equipe_bp.route('/api/frequentation_creche/save', methods=['POST'])
@login_required
def api_save_frequentation():
    """Sauvegarde la frequentation moyenne par tranche horaire (responsable creche)."""
    if session.get('profil') != 'responsable':
        return jsonify({'error': 'Acces non autorise'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Donnees manquantes'}), 400

    secteur_id = data.get('secteur_id')
    tranches = data.get('tranches', [])

    if not secteur_id:
        return jsonify({'error': 'Secteur non specifie'}), 400

    conn = get_db()

    # Verifier que le responsable appartient bien a ce secteur creche
    user = conn.execute('''
        SELECT u.secteur_id, s.type_secteur
        FROM users u
        LEFT JOIN secteurs s ON u.secteur_id = s.id
        WHERE u.id = %s
    ''', (session['user_id'],)).fetchone()

    if not user or str(user['secteur_id']) != str(secteur_id) or user['type_secteur'] != 'creche':
        conn.close()
        return jsonify({'error': 'Acces non autorise a ce secteur'}), 403

    try:
        for t in tranches:
            tranche_label = t.get('tranche', '')
            nb_enfants = float(t.get('nb_enfants', 0))
            if nb_enfants < 0:
                nb_enfants = 0
            resp_terrain = 1 if t.get('responsable_terrain') else 0

            conn.execute('''
                INSERT INTO frequentation_creche (secteur_id, tranche, nb_enfants, responsable_terrain, updated_by, updated_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT(secteur_id, tranche)
                DO UPDATE SET nb_enfants = excluded.nb_enfants,
                              responsable_terrain = excluded.responsable_terrain,
                              updated_by = excluded.updated_by,
                              updated_at = excluded.updated_at
            ''', (secteur_id, tranche_label, nb_enfants, resp_terrain, session['user_id']))

        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Frequentation sauvegardee'})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500
