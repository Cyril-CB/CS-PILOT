"""
Blueprint planificateur_bp.

Gestionnaire de taches avec planification automatique par Time Blocking,
inspire de FlowSavvy. Le moteur d'optimisation (placement glouton + equilibrage
de charge) vit dans le module pur `planificateur_engine`.

Confidentialite : le planning est strictement personnel. Toutes les requetes
sont filtrees par `user_id = session['user_id']` et aucune route n'expose le
planning d'un autre utilisateur (meme la direction n'y a pas acces).

Acces (phase 1) : reserve au profil comptable, pour la phase de test.
"""
import calendar
import logging
from datetime import date, timedelta
from functools import wraps

from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, flash, jsonify)

from database import get_db
from utils import login_required, aujourd_hui, maintenant as _maintenant
import planificateur_engine as moteur

logger = logging.getLogger(__name__)

planificateur_bp = Blueprint('planificateur_bp', __name__)

# Profils autorises a acceder au planificateur : tous les salaries internes.
# Chacun ne voit que son propre planning (le prestataire de paie externe est
# hors perimetre).
PROFILS_AUTORISES = ('directeur', 'comptable', 'responsable', 'salarie')

# Horizon de planification (jours a partir d'aujourd'hui).
HORIZON_JOURS = 60

PRIORITES_VALIDES = ('basse', 'normale', 'haute')
PREFERENCES_VALIDES = ('aucune', 'matin', 'apres_midi')
FREQUENCES_VALIDES = ('quotidien', 'hebdomadaire', 'mensuel')

# Horaires de travail par defaut (lundi-vendredi), utilises uniquement si le
# salarie n'a aucun planning theorique defini (menu « Mon planning »).
HORAIRE_DEFAUT_INTERVALLES = [(540, 750), (810, 1050)]  # 09:00-12:30 / 13:30-17:30
# La direction est au forfait jours (pas d'horaires precis) : on retient une
# amplitude de bureau classique 09:00-12:30 / 14:00-18:00.
HORAIRE_DEFAUT_DIRECTION = [(540, 750), (840, 1080)]  # 09:00-12:30 / 14:00-18:00
JOURS_NOMS_PLANNING = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi']


# ── Controle d'acces ───────────────────────────────────────────────────────

def planif_required(f):
    """Connexion requise + profil autorise pour le planificateur."""
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if session.get('profil') not in PROFILS_AUTORISES:
            if '/api/' in request.path or _veut_json():
                return jsonify({'ok': False, 'erreur': 'Acces refuse.'}), 403
            flash("Le planificateur n'est pas accessible pour votre profil.", 'error')
            return redirect(url_for('dashboard_bp.dashboard'))
        return f(*args, **kwargs)
    return wrapper


def _veut_json():
    """Vrai si le client attend une reponse JSON (appel fetch)."""
    return (request.accept_mimetypes.best == 'application/json'
            or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or request.is_json)


def _uid():
    return session.get('user_id')


# ── Helpers horaires (repris du planning theorique) ────────────────────────

def _horaire_defaut_profil(conn, user_id):
    """Horaires par defaut (intervalles en minutes) selon le profil.

    La direction est au forfait jours : amplitude 09:00-12:30 / 14:00-18:00.
    Les autres profils : 09:00-12:30 / 13:30-17:30.
    """
    row = conn.execute('SELECT profil FROM users WHERE id = ?', (user_id,)).fetchone()
    if row and row['profil'] == 'directeur':
        return HORAIRE_DEFAUT_DIRECTION
    return HORAIRE_DEFAUT_INTERVALLES


def _horaires_par_date(conn, user_id, debut, fin):
    """Construit {date_str: [(deb_min, fin_min), ...]} pour l'horizon.

    Les horaires de travail proviennent du planning theorique du salarie
    (table planning_theorique, alimentee par le menu « Mon planning ») : ils
    n'ont donc pas a etre ressaisis. Le planning peut varier selon la periode
    (scolaire / vacances) et l'alternance, d'ou une resolution par date via les
    helpers existants.

    Si le salarie n'a aucun planning, un horaire par defaut est applique
    (lundi-vendredi) afin que le planificateur reste utilisable immediatement :
    09:00-12:30 / 13:30-17:30 en general, et 09:00-12:30 / 14:00-18:00 pour la
    direction (au forfait jours, sans horaires precis).
    """
    from utils import get_planning_valide_a_date, get_type_periode, slot_horaire

    a_un_planning = conn.execute(
        'SELECT 1 FROM planning_theorique WHERE user_id = ? LIMIT 1', (user_id,)
    ).fetchone()
    defaut = _horaire_defaut_profil(conn, user_id)

    horaires = {}
    d = debut
    while d <= fin:
        # Le planning theorique ne couvre que le lundi au vendredi.
        if d.weekday() < 5:
            date_str = d.isoformat()
            if not a_un_planning:
                horaires[date_str] = list(defaut)
            else:
                planning = get_planning_valide_a_date(
                    user_id, get_type_periode(date_str), date_str
                )
                if planning:
                    jn = JOURS_NOMS_PLANNING[d.weekday()]
                    intervalles = []
                    for col_d, col_f in ((f'{jn}_matin_debut', f'{jn}_matin_fin'),
                                         (f'{jn}_aprem_debut', f'{jn}_aprem_fin'),
                                         (f'{jn}_soir_debut', f'{jn}_soir_fin')):
                        dm, fm = moteur._to_min(slot_horaire(planning, col_d)), moteur._to_min(slot_horaire(planning, col_f))
                        if dm is not None and fm is not None and fm > dm:
                            intervalles.append((dm, fm))
                    if intervalles:
                        horaires[date_str] = intervalles
        d += timedelta(days=1)
    return horaires


