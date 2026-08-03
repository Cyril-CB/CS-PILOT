"""
Blueprint contrats_bp — Liste des contrats par mois / filtre.

Sert les requêtes de la barre de recherche intelligente : « contrats avril »,
« CDD en cours », « CDD se terminant en juillet », « contrats à échéance »,
« CDD signé ce mois ». Accès directeur / comptable.

Réutilise la fenêtre d'activité mensuelle de prepa_paie.py
(date_debut <= fin_mois ET (date_fin IS NULL OR date_fin >= debut_mois)) et la
route de téléchargement existante infos_salaries_bp.telecharger_contrat.
"""
import calendar
from flask import Blueprint, render_template, request, session, flash, redirect, url_for
from database import get_db
from utils import login_required, aujourd_hui, NOMS_MOIS

contrats_bp = Blueprint('contrats_bp', __name__)

PROFILS_AUTORISES = ['directeur', 'comptable']

# Filtres proposés (clé → libellé affiché)
FILTRES = [
    ('en_cours', 'En cours sur le mois'),
    ('echeance', 'CDD se terminant (échéance)'),
    ('signe', 'Débutant ce mois'),
]


@contrats_bp.route('/contrats')
@login_required
def liste_contrats():
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    today = aujourd_hui()
    annee_courante = today.year
    annees = [annee_courante + 1 - d for d in range(0, 6)]  # N+1 … N-4

    try:
        annee = int(request.args.get('annee') or annee_courante)
    except (TypeError, ValueError):
        annee = annee_courante
    if annee not in annees:
        annee = annee_courante

    try:
        mois = int(request.args.get('mois') or today.month)
    except (TypeError, ValueError):
        mois = today.month
    if mois < 1 or mois > 12:
        mois = today.month

    type_contrat = (request.args.get('type') or '').strip().upper() or None
    filtre = (request.args.get('filtre') or 'en_cours').strip()
    if filtre not in {f[0] for f in FILTRES}:
        filtre = 'en_cours'

    debut_mois = f"{annee:04d}-{mois:02d}-01"
    fin_mois = f"{annee:04d}-{mois:02d}-{calendar.monthrange(annee, mois)[1]:02d}"

    where = ["u.profil != 'prestataire'"]
    params = []

    if filtre == 'echeance':
        # Contrats se terminant dans le mois (CDD par défaut).
        where.append("c.date_fin IS NOT NULL AND c.date_fin BETWEEN ? AND ?")
        params += [debut_mois, fin_mois]
        if not type_contrat:
            type_contrat = 'CDD'
    elif filtre == 'signe':
        # Contrats débutant dans le mois (proxy « signé ce mois »).
        where.append("c.date_debut BETWEEN ? AND ?")
        params += [debut_mois, fin_mois]
    else:  # en_cours
        where.append("c.date_debut <= ? AND (c.date_fin IS NULL OR c.date_fin >= ?)")
        params += [fin_mois, debut_mois]

    if type_contrat:
        where.append("UPPER(c.type_contrat) = ?")
        params.append(type_contrat)

    conn = get_db()
    try:
        contrats = conn.execute(f'''
            SELECT c.id, c.type_contrat, c.date_debut, c.date_fin, c.forfait,
                   c.nbr_jours, c.temps_hebdo, c.fichier_path,
                   u.nom, u.prenom, COALESCE(s.nom, '') AS secteur_nom
            FROM contrats c
            JOIN users u ON c.user_id = u.id
            LEFT JOIN secteurs s ON u.secteur_id = s.id
            WHERE {" AND ".join(where)}
            ORDER BY u.nom, u.prenom, c.date_debut DESC
        ''', params).fetchall()

        types_dispo = [r['type_contrat'] for r in conn.execute(
            "SELECT DISTINCT type_contrat FROM contrats WHERE type_contrat IS NOT NULL "
            "AND type_contrat != '' ORDER BY type_contrat"
        ).fetchall()]
    finally:
        conn.close()

    return render_template(
        'contrats.html',
        contrats=contrats,
        annees=annees,
        annee_selected=annee,
        mois_selected=mois,
        noms_mois=NOMS_MOIS,
        type_selected=type_contrat or '',
        types_dispo=types_dispo,
        filtre_selected=filtre,
        filtres=FILTRES,
    )


@contrats_bp.route('/contrats/sans-contrat')
@login_required
def salaries_sans_contrat():
    """Salariés actifs qu'aucun contrat ne couvre aujourd'hui.

    Depuis que la saisie des heures exige un contrat, cette liste dit
    exactement qui est bloqué. Deux situations s'y côtoient, distinguées car
    elles n'appellent pas le même geste :

    - **aucun contrat au dossier** : le contrat n'a jamais été saisi. C'est
      l'anomalie à traiter en premier, le salarié ne peut rien saisir ;
    - **contrat échu** : le dernier contrat s'est terminé et n'a pas été
      renouvelé. Soit le renouvellement manque, soit c'est le salarié qui
      aurait dû être désactivé.

    Le cadrage est celui de l'effectif qui saisit ses heures — actifs, hors
    direction et prestataires — le même que la vue d'ensemble des validations.
    """
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    today = aujourd_hui().isoformat()

    conn = get_db()
    try:
        salaries = conn.execute(
            '''SELECT u.id, u.nom, u.prenom, u.profil,
                      COALESCE(s.nom, '') AS secteur_nom,
                      (SELECT MAX(c.date_fin) FROM contrats c
                       WHERE c.user_id = u.id) AS derniere_fin,
                      (SELECT COUNT(*) FROM contrats c
                       WHERE c.user_id = u.id) AS nb_contrats
               FROM users u
               LEFT JOIN secteurs s ON u.secteur_id = s.id
               WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
                 AND NOT EXISTS (
                     SELECT 1 FROM contrats c
                     WHERE c.user_id = u.id
                       AND c.date_debut <= ?
                       AND (c.date_fin IS NULL OR c.date_fin >= ?)
                 )
               ORDER BY nb_contrats, u.nom, u.prenom''',
            (today, today)
        ).fetchall()
    finally:
        conn.close()

    return render_template('contrats_sans_contrat.html',
                           salaries=salaries,
                           aujourd_hui=today)
