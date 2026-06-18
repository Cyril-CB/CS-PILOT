"""
Module CSE (Comité Social et Économique).

Accessible depuis le menu RH & Paie :
- La direction et le comptable désignent les membres du CSE (ajout / suppression).
- Les membres du CSE disposent d'un espace dédié :
    * un message à l'attention des salariés (avec date de validité, un seul actif
      à la fois, archivage automatique des messages expirés) ;
    * un budget simplifié (soldes de départ banque / caisse, entrées / sorties) ;
    * un bilan annuel imprimable reprenant l'ensemble des mouvements de l'année.
"""
import re
from datetime import date, datetime

from flask import (
    Blueprint, flash, redirect, render_template, request, session, url_for
)

from access_log import (
    ACTION_AJOUT_MEMBRE_CSE,
    ACTION_RETRAIT_MEMBRE_CSE,
    journaliser_action,
)
from database import get_db
from utils import login_required

cse_bp = Blueprint('cse_bp', __name__)

# Profils habilités à gérer la composition du CSE (désignation des membres).
PROFILS_GESTION = ('directeur', 'comptable')

# Comptes du budget du CSE.
COMPTES = {'banque': 'Banque', 'caisse': 'Caisse'}
# Types de mouvement.
TYPES_MOUVEMENT = {'entree': 'Entrée', 'sortie': 'Sortie'}


# ──────────────────────────────────────────────────────────────────────────
#  Helpers d'accès
# ──────────────────────────────────────────────────────────────────────────

def _is_gestionnaire():
    """La direction et le comptable gèrent la composition du CSE."""
    return session.get('profil') in PROFILS_GESTION


def est_membre_cse(conn, user_id):
    """Indique si l'utilisateur est désigné comme membre du CSE."""
    if not user_id:
        return False
    row = conn.execute(
        "SELECT 1 FROM cse_membres WHERE user_id = ?", (user_id,)
    ).fetchone()
    return row is not None


def _peut_acceder(conn):
    """Accès au module : gestionnaire (direction/comptable) ou membre du CSE."""
    return _is_gestionnaire() or est_membre_cse(conn, session.get('user_id'))


# ──────────────────────────────────────────────────────────────────────────
#  Helpers de formatage / validation
# ──────────────────────────────────────────────────────────────────────────

def _today():
    return date.today().isoformat()


def _format_euro(value):
    """Formate un montant en euros à la française : 1 234,56 €."""
    if value is None:
        value = 0
    formatted = f"{value:,.2f}".replace(',', ' ').replace('.', ',')
    return f"{formatted} €"


def _parse_montant(raw_value, *, signe_autorise=False, zero_autorise=False):
    """Convertit une saisie monétaire en float.

    Accepte la virgule ou le point décimal, max 2 décimales. Lève ValueError
    si la saisie est vide ou invalide. Par défaut, refuse les montants négatifs
    et nuls (mouvements). Les soldes de départ autorisent négatif et zéro.
    """
    value = (raw_value or '').strip()
    for sep in (' ', ' ', ' ', '€'):
        value = value.replace(sep, '')
    if not value:
        raise ValueError

    negatif = False
    if value.startswith('-'):
        if not signe_autorise:
            raise ValueError
        negatif = True
        value = value[1:]

    if value.count(',') > 1 or value.count('.') > 1 or (',' in value and '.' in value):
        raise ValueError

    normalized = value.replace(',', '.')
    if not re.fullmatch(r'\d+(?:\.\d{1,2})?', normalized):
        raise ValueError

    montant = float(normalized)
    if montant == 0 and not zero_autorise:
        raise ValueError
    return -montant if negatif else montant


def _parse_date(raw_value):
    """Valide une date 'YYYY-MM-DD' et la retourne normalisée."""
    value = (raw_value or '').strip()
    try:
        return datetime.strptime(value, '%Y-%m-%d').strftime('%Y-%m-%d')
    except ValueError:
        raise ValueError


# ──────────────────────────────────────────────────────────────────────────
#  Helpers métier : membres
# ──────────────────────────────────────────────────────────────────────────

def _get_membres(conn):
    """Liste des membres du CSE avec les informations du salarié."""
    return conn.execute(
        '''
        SELECT m.id, m.user_id, m.created_at,
               u.prenom, u.nom, u.profil
        FROM cse_membres m
        JOIN users u ON u.id = m.user_id
        ORDER BY u.nom COLLATE NOCASE, u.prenom COLLATE NOCASE
        '''
    ).fetchall()


