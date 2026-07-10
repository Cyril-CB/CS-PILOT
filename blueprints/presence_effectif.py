"""
Blueprint presence_effectif_bp.

Page « Présence effectif » (direction / comptable) : tableau mensuel des
salariés en contrat sur la période — une colonne par jour du mois, un statut
par case (présent, arrêt maladie, congés, récupération, autre absence) avec
un code couleur bien visible. Les motifs non regroupés tombent dans « autre ».
"""
from calendar import monthrange
from datetime import date

from flask import (Blueprint, flash, redirect, render_template, request,
                   session, url_for)

from database import get_db
from utils import login_required, NOMS_MOIS

presence_effectif_bp = Blueprint('presence_effectif_bp', __name__)

# Catégorie d'un motif d'absence ; tout motif non listé tombe dans « autre »
# (congé parental, jour enfant malade, accident du travail, évènement
# familial, sans solde, mi-temps thérapeutique…).
MOTIF_VERS_CATEGORIE = {
    'Arrêt maladie': 'maladie',
    'Congé payé': 'conges',
    'Congé conventionnel': 'conges',
    'Forfait jour': 'conges',
}

# Journées du calendrier forfait jour (direction) → catégorie. La direction
# peut poser des journées directement dans son calendrier, sans fiche
# d'absence : on lit donc aussi presence_forfait_jour.
FORFAIT_VERS_CATEGORIE = {
    'conge_paye': 'conges',
    'conge_conv': 'conges',
    'forfait_jour': 'conges',
    'maladie': 'maladie',
}

# En cas de chevauchement de deux absences sur un même jour, la catégorie la
# plus « forte » l'emporte (plus petit = plus fort).
_PRIORITE = {'maladie': 0, 'conges': 1, 'autre': 2, 'recup': 3}

_JOUR_COURT = ('L', 'M', 'M', 'J', 'V', 'S', 'D')

_LIBELLES = {
    'present': 'Présent',
    'maladie': 'Arrêt maladie',
    'conges': 'Congés',
    'recup': 'Récupération',
    'autre': 'Autre absence',
    'weekend': 'Week-end',
    'ferie': 'Jour férié',
    'hors': 'Hors contrat',
}


def _iso(annee, mois, jour):
    return f"{annee:04d}-{mois:02d}-{jour:02d}"


def _sous_contrat(fenetres, jour_iso):
    """Vrai si le jour (ISO) est couvert par au moins une fenêtre de contrat."""
    for debut, fin in fenetres:
        if debut <= jour_iso and (fin is None or jour_iso <= fin):
            return True
    return False