def _jours_feries_set(conn, debut, fin):
    """Ensemble des jours feries (chaines 'YYYY-MM-DD') dans l'intervalle."""
    try:
        rows = conn.execute(
            'SELECT date FROM jours_feries WHERE date >= ? AND date <= ?',
            (debut.isoformat(), fin.isoformat())
        ).fetchall()
        return {r['date'] for r in rows}
    except Exception:
        return set()


# ── Generation des occurrences de taches recurrentes ───────────────────────

def _dernier_jour_mois(annee, mois):
    return calendar.monthrange(annee, mois)[1]


def _ajouter_mois(d, n):
    """Premier jour du mois decale de n mois."""
    mois = d.month - 1 + n
    annee = d.year + mois // 12
    mois = mois % 12 + 1
    return date(annee, mois, 1)


def _ensure_occurrence(conn, rec, anchor, fenetre_debut, fenetre_fin, today):
    """Cree une occurrence de tache pour une recurrence si elle n'existe pas."""
    # Borner par les dates de validite de la recurrence.
    rec_debut = rec['date_debut']
    rec_fin = rec['date_fin']
    if rec_debut and fenetre_fin.isoformat() < rec_debut:
        return
    if rec_fin and fenetre_debut.isoformat() > rec_fin:
        return
    if rec_debut and fenetre_debut.isoformat() < rec_debut:
        fenetre_debut = date.fromisoformat(rec_debut)
    if rec_fin and fenetre_fin.isoformat() > rec_fin:
        fenetre_fin = date.fromisoformat(rec_fin)
    if fenetre_debut < today:
        fenetre_debut = today
    if fenetre_fin < fenetre_debut:
        return

    existe = conn.execute(
        'SELECT id FROM planif_taches WHERE recurrence_id = ? AND occurrence_jour = ?',
        (rec['id'], anchor)
    ).fetchone()
    if existe:
        return

    conn.execute(
        '''INSERT INTO planif_taches
           (user_id, type, titre, description, duree_min, deadline, date_min,
            priorite, preference, secable, duree_min_bloc, statut,
            recurrence_id, occurrence_jour)
           VALUES (?, 'tache', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'a_faire', ?, ?)''',
        (rec['user_id'], rec['titre'], rec['description'], rec['duree_min'],
         fenetre_fin.isoformat(), fenetre_debut.isoformat(), rec['priorite'],
         rec['preference'], rec['secable'], rec['duree_min_bloc'],
         rec['id'], anchor)
    )


def _generer_occurrences(conn, user_id, today, fin, horaires):
    """Materialise les occurrences des recurrences actives sur l'horizon.

    `horaires` ({date_str: [...]}) sert a ne pas creer d'occurrence quotidienne
    un jour non travaille (qui ne pourrait jamais etre placee).
    """
    recurrences = conn.execute(
        'SELECT * FROM planif_recurrences WHERE user_id = ? AND active = 1',
        (user_id,)
    ).fetchall()

    for rec in recurrences:
        freq = rec['frequence']
        if freq == 'quotidien':
            d = today
            while d <= fin:
                if d.isoformat() in horaires:
                    _ensure_occurrence(conn, rec, d.isoformat(), d, d, today)
                d += timedelta(days=1)

        elif freq == 'hebdomadaire':
            lundi = today - timedelta(days=today.weekday())
            while lundi <= fin:
                semaine_fin = min(lundi + timedelta(days=6), fin)
                if rec['jour_semaine'] is not None:
                    cible = lundi + timedelta(days=int(rec['jour_semaine']))
                    if today <= cible <= fin:
                        _ensure_occurrence(conn, rec, lundi.isoformat(), cible, cible, today)
                else:
                    _ensure_occurrence(conn, rec, lundi.isoformat(),
                                       max(lundi, today), semaine_fin, today)
                lundi += timedelta(days=7)

        elif freq == 'mensuel':
            cur = date(today.year, today.month, 1)
            while cur <= fin:
                dernier = _dernier_jour_mois(cur.year, cur.month)
                mois_fin = date(cur.year, cur.month, dernier)
                if rec['jour_mois']:
                    jour = min(int(rec['jour_mois']), dernier)
                    cible = date(cur.year, cur.month, jour)
                    if today <= cible <= fin:
                        _ensure_occurrence(conn, rec, cur.isoformat(), cible, cible, today)
                else:
                    _ensure_occurrence(conn, rec, cur.isoformat(),
                                       max(cur, today), min(mois_fin, fin), today)
                cur = _ajouter_mois(cur, 1)
    conn.commit()


# ── Replanification ────────────────────────────────────────────────────────