def _get_salaries_disponibles(conn):
    """Salariés actifs pouvant être désignés membres (hors prestataires et
    membres déjà désignés)."""
    return conn.execute(
        '''
        SELECT id, prenom, nom, profil
        FROM users
        WHERE actif = 1
          AND profil != 'prestataire'
          AND id NOT IN (SELECT user_id FROM cse_membres)
        ORDER BY nom COLLATE NOCASE, prenom COLLATE NOCASE
        '''
    ).fetchall()


# ──────────────────────────────────────────────────────────────────────────
#  Helpers métier : messages
# ──────────────────────────────────────────────────────────────────────────

def _archiver_messages_expires(conn):
    """Archive les messages dont la date de validité est dépassée."""
    conn.execute(
        '''
        UPDATE cse_messages
        SET statut = 'archive',
            archive_le = COALESCE(archive_le, ?)
        WHERE statut = 'actif' AND date_validite < ?
        ''',
        (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), _today())
    )
    conn.commit()


def get_message_actif(conn):
    """Retourne le message du CSE actuellement affichable, ou None.

    Un seul message peut être actif : statut 'actif' et date de validité non
    dépassée. Les messages expirés sont filtrés par la date.
    """
    return conn.execute(
        '''
        SELECT m.*, u.prenom AS auteur_prenom, u.nom AS auteur_nom
        FROM cse_messages m
        LEFT JOIN users u ON u.id = m.cree_par
        WHERE m.statut = 'actif' AND m.date_validite >= ?
        ORDER BY m.created_at DESC, m.id DESC
        LIMIT 1
        ''',
        (_today(),)
    ).fetchone()


# ──────────────────────────────────────────────────────────────────────────
#  Helpers métier : budget
# ──────────────────────────────────────────────────────────────────────────

def _get_soldes_initiaux(conn):
    """Retourne les soldes de départ par compte : {compte: row|None}."""
    rows = conn.execute("SELECT * FROM cse_soldes_initiaux").fetchall()
    par_compte = {r['compte']: r for r in rows}
    return {compte: par_compte.get(compte) for compte in COMPTES}


def _calculer_soldes_courants(conn):
    """Solde courant par compte = solde de départ + entrées - sorties."""
    soldes_init = _get_soldes_initiaux(conn)
    soldes = {}
    for compte in COMPTES:
        base = soldes_init[compte]['montant'] if soldes_init[compte] else 0.0
        agg = conn.execute(
            '''
            SELECT
                COALESCE(SUM(CASE WHEN type = 'entree' THEN montant ELSE 0 END), 0) AS entrees,
                COALESCE(SUM(CASE WHEN type = 'sortie' THEN montant ELSE 0 END), 0) AS sorties
            FROM cse_mouvements WHERE compte = ?
            ''',
            (compte,)
        ).fetchone()
        soldes[compte] = base + agg['entrees'] - agg['sorties']
    soldes['total'] = soldes['banque'] + soldes['caisse']
    return soldes


def _annees_disponibles(conn):
    """Années pour lesquelles un bilan est pertinent (dates des opérations)."""
    annees = set()
    for r in conn.execute(
        "SELECT DISTINCT substr(date_mouvement, 1, 4) AS a FROM cse_mouvements"
    ).fetchall():
        if r['a']:
            annees.add(r['a'])
    for r in conn.execute(
        "SELECT DISTINCT substr(date_solde, 1, 4) AS a FROM cse_soldes_initiaux"
    ).fetchall():
        if r['a']:
            annees.add(r['a'])
    annees.add(str(date.today().year))
    return sorted(annees, reverse=True)


