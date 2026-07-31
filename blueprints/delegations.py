"""
Gestion des délégations de missions.
"""
from database import get_db


MISSION_SUIVI_COMMANDES_FOURNITURES = 'suivi_commandes_fournitures'
MISSION_SUIVI_VALIDATIONS_RELANCES = 'suivi_validations_relances'

MISSIONS = [
    {
        'key': MISSION_SUIVI_COMMANDES_FOURNITURES,
        'label': 'Suivi et commande des fournitures',
    },
    {
        'key': MISSION_SUIVI_VALIDATIONS_RELANCES,
        'label': "Suivi des validations (vue d'ensemble) et relances",
    }
]

MISSIONS_MAP = {mission['key']: mission for mission in MISSIONS}


def get_delegation_user_id(mission_key):
    """Retourne l'ID de l'utilisateur délégataire pour une mission."""
    conn = get_db()
    try:
        row = conn.execute(
            'SELECT delegated_user_id FROM delegations_missions WHERE mission_key = ?',
            (mission_key,)
        ).fetchone()
        return row['delegated_user_id'] if row else None
    finally:
        conn.close()


def user_has_delegation(user_id, mission_key):
    """Indique si un utilisateur dispose d'une mission déléguée."""
    if not user_id:
        return False
    return get_delegation_user_id(mission_key) == user_id


def save_delegation(mission_key, delegated_user_id, delegated_by_user_id):
    """Enregistre ou retire une délégation de mission."""
    conn = get_db()
    try:
        if delegated_user_id:
            conn.execute(
                '''
                INSERT INTO delegations_missions (
                    mission_key, delegated_user_id, delegated_by_user_id, updated_at
                )
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(mission_key) DO UPDATE SET
                    delegated_user_id = excluded.delegated_user_id,
                    delegated_by_user_id = excluded.delegated_by_user_id,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (mission_key, delegated_user_id, delegated_by_user_id)
            )
        else:
            conn.execute(
                'DELETE FROM delegations_missions WHERE mission_key = ?',
                (mission_key,)
            )
        conn.commit()
    finally:
        conn.close()


# ── Délégation : réservations de salle récurrentes ─────────────────────────────
# Par défaut, seuls les responsables (et la direction) peuvent créer des
# récurrences. La direction peut déléguer ce droit à un ou plusieurs salariés.

def get_salle_recurrence_user_ids():
    """Retourne la liste des IDs des salariés autorisés à créer des récurrences."""
    conn = get_db()
    try:
        rows = conn.execute(
            'SELECT user_id FROM delegations_salles_recurrence'
        ).fetchall()
        return [row['user_id'] for row in rows]
    finally:
        conn.close()


def user_peut_recurrence_salle(user_id):
    """Indique si un salarié dispose de la délégation des récurrences de salle."""
    if not user_id:
        return False
    conn = get_db()
    try:
        row = conn.execute(
            'SELECT 1 FROM delegations_salles_recurrence WHERE user_id = ?',
            (user_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def save_salle_recurrence_delegations(user_ids, granted_by):
    """Remplace l'ensemble des salariés autorisés à créer des récurrences."""
    conn = get_db()
    try:
        conn.execute('DELETE FROM delegations_salles_recurrence')
        for uid in user_ids:
            conn.execute(
                'INSERT OR IGNORE INTO delegations_salles_recurrence (user_id, granted_by) '
                'VALUES (?, ?)',
                (uid, granted_by)
            )
        conn.commit()
    finally:
        conn.close()


# ── Délégation : gestion complète de la page bénévoles ─────────────────────────
# Par défaut, le répertoire des bénévoles est tenu par la direction et la
# comptabilité (un responsable ne voit que les bénévoles qui lui sont assignés
# et le suivi des heures leur est fermé). Cette délégation confie l'intégralité
# de la page — répertoire ET suivi des heures — à un ou plusieurs salariés.

def get_benevoles_user_ids():
    """Retourne la liste des IDs des salariés délégués à la gestion des bénévoles."""
    conn = get_db()
    try:
        rows = conn.execute('SELECT user_id FROM delegations_benevoles').fetchall()
        return [row['user_id'] for row in rows]
    finally:
        conn.close()


def user_peut_gerer_benevoles(user_id):
    """Indique si un salarié dispose de la délégation de gestion des bénévoles.

    Le profil et l'activité du compte sont revérifiés à chaque appel : une
    délégation accordée hier ne doit pas survivre à la désactivation du compte
    ni à un changement de profil (un prestataire n'a rien à faire dans les
    coordonnées des bénévoles).
    """
    if not user_id:
        return False
    conn = get_db()
    try:
        row = conn.execute(
            '''
            SELECT 1
            FROM delegations_benevoles d
            JOIN users u ON u.id = d.user_id
            WHERE d.user_id = ? AND u.actif = 1
              AND u.profil IN ('salarie', 'responsable')
            ''',
            (user_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def save_benevoles_delegations(user_ids, granted_by):
    """Remplace l'ensemble des salariés délégués à la gestion des bénévoles."""
    conn = get_db()
    try:
        conn.execute('DELETE FROM delegations_benevoles')
        for uid in user_ids:
            conn.execute(
                'INSERT OR IGNORE INTO delegations_benevoles (user_id, granted_by) '
                'VALUES (?, ?)',
                (uid, granted_by)
            )
        conn.commit()
    finally:
        conn.close()
