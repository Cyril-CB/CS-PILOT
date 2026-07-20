"""
Fonctions utilitaires partagées entre tous les blueprints.
"""
import logging
import os
import re
from flask import session, flash, redirect, url_for
from functools import wraps
from datetime import datetime, timedelta
from database import get_db

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None


# ── Heure locale (timezone applicative) ──
# Le processus peut tourner en UTC (conteneur, executable Windows...), ce qui
# decalerait l'heure affichee et les calculs (planning, journaux). On force la
# timezone metier — Europe/Paris par defaut, surchargeable via APP_TIMEZONE.

def _timezone_app():
    """ZoneInfo de la timezone applicative, ou None si indisponible."""
    if ZoneInfo is None:
        return None
    nom = os.environ.get('APP_TIMEZONE', 'Europe/Paris')
    try:
        return ZoneInfo(nom)
    except Exception:
        logger.warning(
            "Timezone '%s' introuvable (paquet tzdata manquant ?) : "
            "repli sur l'heure locale du systeme.", nom
        )
        return None


def maintenant():
    """Datetime courant (naif) exprime dans la timezone applicative.

    Retourne un datetime sans tzinfo (heure « murale » locale), conforme au
    reste de l'application qui manipule des dates/heures naives.
    """
    tz = _timezone_app()
    if tz is None:
        return datetime.now()
    return datetime.now(tz).replace(tzinfo=None)


def aujourd_hui():
    """Date courante dans la timezone applicative."""
    return maintenant().date()


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
    if password is None:
        return ['Le mot de passe est obligatoire']

    errors = []

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


def slot_horaire(row, key):
    """Lit une valeur de créneau d'un Row/dict de manière tolérante.

    Renvoie None si la clé est absente (ancienne ligne sans colonne « soir », ou
    SELECT n'ayant pas récupéré la colonne), sans lever d'exception.
    """
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def duree_pause_meridienne(row):
    """Durée (heures) de la pause entre la fin du matin et le début de l'après-midi.

    0 si l'un des deux créneaux est incomplet ou si les horaires sont
    incohérents (début d'après-midi antérieur ou égal à la fin du matin).
    """
    fin_matin = slot_horaire(row, 'heure_fin_matin')
    debut_aprem = slot_horaire(row, 'heure_debut_aprem')
    if not (slot_horaire(row, 'heure_debut_matin') and fin_matin
            and debut_aprem and slot_horaire(row, 'heure_fin_aprem')):
        return 0
    try:
        fmt = '%H:%M'
        pause = (datetime.strptime(debut_aprem, fmt)
                 - datetime.strptime(fin_matin, fmt)).total_seconds() / 3600
    except ValueError:
        logger.warning("Format d'horaire invalide: %s - %s", fin_matin, debut_aprem)
        return 0
    return round(pause, 2) if pause > 0 else 0


def calculer_heures_reelles_jour(row):
    """Total d'heures d'une saisie (heures_reelles) : matin + après-midi + soir.

    Le créneau « soir » (optionnel, personnel d'entretien en vacances) est
    additionné aux deux créneaux habituels ; absent/vide, il compte pour 0.
    Si la pause méridienne est rémunérée (salarié resté à disposition sur
    place, art. L3121-2 : temps de travail effectif), elle est comptée dans
    le total.
    """
    total = (
        calculer_heures(slot_horaire(row, 'heure_debut_matin'), slot_horaire(row, 'heure_fin_matin'))
        + calculer_heures(slot_horaire(row, 'heure_debut_aprem'), slot_horaire(row, 'heure_fin_aprem'))
        + calculer_heures(slot_horaire(row, 'heure_debut_soir'), slot_horaire(row, 'heure_fin_soir'))
    )
    if slot_horaire(row, 'pause_remuneree'):
        total += duree_pause_meridienne(row)
    return round(total, 2)


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
    # Créneau soir optionnel (peut être absent d'un planning historisé ancien).
    soir_debut = slot_horaire(planning, f'{jour_nom}_soir_debut')
    soir_fin = slot_horaire(planning, f'{jour_nom}_soir_fin')

    heures_matin = calculer_heures(matin_debut, matin_fin)
    heures_aprem = calculer_heures(aprem_debut, aprem_fin)
    heures_soir = calculer_heures(soir_debut, soir_fin)

    return heures_matin + heures_aprem + heures_soir


def _heure_vers_minutes(h):
    """Convertit une heure 'HH:MM' en minutes depuis minuit. None si invalide."""
    if not h:
        return None
    try:
        dt = datetime.strptime(h, '%H:%M')
        return dt.hour * 60 + dt.minute
    except ValueError:
        return None


def _minutes_vers_heure(m):
    """Convertit des minutes depuis minuit en chaine 'HH:MM'."""
    m = int(round(m))
    return f"{m // 60:02d}:{m % 60:02d}"