def _calculer_bilan_annuel(conn, annee):
    """Construit le bilan d'une année : mouvements, totaux et soldes."""
    annee = str(annee)
    mouvements = conn.execute(
        '''
        SELECT * FROM cse_mouvements
        WHERE substr(date_mouvement, 1, 4) = ?
        ORDER BY date_mouvement ASC, id ASC
        ''',
        (annee,)
    ).fetchall()

    fin_annee = f"{annee}-12-31"
    soldes_init = _get_soldes_initiaux(conn)

    comptes = {}
    for compte in COMPTES:
        entrees = sum(m['montant'] for m in mouvements
                      if m['compte'] == compte and m['type'] == 'entree')
        sorties = sum(m['montant'] for m in mouvements
                      if m['compte'] == compte and m['type'] == 'sortie')

        # Le solde de départ ne compte que si sa date de référence est atteinte
        # à la fin de l'année du bilan (sinon il gonflerait les années antérieures).
        solde_row = soldes_init[compte]
        base = solde_row['montant'] if (solde_row and solde_row['date_solde'] <= fin_annee) else 0.0
        agg = conn.execute(
            '''
            SELECT
                COALESCE(SUM(CASE WHEN type = 'entree' THEN montant ELSE 0 END), 0) AS e,
                COALESCE(SUM(CASE WHEN type = 'sortie' THEN montant ELSE 0 END), 0) AS s
            FROM cse_mouvements
            WHERE compte = ? AND date_mouvement <= ?
            ''',
            (compte, fin_annee)
        ).fetchone()
        solde_fin = base + agg['e'] - agg['s']
        solde_debut = solde_fin - (entrees - sorties)

        comptes[compte] = {
            'entrees': entrees,
            'sorties': sorties,
            'variation': entrees - sorties,
            'solde_debut': solde_debut,
            'solde_fin': solde_fin,
            'entrees_fmt': _format_euro(entrees),
            'sorties_fmt': _format_euro(sorties),
            'variation_fmt': _format_euro(entrees - sorties),
            'solde_debut_fmt': _format_euro(solde_debut),
            'solde_fin_fmt': _format_euro(solde_fin),
        }

    total = {}
    for key in ('entrees', 'sorties', 'variation', 'solde_debut', 'solde_fin'):
        total[key] = sum(c[key] for c in comptes.values())
        total[key + '_fmt'] = _format_euro(total[key])

    lignes = []
    for m in mouvements:
        lignes.append({
            'id': m['id'],
            'date': m['date_mouvement'],
            'compte': m['compte'],
            'compte_label': COMPTES.get(m['compte'], m['compte']),
            'type': m['type'],
            'type_label': TYPES_MOUVEMENT.get(m['type'], m['type']),
            'montant': m['montant'],
            'montant_fmt': _format_euro(m['montant']),
            'commentaire': m['commentaire'] or '',
        })

    return {'annee': annee, 'lignes': lignes, 'comptes': comptes, 'total': total}


# ──────────────────────────────────────────────────────────────────────────
#  Routes : accueil + gestion des membres
# ──────────────────────────────────────────────────────────────────────────

