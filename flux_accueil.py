"""
Zone « À l'horizon » de l'accueil sans menu.

Le fil d'actions (`dashboard_actions.construire_actions`) ne montre que ce qui
appelle une décision maintenant. « À l'horizon » montre l'inverse : ce qui ne
demande rien aujourd'hui mais arrive — pour qu'aucune échéance ne soit
découverte en retard.

Deux lignes, à défilement horizontal :
- « RH » : fins de contrat et retours d'absence à préparer ;
- « Échéances » : étapes de subventions et tâches planifiées.

Le seuil de bascule est `JOURS_IMMEDIAT` : en deçà, l'élément appartient au fil
d'actions et n'est pas repris ici, pour ne jamais afficher deux fois la même
échéance.
"""
import logging
from datetime import date, timedelta

from flask import url_for

from utils import aujourd_hui

logger = logging.getLogger(__name__)

# Une échéance à 7 jours ou moins relève du fil d'actions, pas de l'horizon.
JOURS_IMMEDIAT = 7
# Au-delà, l'information devient du bruit.
JOURS_HORIZON = 120

_MOIS_COURTS = ['', 'janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin',
                'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.']


def _to_date(valeur):
    """Parse les 10 premiers caractères (YYYY-MM-DD) ; None si invalide."""
    if not valeur:
        return None
    try:
        return date.fromisoformat(str(valeur)[:10])
    except ValueError:
        return None


def _date_courte(d):
    """date -> « 12 sept. » (l'année n'apparaît que si elle change)."""
    if not d:
        return ''
    if d.year != aujourd_hui().year:
        return f"{d.day} {_MOIS_COURTS[d.month]} {d.year}"
    return f"{d.day} {_MOIS_COURTS[d.month]}"


def _item(titre, detail, echeance, lien, today):
    """Élément d'horizon, coloré par la distance à l'échéance."""
    jours = (echeance - today).days
    return {
        'titre': titre,
        'detail': detail,
        'date': _date_courte(echeance),
        'jours': jours,
        'ton': 'proche' if jours <= 21 else ('moyen' if jours <= 60 else 'lointain'),
        'lien': lien,
    }


def _fins_de_contrat(conn, today, borne_min, borne_max, scope_sql, scope_params):
    """Contrats à durée déterminée qui arrivent à leur terme."""
    rows = conn.execute(
        f'''SELECT c.date_fin, c.type_contrat, u.nom, u.prenom
            FROM contrats c
            JOIN users u ON u.id = c.user_id
            WHERE c.date_fin IS NOT NULL AND c.date_fin != ''
              AND c.date_fin > ? AND c.date_fin <= ?
              AND u.actif = 1 AND u.profil != 'prestataire'
              {scope_sql}
            ORDER BY c.date_fin ASC
            LIMIT 12''',
        (borne_min.isoformat(), borne_max.isoformat()) + scope_params
    ).fetchall()
    items = []
    for r in rows:
        fin = _to_date(r['date_fin'])
        if not fin:
            continue
        type_contrat = (r['type_contrat'] or 'contrat').strip()
        items.append(_item(
            f"Fin de {type_contrat} — {r['prenom']} {r['nom']}",
            'Renouveler, transformer ou solder',
            fin,
            url_for('infos_salaries_bp.infos_salaries'),
            today,
        ))
    return items


def _retours_absence(conn, today, borne_min, borne_max, scope_sql, scope_params):
    """Retours d'absence longue (plus de deux semaines) à préparer."""
    rows = conn.execute(
        f'''SELECT a.date_fin, a.motif, a.jours_ouvres, u.nom, u.prenom
            FROM absences a
            JOIN users u ON u.id = a.user_id
            WHERE a.date_fin > ? AND a.date_fin <= ?
              AND a.jours_ouvres >= 10
              AND u.actif = 1
              {scope_sql}
            ORDER BY a.date_fin ASC
            LIMIT 8''',
        (borne_min.isoformat(), borne_max.isoformat()) + scope_params
    ).fetchall()
    items = []
    for r in rows:
        fin = _to_date(r['date_fin'])
        if not fin:
            continue
        items.append(_item(
            f"Retour de {r['prenom']} {r['nom']}",
            f"{(r['motif'] or 'absence').capitalize()} — reprise à organiser",
            fin,
            url_for('absences_bp.absences'),
            today,
        ))
    return items