def _replanifier(conn, user_id, maintenant=None):
    """Recalcule le planning des taches sur l'horizon. Retourne la liste des
    taches non planifiees (chacune enrichie de son titre).

    `maintenant` (datetime) permet de figer l'instant courant pour les tests ;
    par defaut, l'heure locale applicative (utils.maintenant, Europe/Paris). On
    ne planifie jamais dans le passe : si la journee en cours est terminee, les
    taches partent au lendemain.
    """
    if maintenant is None:
        maintenant = _maintenant()
    today = maintenant.date()
    minute_courante = maintenant.hour * 60 + maintenant.minute
    fin = today + timedelta(days=HORIZON_JOURS)

    # Horaires de travail repris du planning theorique du salarie.
    horaires = _horaires_par_date(conn, user_id, today, fin)
    feries = _jours_feries_set(conn, today, fin)

    # Nettoyer les occurrences recurrentes passees jamais realisees (une reunion
    # quotidienne manquee hier n'est pas reportee a aujourd'hui).
    perimees = conn.execute(
        '''SELECT id FROM planif_taches
           WHERE user_id = ? AND recurrence_id IS NOT NULL AND statut = 'a_faire'
             AND deadline IS NOT NULL AND deadline < ?''',
        (user_id, today.isoformat())
    ).fetchall()
    for occ in perimees:
        conn.execute('DELETE FROM planif_blocs WHERE tache_id = ?', (occ['id'],))
        conn.execute('DELETE FROM planif_taches WHERE id = ?', (occ['id'],))

    _generer_occurrences(conn, user_id, today, fin, horaires)

    # Creneaux deja occupes a conserver : evenements fixes (verrouilles) et
    # blocs deja realises, a partir d'aujourd'hui.
    rows = conn.execute(
        '''SELECT date, heure_debut, heure_fin FROM planif_blocs
           WHERE user_id = ? AND date >= ? AND (verrouille = 1 OR statut = 'fait')''',
        (user_id, today.isoformat())
    ).fetchall()
    occupes = {}
    for r in rows:
        occupes.setdefault(r['date'], []).append(
            (moteur._to_min(r['heure_debut']), moteur._to_min(r['heure_fin']))
        )

    # Supprimer les blocs futurs replanifiables (ni verrouilles ni realises).
    conn.execute(
        '''DELETE FROM planif_blocs
           WHERE user_id = ? AND date >= ? AND verrouille = 0 AND statut != 'fait' ''',
        (user_id, today.isoformat())
    )

    # Charger les taches a planifier (hors evenements fixes).
    taches_rows = conn.execute(
        '''SELECT * FROM planif_taches
           WHERE user_id = ? AND type = 'tache' AND statut = 'a_faire' ''',
        (user_id,)
    ).fetchall()

    taches = []
    titres = {}
    recurrence_ids = set()
    for t in taches_rows:
        duree = int(t['duree_min'])
        # Temps reellement REALISE (blocs « fait ») : sert a savoir si la tache
        # est terminee.
        fait_min = conn.execute(
            "SELECT COALESCE(SUM(duree_min), 0) AS s FROM planif_blocs "
            "WHERE tache_id = ? AND statut = 'fait'",
            (t['id'],)
        ).fetchone()['s']
        if int(fait_min) >= duree:
            conn.execute("UPDATE planif_taches SET statut = 'fait' WHERE id = ?", (t['id'],))
            continue
        # Temps deja ENGAGE et non replanifiable : blocs realises (fait) ET blocs
        # verrouilles manuellement (glisser-deposer). Verrouiller n'est pas
        # « faire » : on ne replanifie que le reste, autour de ces creneaux, mais
        # la tache reste a faire.
        # Un bloc verrouille n'est compte que s'il est encore a venir (date >=
        # aujourd'hui) : un creneau verrouille dont le jour est passe sans avoir
        # ete realise n'occupe plus la capacite future, donc son temps doit etre
        # replanifie (sinon il serait silencieusement perdu). Les blocs « fait »,
        # eux, comptent quelle que soit leur date (travail reellement accompli).
        engage_min = conn.execute(
            "SELECT COALESCE(SUM(duree_min), 0) AS s FROM planif_blocs "
            "WHERE tache_id = ? AND (statut = 'fait' OR (verrouille = 1 AND date >= ?))",
            (t['id'], today.isoformat())
        ).fetchone()['s']
        restant = duree - int(engage_min or 0)
        if restant <= 0:
            continue  # entierement planifie (creneaux verrouilles) : rien a ajouter
        dmin = t['date_min'] or today.isoformat()
        if dmin < today.isoformat():
            dmin = today.isoformat()
        titres[t['id']] = t['titre']
        if t['recurrence_id'] is not None:
            recurrence_ids.add(t['id'])
        taches.append({
            'id': t['id'], 'titre': t['titre'], 'duree_min': restant,
            'deadline': t['deadline'], 'priorite': t['priorite'],
            'preference': t['preference'], 'secable': bool(t['secable']),
            'duree_min_bloc': t['duree_min_bloc'],
            'est_recurrente': t['recurrence_id'] is not None,
            'date_min': dmin,
        })

    resultat = moteur.planifier(taches, occupes, horaires, today, fin, feries,
                                minute_courante=minute_courante)

    for b in resultat['blocs']:
        conn.execute(
            '''INSERT INTO planif_blocs
               (tache_id, user_id, date, heure_debut, heure_fin, duree_min, statut, verrouille)
               VALUES (?, ?, ?, ?, ?, ?, 'planifie', 0)''',
            (b['tache_id'], user_id, b['date'], b['heure_debut'], b['heure_fin'], b['duree_min'])
        )
    conn.commit()

    # Les occurrences recurrentes sont placees « au mieux, la ou il reste de la
    # place » : leur absence (ex. journee deja terminee) n'est pas une anomalie
    # a signaler a l'utilisateur.
    non_planifie = []
    for np in resultat['non_planifie']:
        if np['tache_id'] in recurrence_ids:
            continue
        non_planifie.append({**np, 'titre': titres.get(np['tache_id'], '')})
    return non_planifie


# ── Synchronisation des blocs d'evenements fixes ───────────────────────────

def _sync_bloc_evenement(conn, tache):
    """(Re)cree le bloc verrouille correspondant a un evenement fixe."""
    conn.execute('DELETE FROM planif_blocs WHERE tache_id = ?', (tache['id'],))
    if not (tache['date_fixe'] and tache['heure_debut'] and tache['heure_fin']):
        return
    dm = moteur._to_min(tache['heure_debut'])
    fm = moteur._to_min(tache['heure_fin'])
    duree = (fm - dm) if (dm is not None and fm is not None) else 0
    statut = 'fait' if tache['statut'] == 'fait' else 'planifie'
    conn.execute(
        '''INSERT INTO planif_blocs
           (tache_id, user_id, date, heure_debut, heure_fin, duree_min, statut, verrouille)
           VALUES (?, ?, ?, ?, ?, ?, ?, 1)''',
        (tache['id'], tache['user_id'], tache['date_fixe'], tache['heure_debut'],
         tache['heure_fin'], max(duree, 0), statut)
    )


# ── Serialisation ──────────────────────────────────────────────────────────

