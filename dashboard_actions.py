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

from blueprints.delegations import (MISSION_SUIVI_VALIDATIONS_RELANCES,
                                    user_has_delegation)
from utils import NOMS_MOIS, aujourd_hui, calculer_solde_recup

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


def _fr_num(x):
    """Nombre -> notation française compacte ('3', '3,5')."""
    return f"{x:g}".replace('.', ',')


def _periode_demande(r):
    """« du 20/07/2026 au 24/07/2026 (5 j) » — ou « le 20/07/2026 (1 j) »."""
    debut, fin = _to_date(r['date_debut']), _to_date(r['date_fin'])
    if not debut:
        return ''
    quand = f"le {_fr(debut)}" if (not fin or fin == debut) else f"du {_fr(debut)} au {_fr(fin)}"
    return f"{quand} ({_fr_num(r['nb_jours'])} j)"


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


def construire_actions(conn, profil, user_id, secteur_id=None,
                       etendu=False, seuils=None, surcharges=None,
                       factures_direction_seulement=False):
    """Retourne la liste des actions à faire du tableau de bord d'un profil.

    - directeur / comptable : toutes les demandes en attente + toutes les
      échéances de subventions.
    - responsable : demandes de son secteur + subventions dont il est assigné.

    En mode « étendu » (centre de contrôle direction), la liste s'enrichit
    d'items actionnables en un clic : factures en attente d'approbation,
    fiches du mois précédent à relancer, salariés en surcharge (liste
    `surcharges` calculée par l'appelant, filtrée par seuil) et soldes de
    congés conventionnels au-dessus du seuil. Chaque item porte alors un
    `id` stable et un `type` ('facture' / 'demande' / 'relance' / 'lien')
    avec les données nécessaires à l'action.

    `factures_direction_seulement` restreint les factures à celles assignées
    à la direction (`assigned_direction = 1`) — utilisé par le digest matinal
    pour n'y mettre que ce que la direction doit valider, sans les factures
    d'un secteur (qui relèvent de son responsable).
    """
    actions = []
    today = aujourd_hui()
    seuils = seuils or {}

    # 1. Demandes de récupération / congé à valider.
    if profil == 'responsable':
        statut_clause = "d.statut = 'en_attente_responsable'"
        scope_clause = 'AND u.secteur_id = ?'
        scope_params = (secteur_id,)
    else:  # directeur / comptable
        statut_clause = "d.statut IN ('en_attente_responsable', 'en_attente_direction')"
        scope_clause = ''
        scope_params = ()

    # Récupérations : dates de la période + solde de récupération du salarié.
    rows = conn.execute(
        f"""SELECT d.id, d.date_demande, d.statut, d.date_debut, d.date_fin,
                   d.nb_jours, d.nb_heures, u.id AS uid, u.nom, u.prenom
            FROM demandes_recup d JOIN users u ON u.id = d.user_id
            WHERE {statut_clause} {scope_clause}
            ORDER BY d.date_demande ASC
            LIMIT 25""",
        scope_params
    ).fetchall()
    for r in rows:
        depot = _to_date(r['date_demande'])
        parts = [p for p in (_periode_demande(r),
                             f"déposée le {_fr(depot)}" if depot else '') if p]
        parts.append('validée responsable, à valider'
                     if r['statut'] == 'en_attente_direction'
                     else 'en attente du responsable')
        try:
            solde_h = calculer_solde_recup(r['uid'])
            if r['nb_heures']:
                parts.append(f"solde récup après validation : "
                             f"{solde_h - r['nb_heures']:.1f} h".replace('.', ','))
            else:
                parts.append(f"solde récup actuel : {solde_h:.1f} h".replace('.', ','))
        except Exception:
            pass   # le solde est une aide, jamais bloquant
        actions.append({
            'id': f"dem-recup-{r['id']}",
            'categorie': 'validation',
            'type': 'demande',
            'demande_id': r['id'],
            'demande_type': 'recup',
            'icone': '📋',
            'titre': f"Demande de récupération : {r['prenom']} {r['nom']}",
            'detail': ' — '.join(parts),
            'lien': url_for('recup_bp.validation_demandes_recup'),
            'lien_texte': 'Valider',
            'urgence': _urgence_depot(depot, today),
        })

    # Congés : dates + solde du compteur concerné APRÈS validation (CP ou
    # congés conventionnels), pour valider en connaissance de cause.
    rows = conn.execute(
        f"""SELECT d.id, d.date_demande, d.statut, d.date_debut, d.date_fin,
                   d.nb_jours, d.type_conge, u.nom, u.prenom,
                   COALESCE(u.cp_a_prendre, 0) AS cp_a_prendre,
                   COALESCE(u.cp_pris, 0) AS cp_pris,
                   COALESCE(u.cc_solde, 0) AS cc_solde
            FROM demandes_conges d JOIN users u ON u.id = d.user_id
            WHERE {statut_clause} {scope_clause}
            ORDER BY d.date_demande ASC
            LIMIT 25""",
        scope_params
    ).fetchall()
    for r in rows:
        depot = _to_date(r['date_demande'])
        parts = [p for p in (_periode_demande(r),
                             f"déposée le {_fr(depot)}" if depot else '') if p]
        parts.append('validée responsable, à valider'
                     if r['statut'] == 'en_attente_direction'
                     else 'en attente du responsable')
        if r['type_conge'] == 'Congé payé':
            apres = r['cp_a_prendre'] - r['cp_pris'] - r['nb_jours']
            parts.append(f"solde CP après validation : {_fr_num(apres)} j")
        elif r['type_conge'] == 'Congé conventionnel':
            apres = r['cc_solde'] - r['nb_jours']
            parts.append(f"solde CC après validation : {_fr_num(apres)} j")
        type_lbl = (r['type_conge'] or 'congé').lower()
        actions.append({
            'id': f"dem-conge-{r['id']}",
            'categorie': 'validation',
            'type': 'demande',
            'demande_id': r['id'],
            'demande_type': 'conge',
            'icone': '📋',
            'titre': f"Demande de {type_lbl} : {r['prenom']} {r['nom']}",
            'detail': ' — '.join(parts),
            'lien': url_for('recup_bp.validation_demandes_recup'),
            'lien_texte': 'Valider',
            'urgence': _urgence_depot(depot, today),
        })

    # 2. Subventions : étapes (sous-éléments) à échéance et non terminées.
    # Le responsable voit les étapes des subventions dont il est assigné (parent)
    # ainsi que celles des sous-éléments qui lui sont directement attribués — en
    # cohérence avec la notification d'attribution par e-mail.
    if profil == 'responsable':
        sub_scope = 'AND (s.assignee_1_id = ? OR s.assignee_2_id = ? OR se.assignee_id = ?)'
        sub_params = (user_id, user_id, user_id)
    else:
        sub_scope = ''
        sub_params = ()

    # On exclut uniquement les subventions refusées : une subvention acceptée
    # garde des échéances actionnables (bilans qualitatif / financier).
    rows = conn.execute(
        f"""SELECT se.id, se.nom AS etape, se.date_echeance, s.nom AS sub_nom, s.annee_action
            FROM subventions_sous_elements se
            JOIN subventions s ON s.id = se.subvention_id
            WHERE se.date_echeance IS NOT NULL AND se.date_echeance != ''
              AND se.statut != 'fait'
              AND s.groupe != 'refusee'
              {sub_scope}
            ORDER BY se.date_echeance ASC
            LIMIT 25""",
        sub_params
    ).fetchall()
    # La page subventions filtre par année (année courante par défaut). Pour que
    # la subvention pointée reste visible, on cible son année si elle est dans la
    # plage du filtre (N-3..N+2), sinon « toutes » (année absente ou hors plage).
    annee_min, annee_max = today.year - 3, today.year + 2
    for r in rows:
        ech = _to_date(r['date_echeance'])
        annee = f" ({r['annee_action']})" if r['annee_action'] else ''
        annee_sub = (r['annee_action'] or '').strip()
        if annee_sub.isdigit() and len(annee_sub) == 4 and annee_min <= int(annee_sub) <= annee_max:
            lien_sub = url_for('subventions_bp.gestion_subventions', annee=annee_sub)
        else:
            lien_sub = url_for('subventions_bp.gestion_subventions', annee='toutes')
        actions.append({
            'id': f"sub-{r['id']}",
            'categorie': 'subvention',
            'type': 'subvention',
            'se_id': r['id'],
            'icone': '💶',
            'titre': f"{r['sub_nom']}{annee} — {r['etape']}",
            'detail': f"échéance le {_fr(ech)}" if ech else '',
            'lien': lien_sub,
            'lien_texte': 'Voir',
            'urgence': _urgence_echeance(ech, today),
        })

    if etendu and profil in ('directeur', 'comptable'):
        actions.extend(_actions_etendues(conn, profil, user_id, today, seuils, surcharges,
                                         factures_direction_seulement))

    # Les plus urgents d'abord, puis par ordre d'insertion (déjà trié par date).
    actions.sort(key=lambda a: _ORDRE_URGENCE.get(a['urgence'], 2))
    return actions


