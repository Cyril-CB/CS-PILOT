"""
Construction du panneau « Actions à faire » des tableaux de bord
(direction / responsable / comptable).

Agrège, par profil, les éléments réellement actionnables :
- les demandes de récupération / congé en attente de validation ;
- les étapes de subventions à échéance et non terminées.

Chaque item porte un libellé, un détail (date), un lien et un niveau d'urgence
(retard / urgent / normal) pour le code couleur. Le tri place les plus urgents
en tête.
"""
from datetime import date

from flask import url_for

from utils import aujourd_hui

_ORDRE_URGENCE = {'retard': 0, 'urgent': 1, 'normal': 2}


def _to_date(valeur):
    """Parse les 10 premiers caractères (YYYY-MM-DD) ; None si invalide."""
    if not valeur:
        return None
    try:
        return date.fromisoformat(str(valeur)[:10])
    except ValueError:
        return None


def _fr(d):
    """date -> 'JJ/MM/AAAA'."""
    return d.strftime('%d/%m/%Y') if d else ''


def _urgence_echeance(d, today):
    if not d:
        return 'normal'
    jours = (d - today).days
    if jours < 0:
        return 'retard'
    if jours <= 7:
        return 'urgent'
    return 'normal'


def _urgence_depot(d, today):
    if not d:
        return 'normal'
    jours = (today - d).days
    if jours > 14:
        return 'retard'
    if jours > 7:
        return 'urgent'
    return 'normal'


def construire_actions(conn, profil, user_id, secteur_id=None):
    """Retourne la liste des actions à faire du tableau de bord d'un profil.

    - directeur / comptable : toutes les demandes en attente + toutes les
      échéances de subventions.
    - responsable : demandes de son secteur + subventions dont il est assigné.
    """
    actions = []
    today = aujourd_hui()

    # 1. Demandes de récupération / congé à valider.
    if profil == 'responsable':
        statut_clause = "d.statut = 'en_attente_responsable'"
        scope_clause = 'AND u.secteur_id = ?'
        scope_params = (secteur_id,)
    else:  # directeur / comptable
        statut_clause = "d.statut IN ('en_attente_responsable', 'en_attente_direction')"
        scope_clause = ''
        scope_params = ()

    for table, type_lbl in (('demandes_recup', 'récupération'), ('demandes_conges', 'congé')):
        rows = conn.execute(
            f"""SELECT d.date_demande, u.nom, u.prenom
                FROM {table} d JOIN users u ON u.id = d.user_id
                WHERE {statut_clause} {scope_clause}
                ORDER BY d.date_demande ASC
                LIMIT 25""",
            scope_params
        ).fetchall()
        for r in rows:
            depot = _to_date(r['date_demande'])
            actions.append({
                'categorie': 'validation',
                'icone': '📋',
                'titre': f"Demande de {type_lbl} : {r['prenom']} {r['nom']}",
                'detail': f"déposée le {_fr(depot)}" if depot else "en attente de validation",
                'lien': url_for('recup_bp.validation_demandes_recup'),
                'lien_texte': 'Valider',
                'urgence': _urgence_depot(depot, today),
            })

    # 2. Subventions : étapes (sous-éléments) à échéance et non terminées.
    if profil == 'responsable':
        sub_scope = 'AND (s.assignee_1_id = ? OR s.assignee_2_id = ?)'
        sub_params = (user_id, user_id)
    else:
        sub_scope = ''
        sub_params = ()

    rows = conn.execute(
        f"""SELECT se.nom AS etape, se.date_echeance, s.nom AS sub_nom, s.annee_action
            FROM subventions_sous_elements se
            JOIN subventions s ON s.id = se.subvention_id
            WHERE se.date_echeance IS NOT NULL AND se.date_echeance != ''
              AND se.statut != 'fait'
              AND s.groupe IN ('nouveau_projet', 'en_cours')
              {sub_scope}
            ORDER BY se.date_echeance ASC
            LIMIT 25""",
        sub_params
    ).fetchall()
    for r in rows:
        ech = _to_date(r['date_echeance'])
        annee = f" ({r['annee_action']})" if r['annee_action'] else ''
        actions.append({
            'categorie': 'subvention',
            'icone': '💶',
            'titre': f"{r['sub_nom']}{annee} — {r['etape']}",
            'detail': f"échéance le {_fr(ech)}" if ech else '',
            'lien': url_for('subventions_bp.gestion_subventions'),
            'lien_texte': 'Voir',
            'urgence': _urgence_echeance(ech, today),
        })

    # Les plus urgents d'abord, puis par ordre d'insertion (déjà trié par date).
    actions.sort(key=lambda a: _ORDRE_URGENCE.get(a['urgence'], 2))
    return actions
