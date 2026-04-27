"""
Fonctions utilitaires partagées entre tous les blueprints.
"""
import logging
import re
from flask import session, flash, redirect, url_for
from functools import wraps
from datetime import datetime, timedelta
from database import get_db

logger = logging.getLogger(__name__)


# ── Chiffrement / déchiffrement (clés API, etc.) ──

def _get_fernet():
    """Retourne un objet Fernet basé sur la secret_key de l'app."""
    from flask import current_app
    from cryptography.fernet import Fernet
    import base64, hashlib
    key = hashlib.sha256(current_app.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_value(plaintext):
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(encrypted):
    return _get_fernet().decrypt(encrypted.encode()).decode()


def get_setting(key):
    """Récupère et déchiffre une valeur depuis app_settings."""
    conn = get_db()
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    if row:
        try:
            return decrypt_value(row['value'])
        except Exception:
            return None
    return None


def save_setting(key, value):
    """Chiffre et stocke une valeur dans app_settings."""
    encrypted = encrypt_value(value)
    conn = get_db()
    existing = conn.execute("SELECT id FROM app_settings WHERE key = ?", (key,)).fetchone()
    if existing:
        conn.execute("UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?", (encrypted, key))
    else:
        conn.execute("INSERT INTO app_settings (key, value) VALUES (?, ?)", (key, encrypted))
    conn.commit()
    conn.close()


def delete_setting(key):
    """Supprime une valeur de app_settings."""
    conn = get_db()
    conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
    conn.commit()
    conn.close()


# Constante partagée
NOMS_MOIS = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
             'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']


def calcul_etp(type_contrat, temps_hebdo):
    """Calcule l'ETP d'un salarié selon son type de contrat."""
    if type_contrat == 'CEE':
        return 0.12
    if temps_hebdo and temps_hebdo > 0:
        return round(temps_hebdo / 35.0, 4)
    return 1.0


def validate_password_strength(password):
    """Valide la complexité d'un mot de passe.

    Retourne une liste d'erreurs (vide si le mot de passe est conforme).
    Règles : 8 caractères min, 1 majuscule, 1 minuscule, 1 caractère spécial.
    Un mot de passe absent est considéré comme invalide.
    """
    errors = []
    if password is None:
        password = ''

    if len(password) < 8:
        errors.append('Le mot de passe doit contenir au moins 8 caractères')
    if not re.search(r'[A-Z]', password):
        errors.append('Le mot de passe doit contenir au moins une majuscule')
    if not re.search(r'[a-z]', password):
        errors.append('Le mot de passe doit contenir au moins une minuscule')
    if not re.search(r'[^A-Za-z0-9]', password):
        errors.append('Le mot de passe doit contenir au moins un caractère spécial')

    return errors


def login_required(f):
    """Décorateur pour protéger les routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Veuillez vous connecter', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def get_user_info(user_id):
    """Récupérer les informations d'un utilisateur"""
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return user


def calculer_heures(debut, fin):
    """Calculer la durée entre deux horaires"""
    if not debut or not fin:
        return 0
    try:
        fmt = '%H:%M'
        debut_dt = datetime.strptime(debut, fmt)
        fin_dt = datetime.strptime(fin, fmt)
        if fin_dt < debut_dt:
            fin_dt += timedelta(days=1)
        duree = (fin_dt - debut_dt).total_seconds() / 3600
        return round(duree, 2)
    except ValueError:
        logger.warning("Format d'horaire invalide: %s - %s", debut, fin)
        return 0