def _serialiser_blocs(conn, user_id, debut, fin):
    """Retourne la liste JSON des blocs (avec infos de la tache) sur l'intervalle."""
    rows = conn.execute(
        '''SELECT b.id, b.tache_id, b.date, b.heure_debut, b.heure_fin, b.duree_min,
                  b.statut AS bloc_statut, b.verrouille,
                  t.titre, t.type, t.description, t.priorite, t.preference,
                  t.deadline, t.secable, t.statut AS tache_statut, t.couleur,
                  t.recurrence_id, t.duree_min AS tache_duree_min, t.duree_min_bloc
           FROM planif_blocs b
           JOIN planif_taches t ON b.tache_id = t.id
           WHERE b.user_id = ? AND b.date >= ? AND b.date <= ?
           ORDER BY b.date, b.heure_debut''',
        (user_id, debut, fin)
    ).fetchall()
    today = aujourd_hui()
    blocs = []
    for r in rows:
        urgence = moteur.niveau_urgence(r['deadline'], today, r['bloc_statut'])
        blocs.append({
            'id': r['id'], 'tache_id': r['tache_id'], 'date': r['date'],
            'heure_debut': r['heure_debut'], 'heure_fin': r['heure_fin'],
            'duree_min': r['duree_min'], 'statut': r['bloc_statut'],
            'verrouille': bool(r['verrouille']), 'titre': r['titre'],
            'type': r['type'], 'description': r['description'] or '',
            'priorite': r['priorite'], 'preference': r['preference'],
            'deadline': r['deadline'], 'secable': bool(r['secable']),
            'tache_statut': r['tache_statut'], 'couleur': r['couleur'] or '',
            'urgence': urgence, 'recurrente': r['recurrence_id'] is not None,
            'tache_duree_min': r['tache_duree_min'], 'duree_min_bloc': r['duree_min_bloc'],
        })
    return blocs


def _taches_non_placees(conn, user_id):
    """Taches (non recurrentes, a faire) sans aucun bloc futur planifie.

    Ce sont les taches que le moteur n'a pas pu caser : echeance depassee sans
    capacite, horizon sature, ou tache non secable plus longue que le plus grand
    creneau. N'ayant aucun bloc sur le calendrier, elles seraient invisibles et
    non gerables ; on les expose a part pour qu'elles restent modifiables,
    reportables et supprimables (sinon elles deviennent des « taches fantomes »
    qui declenchent l'alerte sans pouvoir etre corrigees).
    """
    today = aujourd_hui().isoformat()
    rows = conn.execute(
        '''SELECT t.* FROM planif_taches t
           WHERE t.user_id = ? AND t.type = 'tache' AND t.statut = 'a_faire'
             AND t.recurrence_id IS NULL
             AND NOT EXISTS (
                 SELECT 1 FROM planif_blocs b
                 WHERE b.tache_id = t.id AND b.date >= ?
             )
           ORDER BY t.deadline IS NULL, t.deadline''',
        (user_id, today)
    ).fetchall()
    return [dict(r) for r in rows]


# ── Validation des entrees ─────────────────────────────────────────────────

def _parse_int(valeur, defaut=0, mini=None, maxi=None):
    try:
        n = int(valeur)
    except (TypeError, ValueError):
        return defaut
    if mini is not None:
        n = max(mini, n)
    if maxi is not None:
        n = min(maxi, n)
    return n


def _valide_date(valeur):
    if not valeur:
        return None
    try:
        return date.fromisoformat(valeur).isoformat()
    except (TypeError, ValueError):
        return None


def _valide_heure(valeur):
    if moteur._to_min(valeur) is None:
        return None
    return valeur


# ── Routes : page principale ───────────────────────────────────────────────

@planificateur_bp.route('/planificateur')
@planif_required
def planificateur():
    """Page principale du planificateur (calendrier + panneaux de gestion)."""
    conn = get_db()
    try:
        user_id = _uid()
        vue = request.args.get('vue', 'semaine')
        if vue not in ('jour', 'semaine', 'mois'):
            vue = 'semaine'
        date_ref = _valide_date(request.args.get('date')) or aujourd_hui().isoformat()

        a_un_planning = conn.execute(
            'SELECT 1 FROM planning_theorique WHERE user_id = ? LIMIT 1', (user_id,)
        ).fetchone() is not None
        # Description des horaires par defaut (affichee si aucun planning).
        defaut = _horaire_defaut_profil(conn, user_id)
        horaire_defaut_txt = ' / '.join(
            f'{moteur._to_hhmm(a)}–{moteur._to_hhmm(b)}' for a, b in defaut
        )
        recurrences = conn.execute(
            'SELECT * FROM planif_recurrences WHERE user_id = ? AND active = 1 ORDER BY id DESC',
            (user_id,)
        ).fetchall()

        # Taches sans bloc futur planifie = non placees (indicateur persistant).
        # Les occurrences recurrentes sont exclues : elles sont placees « au
        # mieux, la ou il reste de la place » et leur absence n'est pas une
        # anomalie a signaler.
        taches_non_placees = _taches_non_placees(conn, user_id)

        return render_template(
            'planificateur.html',
            vue=vue, date_ref=date_ref,
            recurrences=[dict(r) for r in recurrences],
            taches_non_placees=taches_non_placees,
            a_un_planning=a_un_planning,
            horaire_defaut_txt=horaire_defaut_txt,
        )
    finally:
        conn.close()


@planificateur_bp.route('/planificateur/api/blocs')
@planif_required
def api_blocs():
    """Retourne les blocs et les horaires de travail (JSON) sur un intervalle."""
    conn = get_db()
    try:
        user_id = _uid()
        debut = _valide_date(request.args.get('debut')) or aujourd_hui().isoformat()
        fin = _valide_date(request.args.get('fin')) or debut
        blocs = _serialiser_blocs(conn, user_id, debut, fin)
        # Horaires de travail (par date) pour afficher les plages travaillees.
        horaires_min = _horaires_par_date(
            conn, user_id, date.fromisoformat(debut), date.fromisoformat(fin)
        )
        horaires = {k: [[d, f] for (d, f) in v] for k, v in horaires_min.items()}
        # Taches non placees : renvoyees a chaque rafraichissement pour que le
        # bandeau reste a jour apres une action (creation, suppression...) sans
        # rechargement complet de la page.
        non_placees = _taches_non_placees(conn, user_id)
        return jsonify({'ok': True, 'blocs': blocs, 'horaires': horaires,
                        'non_placees': non_placees})
    finally:
        conn.close()