def _actions_etendues(conn, profil, user_id, today, seuils, surcharges,
                      factures_direction_seulement=False):
    """Items supplémentaires du centre de contrôle direction / comptable."""
    actions = []

    # 3. Factures en attente d'approbation (approbation en un clic). Même
    # périmètre que la page d'approbation : une facture sans secteur ni
    # assignation direction n'est pas encore entrée dans le circuit et ne doit
    # pas pouvoir être approuvée depuis le tableau de bord.
    # Le digest ne retient que les factures de la direction : celles d'un
    # secteur sont à valider par son responsable, pas par la direction.
    scope_factures = ('AND f.assigned_direction = 1' if factures_direction_seulement
                      else 'AND (f.secteur_id IS NOT NULL OR f.assigned_direction = 1)')
    rows = conn.execute(f'''
        SELECT f.id, f.numero_facture, f.montant_ttc, f.date_echeance,
               fr.nom AS fournisseur_nom
        FROM factures f
        LEFT JOIN fournisseurs fr ON f.fournisseur_id = fr.id
        WHERE f.approbation = 'en_attente'
          {scope_factures}
        ORDER BY f.date_echeance ASC, f.date_facture ASC
        LIMIT 15
    ''').fetchall()
    for r in rows:
        ech = _to_date(r['date_echeance'])
        montant = f"{(r['montant_ttc'] or 0):,.2f}".replace(',', ' ').replace('.', ',')
        if ech:
            jours = (ech - today).days
            if jours < 0:
                detail = f"échéance dépassée de {-jours} jour(s) ({_fr(ech)})"
            else:
                detail = f"échéance dans {jours} jour(s) ({_fr(ech)})"
        else:
            detail = "en attente d'approbation"
        actions.append({
            'id': f"fact-{r['id']}",
            'categorie': 'facture',
            'type': 'facture',
            'facture_id': r['id'],
            'icone': '🧾',
            'titre': f"Facture {r['fournisseur_nom'] or r['numero_facture'] or ''} — {montant} €",
            'detail': detail,
            'lien': url_for('factures_bp.detail_facture', facture_id=r['id']),
            'lien_texte': 'Détail',
            'urgence': _urgence_echeance(ech, today),
        })

    # 4. Fiches du mois précédent non validées : relance des responsables.
    mois_prec = today.month - 1 or 12
    annee_prec = today.year if today.month > 1 else today.year - 1
    fiches = conn.execute('''
        SELECT COUNT(*) AS nb FROM users u
        WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
          AND NOT EXISTS (
              SELECT 1 FROM validations v
              WHERE v.user_id = u.id AND v.mois = ? AND v.annee = ? AND v.bloque = 1
          )
    ''', (mois_prec, annee_prec)).fetchone()
    if fiches['nb'] > 0:
        # L'endpoint de relance est réservé à la direction (ou à un délégué) :
        # pour les autres (comptable sans délégation), l'item reste informatif
        # avec un lien vers la vue d'ensemble plutôt qu'un bouton voué au 403.
        peut_relancer = (profil == 'directeur'
                         or user_has_delegation(user_id, MISSION_SUIVI_VALIDATIONS_RELANCES))
        item = {
            'id': f"relance-{annee_prec}-{mois_prec:02d}",
            'categorie': 'validation',
            'type': 'relance' if peut_relancer else 'lien',
            'icone': '✅',
            'titre': f"{fiches['nb']} fiche(s) de {NOMS_MOIS[mois_prec].lower()} non validée(s)",
            'detail': "responsables à relancer par email" if peut_relancer
                      else "en attente de validation",
            'lien': url_for('validation_bp.vue_ensemble_validation'),
            'lien_texte': 'Vue ensemble',
            # Urgent passé le 10 du mois (la paie attend les fiches).
            'urgence': 'urgent' if today.day > 10 else 'normal',
        }
        if peut_relancer:
            item['relance_mois'] = mois_prec
            item['relance_annee'] = annee_prec
        actions.append(item)

    # 5. Salariés en surcharge (score calculé par l'appelant, déjà filtré par seuil).
    for s in (surcharges or [])[:5]:
        actions.append({
            'id': f"surch-{s['user_id']}",
            'categorie': 'surcharge',
            'type': 'lien',
            'icone': '🚨',
            'titre': f"Surcharge : {s['nom_complet']}",
            'detail': (f"score {s['score']}/100 ({s['category']['label']}) — "
                       f"{s['solde_actuel']:.1f} h à récupérer"),
            'lien': url_for('suivi_bp.alertes_surcharge'),
            'lien_texte': 'Alertes surcharge',
            'urgence': 'retard' if s['score'] >= 76 else 'urgent',
        })

    # 6. Soldes de congés conventionnels au-dessus du seuil : à planifier.
    seuil_conges = seuils.get('conges')
    if seuil_conges is not None:
        rows = conn.execute('''
            SELECT u.id, u.nom, u.prenom, COALESCE(u.cc_solde, 0) AS cc_solde
            FROM users u
            WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
              AND COALESCE(u.cc_solde, 0) >= ?
            ORDER BY u.cc_solde DESC
            LIMIT 5
        ''', (seuil_conges,)).fetchall()
        for r in rows:
            solde = f"{r['cc_solde']:g}".replace('.', ',')
            actions.append({
                'id': f"conge-{r['id']}",
                'categorie': 'conges',
                'type': 'lien',
                'icone': '🏖️',
                'titre': f"Solde congés conventionnels élevé : {r['prenom']} {r['nom']}",
                'detail': f"{solde} j de congés conventionnels à planifier (seuil {seuil_conges:g} j)",
                'lien': url_for('absences_bp.absences', search_user_id=r['id']),
                'lien_texte': 'Planifier',
                'urgence': 'normal',
            })

    return actions