@cse_bp.route('/cse')
@login_required
def cse_accueil():
    """Page d'accueil du module CSE."""
    conn = get_db()
    try:
        if not _peut_acceder(conn):
            flash("Accès réservé au CSE.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))

        is_gestionnaire = _is_gestionnaire()
        is_membre = est_membre_cse(conn, session.get('user_id'))

        membres = _get_membres(conn) if is_gestionnaire else []
        salaries = _get_salaries_disponibles(conn) if is_gestionnaire else []

        message_actif = None
        if is_membre:
            _archiver_messages_expires(conn)
            message_actif = get_message_actif(conn)
    finally:
        conn.close()

    return render_template(
        'cse.html',
        is_gestionnaire=is_gestionnaire,
        is_membre=is_membre,
        membres=membres,
        salaries=salaries,
        message_actif=message_actif,
        profils_labels={'directeur': 'Direction', 'comptable': 'Comptable',
                        'responsable': 'Responsable', 'salarie': 'Salarié'},
    )


@cse_bp.route('/cse/membres/ajouter', methods=['POST'])
@login_required
def ajouter_membre():
    """Désigne un salarié comme membre du CSE (direction / comptable)."""
    if not _is_gestionnaire():
        flash("Seules la direction et la comptabilité peuvent désigner les membres du CSE.", "error")
        return redirect(url_for('cse_bp.cse_accueil'))

    try:
        user_id = int(request.form.get('user_id', ''))
    except (TypeError, ValueError):
        flash("Veuillez sélectionner un salarié.", "error")
        return redirect(url_for('cse_bp.cse_accueil'))

    conn = get_db()
    try:
        salarie = conn.execute(
            "SELECT id, prenom, nom, profil FROM users WHERE id = ? AND actif = 1 AND profil != 'prestataire'",
            (user_id,)
        ).fetchone()
        if not salarie:
            flash("Salarié introuvable.", "error")
            return redirect(url_for('cse_bp.cse_accueil'))

        deja = conn.execute(
            "SELECT 1 FROM cse_membres WHERE user_id = ?", (user_id,)
        ).fetchone()
        if deja:
            flash(f"{salarie['prenom']} {salarie['nom']} fait déjà partie du CSE.", "warning")
            return redirect(url_for('cse_bp.cse_accueil'))

        conn.execute(
            "INSERT INTO cse_membres (user_id, ajoute_par) VALUES (?, ?)",
            (user_id, session['user_id'])
        )
        journaliser_action(
            conn, ACTION_AJOUT_MEMBRE_CSE,
            cible_type='user', cible_id=user_id,
            details=f"profil={salarie['profil']}",
        )
        conn.commit()
        flash(f"{salarie['prenom']} {salarie['nom']} a été ajouté(e) au CSE.", "success")
    finally:
        conn.close()

    return redirect(url_for('cse_bp.cse_accueil'))


@cse_bp.route('/cse/membres/<int:membre_id>/supprimer', methods=['POST'])
@login_required
def supprimer_membre(membre_id):
    """Retire un membre du CSE (direction / comptable)."""
    if not _is_gestionnaire():
        flash("Seules la direction et la comptabilité peuvent modifier les membres du CSE.", "error")
        return redirect(url_for('cse_bp.cse_accueil'))

    conn = get_db()
    try:
        membre = conn.execute(
            '''
            SELECT m.id, m.user_id, u.prenom, u.nom, u.profil
            FROM cse_membres m JOIN users u ON u.id = m.user_id
            WHERE m.id = ?
            ''',
            (membre_id,)
        ).fetchone()
        if not membre:
            flash("Membre introuvable.", "error")
            return redirect(url_for('cse_bp.cse_accueil'))

        conn.execute("DELETE FROM cse_membres WHERE id = ?", (membre_id,))
        journaliser_action(
            conn, ACTION_RETRAIT_MEMBRE_CSE,
            cible_type='user', cible_id=membre['user_id'],
            details=f"profil={membre['profil']}",
        )
        conn.commit()
        flash(f"{membre['prenom']} {membre['nom']} a été retiré(e) du CSE.", "success")
    finally:
        conn.close()

    return redirect(url_for('cse_bp.cse_accueil'))


# ──────────────────────────────────────────────────────────────────────────
#  Routes : messages aux salariés (membres du CSE)
# ──────────────────────────────────────────────────────────────────────────

@cse_bp.route('/cse/messages')
@login_required
def cse_messages():
    """Gestion des messages à l'attention des salariés."""
    conn = get_db()
    try:
        if not est_membre_cse(conn, session.get('user_id')):
            flash("Accès réservé aux membres du CSE.", "error")
            return redirect(url_for('cse_bp.cse_accueil'))

        _archiver_messages_expires(conn)
        message_actif = get_message_actif(conn)

        archives = conn.execute(
            '''
            SELECT m.*, u.prenom AS auteur_prenom, u.nom AS auteur_nom
            FROM cse_messages m
            LEFT JOIN users u ON u.id = m.cree_par
            WHERE NOT (m.statut = 'actif' AND m.date_validite >= ?)
            ORDER BY m.created_at DESC, m.id DESC
            ''',
            (_today(),)
        ).fetchall()
    finally:
        conn.close()

    return render_template(
        'cse_messages.html',
        message_actif=message_actif,
        archives=archives,
        aujourd_hui=_today(),
    )


@cse_bp.route('/cse/messages/creer', methods=['POST'])
@login_required
def creer_message():
    """Publie un nouveau message (archive automatiquement le précédent)."""
    conn = get_db()
    try:
        if not est_membre_cse(conn, session.get('user_id')):
            flash("Accès réservé aux membres du CSE.", "error")
            return redirect(url_for('cse_bp.cse_accueil'))

        titre = (request.form.get('titre') or '').strip()
        contenu = (request.form.get('contenu') or '').strip()
        try:
            date_validite = _parse_date(request.form.get('date_validite'))
        except ValueError:
            flash("La date de validité est invalide.", "error")
            return redirect(url_for('cse_bp.cse_messages'))

        if not contenu:
            flash("Le contenu du message est obligatoire.", "error")
            return redirect(url_for('cse_bp.cse_messages'))
        if date_validite < _today():
            flash("La date de validité doit être aujourd'hui ou dans le futur.", "error")
            return redirect(url_for('cse_bp.cse_messages'))

        # Un seul message actif à la fois : on archive l'éventuel précédent.
        conn.execute(
            '''
            UPDATE cse_messages
            SET statut = 'archive', archive_le = COALESCE(archive_le, ?)
            WHERE statut = 'actif'
            ''',
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),)
        )
        conn.execute(
            '''
            INSERT INTO cse_messages (titre, contenu, date_validite, statut, cree_par)
            VALUES (?, ?, ?, 'actif', ?)
            ''',
            (titre or None, contenu, date_validite, session['user_id'])
        )
        conn.commit()
        flash("Le message a été publié.", "success")
    finally:
        conn.close()

    return redirect(url_for('cse_bp.cse_messages'))