def get_heures_theoriques_jour(planning, jour_semaine):
    """Récupère les heures théoriques pour un jour de la semaine (0=lundi, 4=vendredi)"""
    if not planning or jour_semaine < 0 or jour_semaine > 4:
        return 0

    jours = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi']
    jour_nom = jours[jour_semaine]

    matin_debut = planning[f'{jour_nom}_matin_debut']
    matin_fin = planning[f'{jour_nom}_matin_fin']
    aprem_debut = planning[f'{jour_nom}_aprem_debut']
    aprem_fin = planning[f'{jour_nom}_aprem_fin']

    heures_matin = calculer_heures(matin_debut, matin_fin)
    heures_aprem = calculer_heures(aprem_debut, aprem_fin)

    return heures_matin + heures_aprem


def get_type_periode(date_str):
    """Déterminer si on est en période scolaire ou vacances selon les périodes définies"""
    conn = get_db()

    periode = conn.execute('''
        SELECT * FROM periodes_vacances
        WHERE ? >= date_debut AND ? <= date_fin
    ''', (date_str, date_str)).fetchone()

    conn.close()

    if periode:
        return 'vacances'
    else:
        return 'periode_scolaire'


def get_semaine_alternance(user_id, date_str):
    """Détermine si on est en semaine 1 ou semaine 2 pour un salarié en alternance"""
    conn = get_db()

    ref = conn.execute('''
        SELECT date_reference FROM alternance_reference
        WHERE user_id = ? AND date_debut_validite <= ?
        ORDER BY date_debut_validite DESC
        LIMIT 1
    ''', (user_id, date_str)).fetchone()

    conn.close()

    if not ref:
        return 'fixe'

    date_ref = datetime.strptime(ref['date_reference'], '%Y-%m-%d')
    date_actuelle = datetime.strptime(date_str, '%Y-%m-%d')

    delta_jours = (date_actuelle - date_ref).days
    semaines_ecoulees = delta_jours // 7

    if semaines_ecoulees % 2 == 0:
        return 'semaine_1'
    else:
        return 'semaine_2'


def get_planning_valide_a_date(user_id, type_periode, date_str):
    """Récupère le planning théorique valide à une date donnée (gère historisation ET alternance)"""
    conn = get_db()

    semaine_type = get_semaine_alternance(user_id, date_str)

    if semaine_type == 'fixe':
        planning = conn.execute('''
            SELECT * FROM planning_theorique
            WHERE user_id = ? 
            AND type_periode = ?
            AND (type_alternance IS NULL OR type_alternance = 'fixe')
            AND date_debut_validite <= ?
            ORDER BY date_debut_validite DESC
            LIMIT 1
        ''', (user_id, type_periode, date_str)).fetchone()
    else:
        planning = conn.execute('''
            SELECT * FROM planning_theorique
            WHERE user_id = ? 
            AND type_periode = ?
            AND type_alternance = ?
            AND date_debut_validite <= ?
            ORDER BY date_debut_validite DESC
            LIMIT 1
        ''', (user_id, type_periode, semaine_type, date_str)).fetchone()

    conn.close()
    return planning


def calculer_jours_ouvres(date_debut_str, date_fin_str):
    """Calcule le nombre de jours ouvrés entre deux dates (exclut weekends ET jours fériés)"""
    date_debut = datetime.strptime(date_debut_str, '%Y-%m-%d')
    date_fin = datetime.strptime(date_fin_str, '%Y-%m-%d')

    if date_debut > date_fin:
        return 0

    # Récupérer tous les jours fériés entre les deux dates
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
        # Compter uniquement les jours ouvrés (lundi-vendredi) qui ne sont pas fériés
        if jour_actuel.weekday() < 5 and date_str not in jours_feries:
            nb_jours += 1
        jour_actuel += timedelta(days=1)

    return nb_jours