def _soustraire_creneau(intervalle_debut, intervalle_fin, abs_debut, abs_fin):
    """Retire un creneau d'absence d'un intervalle horaire.

    Tous les arguments sont des chaines 'HH:MM'. Retourne la liste des
    segments restants (parties travaillees) sous forme de tuples (debut, fin)
    en chaines 'HH:MM'. Peut contenir 0, 1 ou 2 segments.
    """
    i_deb = _heure_vers_minutes(intervalle_debut)
    i_fin = _heure_vers_minutes(intervalle_fin)
    if i_deb is None or i_fin is None or i_fin <= i_deb:
        return []

    a_deb = _heure_vers_minutes(abs_debut)
    a_fin = _heure_vers_minutes(abs_fin)
    if a_deb is None or a_fin is None or a_fin <= a_deb:
        # Pas d'absence valide : tout l'intervalle est travaille
        return [(intervalle_debut, intervalle_fin)]

    # Pas de chevauchement
    if a_fin <= i_deb or a_deb >= i_fin:
        return [(intervalle_debut, intervalle_fin)]

    segments = []
    # Partie avant l'absence
    if a_deb > i_deb:
        segments.append((_minutes_vers_heure(i_deb), _minutes_vers_heure(min(a_deb, i_fin))))
    # Partie apres l'absence
    if a_fin < i_fin:
        segments.append((_minutes_vers_heure(max(a_fin, i_deb)), _minutes_vers_heure(i_fin)))

    return segments


def _fusionner_segments(segments):
    """Reduit une liste de segments en un seul (debut, fin) conservant le
    volume horaire total. Cas courant : 0 ou 1 segment (rendu exact). Pour le
    cas rare d'une absence au milieu d'une demi-journee (2 segments), on
    represente le temps travaille restant de facon contigue a partir du debut
    du premier segment afin de conserver le bon nombre d'heures.
    """
    if not segments:
        return (None, None)
    if len(segments) == 1:
        return segments[0]

    total_minutes = 0
    for deb, fin in segments:
        total_minutes += _heure_vers_minutes(fin) - _heure_vers_minutes(deb)
    debut = _heure_vers_minutes(segments[0][0])
    return (_minutes_vers_heure(debut), _minutes_vers_heure(debut + total_minutes))


def calculer_recup_partielle(planning, jour_semaine, abs_debut, abs_fin):
    """Calcule une recuperation partielle sur un creneau d'absence.

    A partir du planning theorique du jour, retire le creneau d'absence
    [abs_debut, abs_fin] et determine :
    - les heures de recuperation consommees (chevauchement de l'absence avec
      les horaires reellement prevus) ;
    - les horaires travailles restants (matin / apres-midi) a reporter dans
      le suivi.

    Retourne un dict :
        {
            'heures_recup': float,
            'matin_debut', 'matin_fin', 'aprem_debut', 'aprem_fin',  # 'HH:MM' ou None
            'heures_theoriques': float,
        }
    Retourne None si le jour n'est pas travaille (planning vide).
    """
    if not planning or jour_semaine < 0 or jour_semaine > 4:
        return None

    jours = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi']
    jour_nom = jours[jour_semaine]

    matin_debut = planning[f'{jour_nom}_matin_debut']
    matin_fin = planning[f'{jour_nom}_matin_fin']
    aprem_debut = planning[f'{jour_nom}_aprem_debut']
    aprem_fin = planning[f'{jour_nom}_aprem_fin']
    # Créneau soir optionnel (vacances) : peut être absent d'un planning ancien.
    soir_debut = slot_horaire(planning, f'{jour_nom}_soir_debut')
    soir_fin = slot_horaire(planning, f'{jour_nom}_soir_fin')

    heures_theoriques = (
        calculer_heures(matin_debut, matin_fin)
        + calculer_heures(aprem_debut, aprem_fin)
        + calculer_heures(soir_debut, soir_fin)
    )
    if heures_theoriques <= 0:
        return None

    segs_matin = _soustraire_creneau(matin_debut, matin_fin, abs_debut, abs_fin)
    segs_aprem = _soustraire_creneau(aprem_debut, aprem_fin, abs_debut, abs_fin)
    segs_soir = _soustraire_creneau(soir_debut, soir_fin, abs_debut, abs_fin)

    matin_d, matin_f = _fusionner_segments(segs_matin)
    aprem_d, aprem_f = _fusionner_segments(segs_aprem)
    soir_d, soir_f = _fusionner_segments(segs_soir)

    heures_travaillees = (
        calculer_heures(matin_d, matin_f)
        + calculer_heures(aprem_d, aprem_f)
        + calculer_heures(soir_d, soir_f)
    )
    heures_recup = round(heures_theoriques - heures_travaillees, 2)

    return {
        'heures_recup': heures_recup,
        'matin_debut': matin_d,
        'matin_fin': matin_f,
        'aprem_debut': aprem_d,
        'aprem_fin': aprem_f,
        'soir_debut': soir_d,
        'soir_fin': soir_f,
        'heures_theoriques': heures_theoriques,
    }


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

    if not ref:
        conn.close()
        return 'fixe'

    # Vérifier qu'au moins un planning alterné est encore actif (non supersédé par un planning fixe
    # plus récent pour le même type_periode) — évite de bloquer les heures théoriques si tous les
    # plannings alternés ont été supprimés ou remplacés par des plannings fixes.
    still_alternating = conn.execute('''
        SELECT 1 FROM planning_theorique p
        WHERE p.user_id = ?
          AND p.type_alternance IN ('semaine_1', 'semaine_2')
          AND p.date_debut_validite <= ?
          AND NOT EXISTS (
              SELECT 1 FROM planning_theorique p2
              WHERE p2.user_id = p.user_id
                AND p2.type_periode = p.type_periode
                AND p2.type_alternance = 'fixe'
                AND p2.date_debut_validite > p.date_debut_validite
                AND p2.date_debut_validite <= ?
          )
        LIMIT 1
    ''', (user_id, date_str, date_str)).fetchone()

    conn.close()

    if not still_alternating:
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

    def _chercher_planning_pour_type(type_periode_recherche):
        if semaine_type == 'fixe':
            return conn.execute('''
                SELECT * FROM planning_theorique
                WHERE user_id = ?
                AND type_periode = ?
                AND (type_alternance IS NULL OR type_alternance = 'fixe')
                AND date_debut_validite <= ?
                ORDER BY date_debut_validite DESC
                LIMIT 1
            ''', (user_id, type_periode_recherche, date_str)).fetchone()

        planning = conn.execute('''
            SELECT * FROM planning_theorique
            WHERE user_id = ?
            AND type_periode = ?
            AND type_alternance = ?
            AND date_debut_validite <= ?
            ORDER BY date_debut_validite DESC
            LIMIT 1
        ''', (user_id, type_periode_recherche, semaine_type, date_str)).fetchone()

        # Fallback : si aucun planning alterné pour ce type_periode, utiliser le planning fixe
        if not planning:
            planning = conn.execute('''
                SELECT * FROM planning_theorique
                WHERE user_id = ?
                AND type_periode = ?
                AND (type_alternance IS NULL OR type_alternance = 'fixe')
                AND date_debut_validite <= ?
                ORDER BY date_debut_validite DESC
                LIMIT 1
            ''', (user_id, type_periode_recherche, date_str)).fetchone()

        return planning

    planning = _chercher_planning_pour_type(type_periode)

    if not planning and type_periode == 'vacances':
        planning = _chercher_planning_pour_type('periode_scolaire')

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
        # « Forfait jour » (congé de repos posé par la direction) consomme le même
        # quota de repos forfait que « repos_forfait » (RTT) : on l'y agrège pour
        # que le solde restant en tienne compte.
        type_j = 'repos_forfait' if p['type_journee'] == 'forfait_jour' else p['type_journee']
        if type_j in stats:
            stats[type_j] += p['nb']

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