def _construire_matrice(conn, annee, mois, nb_jours):
    """Construit la matrice salariés × jours du mois.

    Retourne (jours, salaries, absents_par_jour) :
    - jours : [{num, lettre, is_weekend, is_ferie, ferie_libelle, is_today}]
    - salaries : [{nom, prenom, cells: [{cat, title}], compteurs: {...}}]
    - absents_par_jour : nombre d'absents (maladie+congés+récup+autre) par jour.
    """
    debut = _iso(annee, mois, 1)
    fin = _iso(annee, mois, nb_jours)

    # Salariés en contrat sur la période (contrats chevauchant le mois),
    # classés par secteur (les sans-secteur en dernier). Les contrats clos
    # restent visibles même si le compte a été désactivé (départ en cours
    # d'année) ; un contrat ouvert exige un compte actif.
    rows = conn.execute('''
        SELECT u.id, u.nom, u.prenom, u.profil, c.date_debut, c.date_fin,
               sec.nom AS secteur_nom
        FROM users u
        LEFT JOIN secteurs sec ON sec.id = u.secteur_id
        JOIN contrats c ON c.user_id = u.id
        WHERE u.profil != 'prestataire'
          AND c.date_debut <= ?
          AND (c.date_fin IS NULL OR c.date_fin >= ?)
          AND (u.actif = 1 OR c.date_fin IS NOT NULL)
        ORDER BY (sec.nom IS NULL), sec.nom COLLATE NOCASE,
                 u.nom COLLATE NOCASE, u.prenom COLLATE NOCASE
    ''', (fin, debut)).fetchall()

    salaries_map = {}
    ordre = []
    for r in rows:
        if r['id'] not in salaries_map:
            salaries_map[r['id']] = {
                'nom': r['nom'], 'prenom': r['prenom'], 'profil': r['profil'],
                'secteur': r['secteur_nom'] or 'Sans secteur',
                'fenetres': [],
            }
            ordre.append(r['id'])
        salaries_map[r['id']]['fenetres'].append((r['date_debut'], r['date_fin']))

    # Statut par (user, jour) : {jour_iso: (categorie, libelle)}
    statuts = {uid: {} for uid in salaries_map}

    def poser(uid, jour_iso, categorie, libelle):
        if uid not in statuts:
            return
        actuel = statuts[uid].get(jour_iso)
        if actuel and _PRIORITE.get(actuel[0], 9) <= _PRIORITE.get(categorie, 9):
            return
        statuts[uid][jour_iso] = (categorie, libelle)

    # Absences chevauchant le mois : catégorie selon le motif.
    for a in conn.execute('''
        SELECT user_id, motif, date_debut, date_fin FROM absences
        WHERE date_debut <= ? AND date_fin >= ?
    ''', (fin, debut)).fetchall():
        categorie = MOTIF_VERS_CATEGORIE.get(a['motif'], 'autre')
        for jour in range(1, nb_jours + 1):
            jour_iso = _iso(annee, mois, jour)
            if a['date_debut'] <= jour_iso <= a['date_fin']:
                poser(a['user_id'], jour_iso, categorie, a['motif'])

    # Journées de récupération validées (matérialisées dans heures_reelles).
    for r in conn.execute('''
        SELECT user_id, date FROM heures_reelles
        WHERE date BETWEEN ? AND ? AND type_saisie = 'recup_journee'
    ''', (debut, fin)).fetchall():
        poser(r['user_id'], r['date'], 'recup', 'Récupération')

    # Calendrier forfait jour (direction) : journées posées sans fiche
    # d'absence (le type 'travaille' reste un jour présent).
    for f in conn.execute('''
        SELECT user_id, date, type_journee FROM presence_forfait_jour
        WHERE date BETWEEN ? AND ?
    ''', (debut, fin)).fetchall():
        categorie = FORFAIT_VERS_CATEGORIE.get(f['type_journee'])
        if categorie is None and f['type_journee'] != 'travaille':
            categorie = 'autre'
        if categorie:
            poser(f['user_id'], f['date'], categorie,
                  f"Forfait jour : {f['type_journee'].replace('_', ' ')}")

    feries = {r['date']: r['libelle'] for r in conn.execute(
        'SELECT date, libelle FROM jours_feries WHERE date BETWEEN ? AND ?',
        (debut, fin)).fetchall()}

    aujourd_hui = date.today().isoformat()
    jours = []
    for jour in range(1, nb_jours + 1):
        jour_iso = _iso(annee, mois, jour)
        semaine = date(annee, mois, jour).weekday()
        jours.append({
            'num': jour,
            'iso': jour_iso,
            'lettre': _JOUR_COURT[semaine],
            'is_weekend': semaine >= 5,
            'is_ferie': jour_iso in feries,
            'ferie_libelle': feries.get(jour_iso, ''),
            'is_today': jour_iso == aujourd_hui,
        })

    salaries = []
    absents_par_jour = [0] * nb_jours
    for uid in ordre:
        s = salaries_map[uid]
        cells = []
        compteurs = {'maladie': 0, 'conges': 0, 'recup': 0, 'autre': 0}
        for j in jours:
            jour_iso = j['iso']
            if not _sous_contrat(s['fenetres'], jour_iso):
                cat, libelle = 'hors', _LIBELLES['hors']
            elif j['is_weekend']:
                cat, libelle = 'weekend', _LIBELLES['weekend']
            elif j['is_ferie']:
                cat, libelle = 'ferie', f"Férié : {j['ferie_libelle']}"
            else:
                cat, libelle = statuts[uid].get(jour_iso, ('present', _LIBELLES['present']))
                if cat in compteurs:
                    compteurs[cat] += 1
                    absents_par_jour[j['num'] - 1] += 1
            cells.append({'cat': cat, 'title': f"{jour_iso} — {libelle}"})
        salaries.append({
            'nom': s['nom'], 'prenom': s['prenom'], 'secteur': s['secteur'],
            'cells': cells, 'compteurs': compteurs,
        })

    return jours, salaries, absents_par_jour


@presence_effectif_bp.route('/presence-effectif')
@login_required
def presence_effectif():
    """Tableau mensuel de présence de l'effectif (direction / comptable)."""
    if session.get('profil') not in ('directeur', 'comptable'):
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    aujourd_hui = date.today()
    mois = request.args.get('mois', type=int) or aujourd_hui.month
    annee = request.args.get('annee', type=int) or aujourd_hui.year
    mois = min(max(mois, 1), 12)
    annee = min(max(annee, 2000), 2100)
    nb_jours = monthrange(annee, mois)[1]

    conn = get_db()
    try:
        jours, salaries, absents_par_jour = _construire_matrice(conn, annee, mois, nb_jours)
    finally:
        conn.close()

    prec_annee, prec_mois = (annee - 1, 12) if mois == 1 else (annee, mois - 1)
    suiv_annee, suiv_mois = (annee + 1, 1) if mois == 12 else (annee, mois + 1)

    return render_template(
        'presence_effectif.html',
        annee=annee, mois=mois, mois_nom=NOMS_MOIS[mois],
        annees=list(range(aujourd_hui.year - 3, aujourd_hui.year + 2)),
        noms_mois=NOMS_MOIS,
        jours=jours, salaries=salaries, absents_par_jour=absents_par_jour,
        prec_mois=prec_mois, prec_annee=prec_annee,
        suiv_mois=suiv_mois, suiv_annee=suiv_annee,
    )