def calculer_stats_forfait_jour(user_id, annee):
    """Calcule les statistiques forfait jour pour une année"""
    conn = get_db()

    JOURS_CONTRAT = 210
    JOURS_CONGES_PAYES = 25
    JOURS_CONGES_CONV = 8

    jours_feries = conn.execute('''
        SELECT COUNT(*) as nb FROM jours_feries 
        WHERE annee = ? AND strftime('%w', date) NOT IN ('0', '6')
    ''', (annee,)).fetchone()
    nb_jours_feries = jours_feries['nb'] if jours_feries else 0

    date_debut = datetime(annee, 1, 1)
    date_fin = datetime(annee, 12, 31)
    nb_jours_ouvrables = calculer_jours_ouvres(date_debut.strftime('%Y-%m-%d'), date_fin.strftime('%Y-%m-%d'))

    jours_repos_forfait = nb_jours_ouvrables - nb_jours_feries - JOURS_CONGES_PAYES - JOURS_CONGES_CONV - JOURS_CONTRAT

    presences = conn.execute('''
        SELECT type_journee, COUNT(*) as nb
        FROM presence_forfait_jour
        WHERE user_id = ? AND strftime('%Y', date) = ?
        GROUP BY type_journee
    ''', (user_id, str(annee))).fetchall()

    stats = {
        'travaille': 0,
        'conge_paye': 0,
        'conge_conv': 0,
        'repos_forfait': 0,
        'ferie': 0,
        'maladie': 0,
        'sans_solde': 0,
        'autre': 0
    }

    for p in presences:
        if p['type_journee'] in stats:
            stats[p['type_journee']] = p['nb']

    stats['config'] = {
        'jours_contrat': JOURS_CONTRAT,
        'jours_conges_payes': JOURS_CONGES_PAYES,
        'jours_conges_conv': JOURS_CONGES_CONV,
        'jours_feries': nb_jours_feries,
        'jours_repos_forfait': jours_repos_forfait,
        'jours_ouvrables': nb_jours_ouvrables
    }

    stats['soldes'] = {
        'jours_a_travailler': JOURS_CONTRAT - stats['travaille'],
        'conges_payes_restants': JOURS_CONGES_PAYES - stats['conge_paye'],
        'conges_conv_restants': JOURS_CONGES_CONV - stats['conge_conv'],
        'repos_forfait_restants': jours_repos_forfait - stats['repos_forfait']
    }

    stats['pourcentage_travail'] = (stats['travaille'] / JOURS_CONTRAT * 100) if JOURS_CONTRAT > 0 else 0

    conn.close()
    return stats


def calculer_solde_recup(user_id):
    """Calcule le solde de récupération total d'un salarié.
    Utilisé par dashboard et demande_recup pour éviter la duplication."""
    conn = get_db()

    try:
        try:
            user_data = conn.execute('SELECT solde_initial FROM users WHERE id = ?', (user_id,)).fetchone()
            solde = user_data['solde_initial'] if user_data and user_data['solde_initial'] else 0
        except (KeyError, TypeError):
            solde = 0

        heures = conn.execute('''
            SELECT date, heure_debut_matin, heure_fin_matin,
                   heure_debut_aprem, heure_fin_aprem, declaration_conforme
            FROM heures_reelles
            WHERE user_id = ?
            ORDER BY date
        ''', (user_id,)).fetchall()

        for h in heures:
            date_obj = datetime.strptime(h['date'], '%Y-%m-%d')
            if date_obj.weekday() == 6:  # Dimanche
                continue

            type_periode = get_type_periode(h['date'])
            jour_semaine = date_obj.weekday()

            total_theorique = 0
            if jour_semaine == 5:  # Samedi
                total_theorique = 0
            else:
                planning = get_planning_valide_a_date(user_id, type_periode, h['date'])
                if planning:
                    total_theorique = get_heures_theoriques_jour(planning, jour_semaine)

            if h['declaration_conforme']:
                total_reel = total_theorique
            else:
                heures_matin = calculer_heures(h['heure_debut_matin'], h['heure_fin_matin'])
                heures_aprem = calculer_heures(h['heure_debut_aprem'], h['heure_fin_aprem'])
                total_reel = heures_matin + heures_aprem

            solde += (total_reel - total_theorique)

        return solde
    finally:
        conn.close()