def _etapes_subventions(conn, today, borne_min, borne_max, profil, user_id):
    """Étapes de subventions dont l'échéance n'est pas encore imminente."""
    if profil == 'responsable':
        scope = 'AND (s.assignee_1_id = ? OR s.assignee_2_id = ? OR se.assignee_id = ?)'
        params = (user_id, user_id, user_id)
    else:
        scope, params = '', ()
    rows = conn.execute(
        f'''SELECT se.nom AS etape, se.date_echeance, s.nom AS sub_nom, s.annee_action
            FROM subventions_sous_elements se
            JOIN subventions s ON s.id = se.subvention_id
            WHERE se.date_echeance IS NOT NULL AND se.date_echeance != ''
              AND se.date_echeance > ? AND se.date_echeance <= ?
              AND se.statut != 'fait'
              AND s.groupe != 'refusee'
              {scope}
            ORDER BY se.date_echeance ASC
            LIMIT 12''',
        (borne_min.isoformat(), borne_max.isoformat()) + params
    ).fetchall()
    # La page subventions filtre par année : on cible celle du dossier si elle
    # est dans la plage du filtre, sinon « toutes ».
    annee_min, annee_max = today.year - 3, today.year + 2
    items = []
    for r in rows:
        ech = _to_date(r['date_echeance'])
        if not ech:
            continue
        annee = (r['annee_action'] or '').strip()
        if annee.isdigit() and len(annee) == 4 and annee_min <= int(annee) <= annee_max:
            lien = url_for('subventions_bp.gestion_subventions', annee=annee)
        else:
            lien = url_for('subventions_bp.gestion_subventions', annee='toutes')
        items.append(_item(
            f"{r['sub_nom']} — {r['etape']}",
            f"Subvention{f' {annee}' if annee else ''}",
            ech, lien, today,
        ))
    return items


def _taches_planifiees(conn, today, borne_min, borne_max, user_id):
    """Tâches du planificateur dont l'échéance approche."""
    if not user_id:
        return []
    rows = conn.execute(
        '''SELECT titre, deadline, priorite
           FROM planif_taches
           WHERE user_id = ? AND statut NOT IN ('fait', 'annule')
             AND deadline IS NOT NULL AND deadline != ''
             AND deadline > ? AND deadline <= ?
           ORDER BY deadline ASC
           LIMIT 8''',
        (user_id, borne_min.isoformat(), borne_max.isoformat())
    ).fetchall()
    items = []
    for r in rows:
        ech = _to_date(r['deadline'])
        if not ech:
            continue
        priorite = (r['priorite'] or 'normale').replace('_', ' ')
        items.append(_item(
            r['titre'],
            f"Tâche planifiée — priorité {priorite}",
            ech,
            url_for('planificateur_bp.planificateur'),
            today,
        ))
    return items


def construire_horizon(conn, profil, user_id, secteur_id=None):
    """Retourne les deux lignes de la zone « À l'horizon ».

    Chaque ligne est `{'titre', 'items'}` ; une ligne sans élément est omise.
    Aucune de ces lectures ne doit faire tomber l'accueil : une table absente
    (base non migrée) neutralise seulement la ligne concernée.
    """
    today = aujourd_hui()
    borne_min = today + timedelta(days=JOURS_IMMEDIAT)
    borne_max = today + timedelta(days=JOURS_HORIZON)

    # Un responsable ne voit que son équipe ; direction et comptabilité voient tout.
    if profil == 'responsable':
        scope_sql = 'AND (u.secteur_id = ? OR u.responsable_id = ?)'
        scope_params = (secteur_id, user_id)
    else:
        scope_sql, scope_params = '', ()

    lignes = []

    rh = []
    for lecture, args in ((_fins_de_contrat, (scope_sql, scope_params)),
                          (_retours_absence, (scope_sql, scope_params))):
        try:
            rh.extend(lecture(conn, today, borne_min, borne_max, *args))
        except Exception:
            logger.warning("Horizon RH : lecture ignorée", exc_info=True)
    if rh:
        rh.sort(key=lambda i: i['jours'])
        lignes.append({'titre': 'RH', 'items': rh[:12]})

    echeances = []
    try:
        echeances.extend(_etapes_subventions(conn, today, borne_min, borne_max,
                                             profil, user_id))
    except Exception:
        logger.warning("Horizon subventions : lecture ignorée", exc_info=True)
    try:
        echeances.extend(_taches_planifiees(conn, today, borne_min, borne_max, user_id))
    except Exception:
        logger.warning("Horizon planificateur : lecture ignorée", exc_info=True)
    if echeances:
        echeances.sort(key=lambda i: i['jours'])
        lignes.append({'titre': 'Échéances', 'items': echeances[:12]})

    return lignes


def separer_actions(actions):
    """Sépare le fil d'actions de ce qui relève de l'horizon.

    Les étapes de subventions lointaines remontent déjà dans « À l'horizon » :
    les laisser dans le fil ferait doublon et noierait les vraies décisions. Le
    reste (demandes à valider, factures, relances, surcharges) reste dans le fil
    quelle que soit son urgence — ce sont des décisions, pas des échéances.
    """
    return [a for a in actions
            if not (a.get('categorie') == 'subvention' and a.get('urgence') == 'normal')]