def est_dans_equipe_responsable(conn, responsable_id, salarie_id):
    """Vrai si le salarié fait partie de l'équipe suivie par ce responsable.

    Deux liens équivalents (mêmes règles que la validation des fiches) :
    - même secteur que le responsable ;
    - rattachement hiérarchique direct (users.responsable_id), qui peut
      traverser les secteurs : un agent d'entretien est rangé en secteur
      « logistique » pour l'analytique comptable mais encadré par la
      responsable de la crèche où il intervient.
    """
    row = conn.execute('''
        SELECT 1
        FROM users s
        JOIN users r ON r.id = ?
        WHERE s.id = ?
          AND (s.responsable_id = r.id
               OR (r.secteur_id IS NOT NULL AND s.secteur_id = r.secteur_id))
    ''', (responsable_id, salarie_id)).fetchone()
    return row is not None


def total_hs_payees(conn, user_id, annee=None, mois=None, avant=False):
    """Total des heures supplémentaires payées ET marquées « déduites du
    compteur » (variables_paie.hs_deduites_compteur = 1) pour un salarié.

    - sans filtre : toutes (déduction du solde de récupération global) ;
    - annee/mois avec avant=True : paies STRICTEMENT antérieures à ce mois
      (solde antérieur de la fiche mensuelle) ;
    - annee/mois : la paie de ce mois précis (« dont X h payées ce mois »).

    Les lignes antérieures à la migration 0057 ont hs_deduites_compteur à NULL
    et ne déduisent rien (pas d'effet rétroactif).
    """
    sql = ('SELECT COALESCE(SUM(heures_supps), 0) AS total FROM variables_paie '
           'WHERE user_id = ? AND hs_deduites_compteur = 1 AND heures_supps IS NOT NULL')
    params = [user_id]
    if annee is not None and mois is not None:
        if avant:
            sql += ' AND (annee < ? OR (annee = ? AND mois < ?))'
            params += [annee, annee, mois]
        else:
            sql += ' AND annee = ? AND mois = ?'
            params += [annee, mois]
    row = conn.execute(sql, params).fetchone()
    return row['total'] or 0


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
                   heure_debut_aprem, heure_fin_aprem,
                   heure_debut_soir, heure_fin_soir, declaration_conforme,
                   pause_remuneree
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
                total_reel = calculer_heures_reelles_jour(h)

            solde += (total_reel - total_theorique)

        # Heures supp payées (variables de paie, marquées « déduites du
        # compteur ») : payées, donc plus à récupérer.
        solde -= total_hs_payees(conn, user_id)

        return solde
    finally:
        conn.close()