@cse_bp.route('/cse/messages/<int:message_id>/archiver', methods=['POST'])
@login_required
def archiver_message(message_id):
    """Retire (archive) manuellement le message actif."""
    conn = get_db()
    try:
        if not est_membre_cse(conn, session.get('user_id')):
            flash("Accès réservé aux membres du CSE.", "error")
            return redirect(url_for('cse_bp.cse_accueil'))

        message = conn.execute(
            "SELECT id FROM cse_messages WHERE id = ?", (message_id,)
        ).fetchone()
        if not message:
            flash("Message introuvable.", "error")
            return redirect(url_for('cse_bp.cse_messages'))

        conn.execute(
            '''
            UPDATE cse_messages
            SET statut = 'archive', archive_le = COALESCE(archive_le, ?)
            WHERE id = ?
            ''',
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), message_id)
        )
        conn.commit()
        flash("Le message a été retiré et archivé.", "success")
    finally:
        conn.close()

    return redirect(url_for('cse_bp.cse_messages'))


# ──────────────────────────────────────────────────────────────────────────
#  Routes : budget (membres du CSE)
# ──────────────────────────────────────────────────────────────────────────

@cse_bp.route('/cse/budget')
@login_required
def cse_budget():
    """Gestion simplifiée du budget du CSE."""
    conn = get_db()
    try:
        if not est_membre_cse(conn, session.get('user_id')):
            flash("Accès réservé aux membres du CSE.", "error")
            return redirect(url_for('cse_bp.cse_accueil'))

        soldes_init = _get_soldes_initiaux(conn)
        soldes_courants = _calculer_soldes_courants(conn)

        rows = conn.execute(
            '''
            SELECT mv.*, u.prenom, u.nom
            FROM cse_mouvements mv
            LEFT JOIN users u ON u.id = mv.cree_par
            ORDER BY mv.date_mouvement DESC, mv.id DESC
            '''
        ).fetchall()
        annees = _annees_disponibles(conn)
    finally:
        conn.close()

    mouvements = []
    for m in rows:
        mouvements.append({
            'id': m['id'],
            'date': m['date_mouvement'],
            'compte': m['compte'],
            'compte_label': COMPTES.get(m['compte'], m['compte']),
            'type': m['type'],
            'type_label': TYPES_MOUVEMENT.get(m['type'], m['type']),
            'montant': m['montant'],
            'montant_fmt': _format_euro(m['montant']),
            'commentaire': m['commentaire'] or '',
        })

    soldes_init_fmt = {}
    for compte, row in soldes_init.items():
        soldes_init_fmt[compte] = {
            'defini': row is not None,
            'date': row['date_solde'] if row else None,
            'montant': row['montant'] if row else 0.0,
            'montant_fmt': _format_euro(row['montant'] if row else 0.0),
        }

    return render_template(
        'cse_budget.html',
        comptes=COMPTES,
        types_mouvement=TYPES_MOUVEMENT,
        soldes_init=soldes_init_fmt,
        soldes_courants={k: _format_euro(v) for k, v in soldes_courants.items()},
        soldes_courants_val=soldes_courants,
        mouvements=mouvements,
        annees=annees,
        aujourd_hui=_today(),
    )


