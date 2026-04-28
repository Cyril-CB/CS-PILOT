"""
Gestion des délégations de missions.
"""
from database import get_db


MISSION_SUIVI_COMMANDES_FOURNITURES = 'suivi_commandes_fournitures'

MISSIONS = [
    {
        'key': MISSION_SUIVI_COMMANDES_FOURNITURES,
        'label': 'Suivi et commande des fournitures',
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