# ── Routes : taches et evenements ──────────────────────────────────────────

def _lire_payload():
    """Lit les donnees du formulaire ou du corps JSON."""
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form


@planificateur_bp.route('/planificateur/api/tache', methods=['POST'])
@planif_required
def api_creer_tache():
    """Cree une tache ou un evenement fixe puis replanifie."""
    data = _lire_payload()
    conn = get_db()
    try:
        user_id = _uid()
        type_item = data.get('type', 'tache')
        titre = (data.get('titre') or '').strip()
        description = (data.get('description') or '').strip()
        if not titre:
            return jsonify({'ok': False, 'erreur': 'Le titre est obligatoire.'}), 400

        if type_item == 'evenement':
            date_fixe = _valide_date(data.get('date_fixe'))
            heure_debut = _valide_heure(data.get('heure_debut'))
            heure_fin = _valide_heure(data.get('heure_fin'))
            if not (date_fixe and heure_debut and heure_fin):
                return jsonify({'ok': False, 'erreur': 'Date et horaires de l\'evenement requis.'}), 400
            if moteur._to_min(heure_fin) <= moteur._to_min(heure_debut):
                return jsonify({'ok': False, 'erreur': 'L\'heure de fin doit suivre l\'heure de debut.'}), 400
            cur = conn.execute(
                '''INSERT INTO planif_taches
                   (user_id, type, titre, description, date_fixe, heure_debut, heure_fin,
                    duree_min, statut)
                   VALUES (?, 'evenement', ?, ?, ?, ?, ?, ?, 'a_faire')''',
                (user_id, titre, description, date_fixe, heure_debut, heure_fin,
                 moteur._to_min(heure_fin) - moteur._to_min(heure_debut))
            )
            tache = conn.execute('SELECT * FROM planif_taches WHERE id = ?',
                                 (cur.lastrowid,)).fetchone()
            _sync_bloc_evenement(conn, tache)
            conn.commit()
        else:
            duree_min = _parse_int(data.get('duree_min'), 60, mini=5, maxi=24 * 60)
            deadline = _valide_date(data.get('deadline'))
            priorite = data.get('priorite') if data.get('priorite') in PRIORITES_VALIDES else 'normale'
            preference = data.get('preference') if data.get('preference') in PREFERENCES_VALIDES else 'aucune'
            secable = 1 if str(data.get('secable')) in ('1', 'true', 'on', 'True') else 0
            duree_min_bloc = _parse_int(data.get('duree_min_bloc'), 30, mini=5, maxi=duree_min)
            conn.execute(
                '''INSERT INTO planif_taches
                   (user_id, type, titre, description, duree_min, deadline,
                    priorite, preference, secable, duree_min_bloc, statut)
                   VALUES (?, 'tache', ?, ?, ?, ?, ?, ?, ?, ?, 'a_faire')''',
                (user_id, titre, description, duree_min, deadline, priorite,
                 preference, secable, duree_min_bloc)
            )
            conn.commit()

        non_planifie = _replanifier(conn, user_id)
        return jsonify({'ok': True, 'non_planifie': non_planifie})
    finally:
        conn.close()


def _get_tache_proprietaire(conn, tache_id, user_id):
    return conn.execute(
        'SELECT * FROM planif_taches WHERE id = ? AND user_id = ?',
        (tache_id, user_id)
    ).fetchone()


@planificateur_bp.route('/planificateur/api/tache/<int:tache_id>', methods=['POST'])
@planif_required
def api_modifier_tache(tache_id):
    """Modifie une tache ou un evenement existant."""
    data = _lire_payload()
    conn = get_db()
    try:
        user_id = _uid()
        tache = _get_tache_proprietaire(conn, tache_id, user_id)
        if not tache:
            return jsonify({'ok': False, 'erreur': 'Tache introuvable.'}), 404

        titre = (data.get('titre') or tache['titre']).strip()
        description = (data.get('description') or '').strip()

        if tache['type'] == 'evenement':
            date_fixe = _valide_date(data.get('date_fixe')) or tache['date_fixe']
            heure_debut = _valide_heure(data.get('heure_debut')) or tache['heure_debut']
            heure_fin = _valide_heure(data.get('heure_fin')) or tache['heure_fin']
            if moteur._to_min(heure_fin) <= moteur._to_min(heure_debut):
                return jsonify({'ok': False, 'erreur': 'Horaires invalides.'}), 400
            conn.execute(
                '''UPDATE planif_taches SET titre = ?, description = ?, date_fixe = ?,
                   heure_debut = ?, heure_fin = ?, duree_min = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?''',
                (titre, description, date_fixe, heure_debut, heure_fin,
                 moteur._to_min(heure_fin) - moteur._to_min(heure_debut), tache_id)
            )
            maj = conn.execute('SELECT * FROM planif_taches WHERE id = ?', (tache_id,)).fetchone()
            _sync_bloc_evenement(conn, maj)
            conn.commit()
        else:
            duree_min = _parse_int(data.get('duree_min'), tache['duree_min'], mini=5, maxi=24 * 60)
            deadline = _valide_date(data.get('deadline'))
            priorite = data.get('priorite') if data.get('priorite') in PRIORITES_VALIDES else tache['priorite']
            preference = data.get('preference') if data.get('preference') in PREFERENCES_VALIDES else tache['preference']
            secable = 1 if str(data.get('secable')) in ('1', 'true', 'on', 'True') else 0
            duree_min_bloc = _parse_int(data.get('duree_min_bloc'), tache['duree_min_bloc'], mini=5, maxi=duree_min)
            conn.execute(
                '''UPDATE planif_taches SET titre = ?, description = ?, duree_min = ?,
                   deadline = ?, priorite = ?, preference = ?, secable = ?,
                   duree_min_bloc = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?''',
                (titre, description, duree_min, deadline, priorite, preference,
                 secable, duree_min_bloc, tache_id)
            )
            conn.commit()

        non_planifie = _replanifier(conn, user_id)
        return jsonify({'ok': True, 'non_planifie': non_planifie})
    finally:
        conn.close()