@cse_bp.route('/cse/budget/solde', methods=['POST'])
@login_required
def definir_solde():
    """Définit (ou met à jour) un solde de départ banque / caisse."""
    conn = get_db()
    try:
        if not est_membre_cse(conn, session.get('user_id')):
            flash("Accès réservé aux membres du CSE.", "error")
            return redirect(url_for('cse_bp.cse_accueil'))

        compte = request.form.get('compte')
        if compte not in COMPTES:
            flash("Compte invalide.", "error")
            return redirect(url_for('cse_bp.cse_budget'))
        try:
            date_solde = _parse_date(request.form.get('date_solde'))
            montant = _parse_montant(
                request.form.get('montant'), signe_autorise=True, zero_autorise=True
            )
        except ValueError:
            flash("La date ou le montant du solde de départ est invalide.", "error")
            return redirect(url_for('cse_bp.cse_budget'))

        conn.execute(
            '''
            INSERT INTO cse_soldes_initiaux (compte, date_solde, montant, updated_par, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(compte) DO UPDATE SET
                date_solde = excluded.date_solde,
                montant = excluded.montant,
                updated_par = excluded.updated_par,
                updated_at = excluded.updated_at
            ''',
            (compte, date_solde, montant, session['user_id'],
             datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        flash(f"Solde de départ « {COMPTES[compte]} » enregistré.", "success")
    finally:
        conn.close()

    return redirect(url_for('cse_bp.cse_budget'))


@cse_bp.route('/cse/budget/mouvement', methods=['POST'])
@login_required
def ajouter_mouvement():
    """Ajoute une entrée ou une sortie au budget du CSE."""
    conn = get_db()
    try:
        if not est_membre_cse(conn, session.get('user_id')):
            flash("Accès réservé aux membres du CSE.", "error")
            return redirect(url_for('cse_bp.cse_accueil'))

        compte = request.form.get('compte')
        type_mvt = request.form.get('type')
        commentaire = (request.form.get('commentaire') or '').strip()

        if compte not in COMPTES:
            flash("Compte invalide.", "error")
            return redirect(url_for('cse_bp.cse_budget'))
        if type_mvt not in TYPES_MOUVEMENT:
            flash("Type de mouvement invalide.", "error")
            return redirect(url_for('cse_bp.cse_budget'))
        try:
            date_mvt = _parse_date(request.form.get('date_mouvement'))
            montant = _parse_montant(request.form.get('montant'))
        except ValueError:
            flash("La date ou le montant du mouvement est invalide.", "error")
            return redirect(url_for('cse_bp.cse_budget'))

        conn.execute(
            '''
            INSERT INTO cse_mouvements (compte, type, date_mouvement, montant, commentaire, cree_par)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (compte, type_mvt, date_mvt, montant, commentaire or None, session['user_id'])
        )
        conn.commit()
        flash("Le mouvement a été enregistré.", "success")
    finally:
        conn.close()

    return redirect(url_for('cse_bp.cse_budget'))


@cse_bp.route('/cse/budget/mouvement/<int:mouvement_id>/supprimer', methods=['POST'])
@login_required
def supprimer_mouvement(mouvement_id):
    """Supprime un mouvement du budget du CSE."""
    conn = get_db()
    try:
        if not est_membre_cse(conn, session.get('user_id')):
            flash("Accès réservé aux membres du CSE.", "error")
            return redirect(url_for('cse_bp.cse_accueil'))

        mvt = conn.execute(
            "SELECT id FROM cse_mouvements WHERE id = ?", (mouvement_id,)
        ).fetchone()
        if not mvt:
            flash("Mouvement introuvable.", "error")
            return redirect(url_for('cse_bp.cse_budget'))

        conn.execute("DELETE FROM cse_mouvements WHERE id = ?", (mouvement_id,))
        conn.commit()
        flash("Le mouvement a été supprimé.", "success")
    finally:
        conn.close()

    return redirect(url_for('cse_bp.cse_budget'))


@cse_bp.route('/cse/bilan')
@login_required
def cse_bilan():
    """Bilan annuel imprimable du budget du CSE."""
    conn = get_db()
    try:
        if not est_membre_cse(conn, session.get('user_id')):
            flash("Accès réservé aux membres du CSE.", "error")
            return redirect(url_for('cse_bp.cse_accueil'))

        annees = _annees_disponibles(conn)
        annee = request.args.get('annee', '').strip()
        if annee not in annees:
            annee = annees[0] if annees else str(date.today().year)

        bilan = _calculer_bilan_annuel(conn, annee)
    finally:
        conn.close()

    return render_template(
        'cse_bilan.html',
        comptes=COMPTES,
        annees=annees,
        annee=annee,
        bilan=bilan,
        genere_le=datetime.now().strftime('%d/%m/%Y à %H:%M'),
    )