@planificateur_bp.route('/planificateur/api/tache/<int:tache_id>/supprimer', methods=['POST'])
@planif_required
def api_supprimer_tache(tache_id):
    """Supprime une tache et ses blocs."""
    conn = get_db()
    try:
        user_id = _uid()
        tache = _get_tache_proprietaire(conn, tache_id, user_id)
        if not tache:
            return jsonify({'ok': False, 'erreur': 'Tache introuvable.'}), 404
        # Suppression manuelle des blocs enfants (FK CASCADE non actif sur cette base).
        conn.execute('DELETE FROM planif_blocs WHERE tache_id = ?', (tache_id,))
        conn.execute('DELETE FROM planif_taches WHERE id = ?', (tache_id,))
        conn.commit()
        non_planifie = _replanifier(conn, user_id)
        return jsonify({'ok': True, 'non_planifie': non_planifie})
    finally:
        conn.close()


@planificateur_bp.route('/planificateur/api/tache/<int:tache_id>/statut', methods=['POST'])
@planif_required
def api_statut_tache(tache_id):
    """Change le statut d'une tache (fait / a_faire / annule)."""
    data = _lire_payload()
    statut = data.get('statut')
    if statut not in ('fait', 'a_faire', 'annule'):
        return jsonify({'ok': False, 'erreur': 'Statut invalide.'}), 400
    conn = get_db()
    try:
        user_id = _uid()
        tache = _get_tache_proprietaire(conn, tache_id, user_id)
        if not tache:
            return jsonify({'ok': False, 'erreur': 'Tache introuvable.'}), 404

        conn.execute('UPDATE planif_taches SET statut = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                     (statut, tache_id))
        if statut == 'fait':
            # Marquer ses blocs futurs comme realises (ils restent en place).
            conn.execute(
                "UPDATE planif_blocs SET statut = 'fait' WHERE tache_id = ? AND date >= ?",
                (tache_id, aujourd_hui().isoformat())
            )
        elif statut in ('a_faire', 'annule'):
            if tache['type'] == 'evenement':
                maj = conn.execute('SELECT * FROM planif_taches WHERE id = ?', (tache_id,)).fetchone()
                _sync_bloc_evenement(conn, maj)
        conn.commit()
        non_planifie = _replanifier(conn, user_id)
        return jsonify({'ok': True, 'non_planifie': non_planifie})
    finally:
        conn.close()


@planificateur_bp.route('/planificateur/api/tache/<int:tache_id>/reporter', methods=['POST'])
@planif_required
def api_reporter_tache(tache_id):
    """Reporte une tache : la replanifie a partir d'une date donnee (ou demain)."""
    data = _lire_payload()
    conn = get_db()
    try:
        user_id = _uid()
        tache = _get_tache_proprietaire(conn, tache_id, user_id)
        if not tache:
            return jsonify({'ok': False, 'erreur': 'Tache introuvable.'}), 404

        nouveau_min = _valide_date(data.get('date_min'))
        if not nouveau_min:
            nouveau_min = (aujourd_hui() + timedelta(days=1)).isoformat()
        conn.execute(
            'UPDATE planif_taches SET date_min = ?, statut = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (nouveau_min, 'a_faire', tache_id)
        )
        # Liberer les blocs non realises de cette tache avant de replanifier.
        conn.execute(
            "DELETE FROM planif_blocs WHERE tache_id = ? AND statut != 'fait'",
            (tache_id,)
        )
        conn.commit()
        non_planifie = _replanifier(conn, user_id)
        return jsonify({'ok': True, 'non_planifie': non_planifie})
    finally:
        conn.close()


@planificateur_bp.route('/planificateur/api/tache/<int:tache_id>/terminer_partiel', methods=['POST'])
@planif_required
def api_terminer_partiel(tache_id):
    """Marque la progression actuelle comme faite et cree une nouvelle tache
    pour planifier la fin (le reste de la duree estimee)."""
    data = _lire_payload()
    conn = get_db()
    try:
        user_id = _uid()
        tache = _get_tache_proprietaire(conn, tache_id, user_id)
        if not tache or tache['type'] != 'tache':
            return jsonify({'ok': False, 'erreur': 'Tache introuvable.'}), 404

        minutes_faites = _parse_int(data.get('minutes_faites'), 0, mini=0, maxi=int(tache['duree_min']))
        restant = int(tache['duree_min']) - minutes_faites
        # La tache courante est cloturee. On conserve ses blocs deja realises
        # (historique) et on LIBERE ses creneaux futurs non realises : le reste
        # est replanifie via une nouvelle tache « suite ». Marquer ces creneaux
        # futurs comme « faits » surevaluerait le travail accompli et
        # consommerait deux fois la capacite (bloc fige + tache suite).
        conn.execute("UPDATE planif_taches SET statut = 'fait', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     (tache_id,))
        conn.execute("DELETE FROM planif_blocs WHERE tache_id = ? AND statut != 'fait'", (tache_id,))

        if restant > 0:
            conn.execute(
                '''INSERT INTO planif_taches
                   (user_id, type, titre, description, duree_min, deadline,
                    priorite, preference, secable, duree_min_bloc, statut)
                   VALUES (?, 'tache', ?, ?, ?, ?, ?, ?, ?, ?, 'a_faire')''',
                (user_id, (tache['titre'] + ' (suite)')[:200], tache['description'],
                 restant, tache['deadline'], tache['priorite'], tache['preference'],
                 tache['secable'], tache['duree_min_bloc'])
            )
        conn.commit()
        non_planifie = _replanifier(conn, user_id)
        return jsonify({'ok': True, 'non_planifie': non_planifie})
    finally:
        conn.close()


# ── Routes : blocs ─────────────────────────────────────────────────────────

@planificateur_bp.route('/planificateur/api/bloc/<int:bloc_id>/statut', methods=['POST'])
@planif_required
def api_statut_bloc(bloc_id):
    """Bascule un bloc entre planifie et fait (depuis le calendrier)."""
    data = _lire_payload()
    statut = data.get('statut', 'fait')
    if statut not in ('fait', 'planifie'):
        return jsonify({'ok': False, 'erreur': 'Statut invalide.'}), 400
    conn = get_db()
    try:
        user_id = _uid()
        bloc = conn.execute('SELECT * FROM planif_blocs WHERE id = ? AND user_id = ?',
                            (bloc_id, user_id)).fetchone()
        if not bloc:
            return jsonify({'ok': False, 'erreur': 'Bloc introuvable.'}), 404
        conn.execute('UPDATE planif_blocs SET statut = ? WHERE id = ?', (statut, bloc_id))

        # La tache n'est consideree faite que si le temps realise couvre la duree
        # estimee. Une tache sous-planifiee (capacite insuffisante : moins de
        # blocs que sa duree) ne doit pas etre cloturee en laissant tomber son
        # reliquat lorsque ses quelques blocs visibles sont coches.
        if statut == 'fait':
            tache = conn.execute(
                "SELECT duree_min FROM planif_taches WHERE id = ?", (bloc['tache_id'],)
            ).fetchone()
            fait_min = conn.execute(
                "SELECT COALESCE(SUM(duree_min), 0) AS s FROM planif_blocs "
                "WHERE tache_id = ? AND statut = 'fait'",
                (bloc['tache_id'],)
            ).fetchone()['s']
            if tache and int(fait_min) >= int(tache['duree_min']):
                conn.execute("UPDATE planif_taches SET statut = 'fait' WHERE id = ?",
                             (bloc['tache_id'],))
        else:
            conn.execute("UPDATE planif_taches SET statut = 'a_faire' WHERE id = ?",
                         (bloc['tache_id'],))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@planificateur_bp.route('/planificateur/api/bloc/<int:bloc_id>/supprimer', methods=['POST'])
@planif_required
def api_supprimer_bloc(bloc_id):
    """Supprime un bloc precis (libere le creneau)."""
    conn = get_db()
    try:
        user_id = _uid()
        bloc = conn.execute(
            'SELECT b.*, t.type AS tache_type FROM planif_blocs b '
            'JOIN planif_taches t ON b.tache_id = t.id '
            'WHERE b.id = ? AND b.user_id = ?',
            (bloc_id, user_id)
        ).fetchone()
        if not bloc:
            return jsonify({'ok': False, 'erreur': 'Bloc introuvable.'}), 404
        # Le creneau d'un evenement fixe ne se supprime pas seul (sinon
        # l'evenement reste en base sans occuper son horaire) : passer par la
        # suppression de l'evenement. En revanche un bloc de tache verrouille
        # (place manuellement) reste supprimable et libere son creneau.
        if bloc['tache_type'] == 'evenement':
            return jsonify({
                'ok': False,
                'erreur': "Ce créneau correspond à un événement fixe : supprimez ou modifiez l'événement."
            }), 400
        conn.execute('DELETE FROM planif_blocs WHERE id = ?', (bloc_id,))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@planificateur_bp.route('/planificateur/api/bloc/<int:bloc_id>/deplacer', methods=['POST'])
@planif_required
def api_deplacer_bloc(bloc_id):
    """Deplace un bloc (glisser-deposer) puis le verrouille.

    Le bloc conserve sa duree ; on change sa date et son heure de debut. Le
    creneau devient fixe (verrouille = 1) : la replanification ne le deplace
    plus et organise le reste autour. Pour un evenement, on met aussi a jour la
    date/heure de l'evenement lui-meme.
    """
    data = _lire_payload()
    conn = get_db()
    try:
        user_id = _uid()
        bloc = conn.execute(
            'SELECT b.*, t.type AS tache_type FROM planif_blocs b '
            'JOIN planif_taches t ON b.tache_id = t.id '
            'WHERE b.id = ? AND b.user_id = ?',
            (bloc_id, user_id)
        ).fetchone()
        if not bloc:
            return jsonify({'ok': False, 'erreur': 'Bloc introuvable.'}), 404

        nouvelle_date = _valide_date(data.get('date')) or bloc['date']
        if nouvelle_date < aujourd_hui().isoformat():
            return jsonify({'ok': False, 'erreur': "Impossible de déplacer un créneau dans le passé."}), 400
        deb = _valide_heure(data.get('heure_debut'))
        if not deb:
            return jsonify({'ok': False, 'erreur': 'Heure de debut invalide.'}), 400
        duree = int(bloc['duree_min'])
        deb_min = moteur._to_min(deb)
        fin_min = deb_min + duree
        if fin_min > 24 * 60:  # ne pas deborder sur le lendemain
            fin_min = 24 * 60
            deb_min = max(0, fin_min - duree)

        conn.execute(
            'UPDATE planif_blocs SET date = ?, heure_debut = ?, heure_fin = ?, verrouille = 1 WHERE id = ?',
            (nouvelle_date, moteur._to_hhmm(deb_min), moteur._to_hhmm(fin_min), bloc_id)
        )
        if bloc['tache_type'] == 'evenement':
            conn.execute(
                'UPDATE planif_taches SET date_fixe = ?, heure_debut = ?, heure_fin = ?, '
                'updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                (nouvelle_date, moteur._to_hhmm(deb_min), moteur._to_hhmm(fin_min), bloc['tache_id'])
            )
        conn.commit()
        non_planifie = _replanifier(conn, user_id)
        return jsonify({'ok': True, 'non_planifie': non_planifie})
    finally:
        conn.close()


@planificateur_bp.route('/planificateur/api/bloc/<int:bloc_id>/verrou', methods=['POST'])
@planif_required
def api_verrou_bloc(bloc_id):
    """Verrouille / deverrouille un bloc de tache (le rend fixe ou re-planifiable)."""
    data = _lire_payload()
    verrou = 1 if str(data.get('verrouille')) in ('1', 'true', 'on', 'True') else 0
    conn = get_db()
    try:
        user_id = _uid()
        bloc = conn.execute(
            'SELECT b.*, t.type AS tache_type FROM planif_blocs b '
            'JOIN planif_taches t ON b.tache_id = t.id '
            'WHERE b.id = ? AND b.user_id = ?',
            (bloc_id, user_id)
        ).fetchone()
        if not bloc:
            return jsonify({'ok': False, 'erreur': 'Bloc introuvable.'}), 404
        # Un evenement fixe reste verrouille par nature.
        if bloc['tache_type'] == 'evenement':
            return jsonify({'ok': False, 'erreur': "Un événement fixe est toujours verrouillé."}), 400
        conn.execute('UPDATE planif_blocs SET verrouille = ? WHERE id = ?', (verrou, bloc_id))
        conn.commit()
        non_planifie = _replanifier(conn, user_id)
        return jsonify({'ok': True, 'non_planifie': non_planifie})
    finally:
        conn.close()


# ── Routes : replanification, horaires, recurrences ────────────────────────

@planificateur_bp.route('/planificateur/api/replanifier', methods=['POST'])
@planif_required
def api_replanifier():
    """Replanifie l'ensemble des taches."""
    conn = get_db()
    try:
        non_planifie = _replanifier(conn, _uid())
        return jsonify({'ok': True, 'non_planifie': non_planifie})
    finally:
        conn.close()


@planificateur_bp.route('/planificateur/api/recurrence', methods=['POST'])
@planif_required
def api_creer_recurrence():
    """Cree une tache recurrente puis replanifie."""
    data = _lire_payload()
    conn = get_db()
    try:
        user_id = _uid()
        titre = (data.get('titre') or '').strip()
        if not titre:
            return jsonify({'ok': False, 'erreur': 'Le titre est obligatoire.'}), 400
        frequence = data.get('frequence') if data.get('frequence') in FREQUENCES_VALIDES else 'hebdomadaire'
        duree_min = _parse_int(data.get('duree_min'), 30, mini=5, maxi=24 * 60)
        priorite = data.get('priorite') if data.get('priorite') in PRIORITES_VALIDES else 'normale'
        preference = data.get('preference') if data.get('preference') in PREFERENCES_VALIDES else 'aucune'
        secable = 1 if str(data.get('secable')) in ('1', 'true', 'on', 'True') else 0
        duree_min_bloc = _parse_int(data.get('duree_min_bloc'), 30, mini=5, maxi=duree_min)
        jour_semaine = data.get('jour_semaine')
        jour_semaine = _parse_int(jour_semaine, None, mini=0, maxi=6) if jour_semaine not in (None, '', 'null') else None
        jour_mois = data.get('jour_mois')
        jour_mois = _parse_int(jour_mois, None, mini=1, maxi=28) if jour_mois not in (None, '', 'null') else None
        date_debut = _valide_date(data.get('date_debut')) or aujourd_hui().isoformat()
        date_fin = _valide_date(data.get('date_fin'))

        conn.execute(
            '''INSERT INTO planif_recurrences
               (user_id, titre, description, duree_min, priorite, preference, secable,
                duree_min_bloc, frequence, jour_semaine, jour_mois, date_debut, date_fin, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)''',
            (user_id, titre, (data.get('description') or '').strip(), duree_min, priorite,
             preference, secable, duree_min_bloc, frequence, jour_semaine, jour_mois,
             date_debut, date_fin)
        )
        conn.commit()
        non_planifie = _replanifier(conn, user_id)
        return jsonify({'ok': True, 'non_planifie': non_planifie})
    finally:
        conn.close()


@planificateur_bp.route('/planificateur/api/recurrence/<int:rec_id>/supprimer', methods=['POST'])
@planif_required
def api_supprimer_recurrence(rec_id):
    """Supprime une recurrence et ses occurrences (et leurs blocs, en cascade)."""
    conn = get_db()
    try:
        user_id = _uid()
        rec = conn.execute('SELECT id FROM planif_recurrences WHERE id = ? AND user_id = ?',
                           (rec_id, user_id)).fetchone()
        if not rec:
            return jsonify({'ok': False, 'erreur': 'Recurrence introuvable.'}), 404
        # Supprimer les occurrences non realisees et leurs blocs (FK CASCADE inactif).
        a_faire = conn.execute(
            "SELECT id FROM planif_taches WHERE recurrence_id = ? AND statut = 'a_faire'",
            (rec_id,)
        ).fetchall()
        for occ in a_faire:
            conn.execute('DELETE FROM planif_blocs WHERE tache_id = ?', (occ['id'],))
            conn.execute('DELETE FROM planif_taches WHERE id = ?', (occ['id'],))
        # Detacher les occurrences deja realisees (conservees comme historique).
        conn.execute(
            'UPDATE planif_taches SET recurrence_id = NULL WHERE recurrence_id = ?',
            (rec_id,)
        )
        conn.execute('DELETE FROM planif_recurrences WHERE id = ?', (rec_id,))
        conn.commit()
        non_planifie = _replanifier(conn, user_id)
        return jsonify({'ok': True, 'non_planifie': non_planifie})
    finally:
        conn.close()
