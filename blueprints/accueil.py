"""
Blueprint accueil_bp : l'accueil de l'interface sans menu.

Deux pages :
- `/accueil` : le flux. Les décisions du jour, puis « À l'horizon » : ce qui
  arrive sans rien demander aujourd'hui.
- `/mon-espace` : le dossier personnel ouvert par le nom, en haut à droite —
  compteurs de congés et de récupérations, dépôt d'une demande, et les demandes
  en cours.

Plus une bascule (`/api/interface/basculer`) qui permet à chaque utilisateur
concerné de revenir au menu latéral historique, et d'y retourner.
"""
import logging
from datetime import datetime

from flask import (Blueprint, jsonify, redirect, render_template, request,
                   session, url_for)

import navigation
from dashboard_actions import construire_actions
from database import get_db
from flux_accueil import construire_horizon, separer_actions
from utils import (aujourd_hui, calculer_solde_recup, get_user_info,
                   login_required, NOMS_MOIS)

logger = logging.getLogger(__name__)

accueil_bp = Blueprint('accueil_bp', __name__)

JOURS_SEMAINE = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']

# Libellés des statuts de demande, et le ton qui les colore.
_STATUTS = {
    'en_attente_responsable': ('En attente', 'attente'),
    'en_attente_direction': ('En attente', 'attente'),
    'validee': ('Acceptée', 'ok'),
    'refusee': ('Refusée', 'refus'),
}


def _fr_num(valeur):
    """Nombre -> notation française compacte ('3', '3,5')."""
    return f"{valeur:g}".replace('.', ',')


def _fr_date(valeur):
    """'YYYY-MM-DD' -> 'JJ/MM/AAAA' (chaîne vide si illisible)."""
    if not valeur:
        return ''
    texte = str(valeur)[:10]
    try:
        return datetime.strptime(texte, '%Y-%m-%d').strftime('%d/%m/%Y')
    except ValueError:
        return texte


def _periode(debut, fin):
    """« du 12/08 au 19/08 » — ou « le 12/08 » si la période tient en un jour."""
    d, f = _fr_date(debut), _fr_date(fin)
    if not d:
        return ''
    return f"le {d}" if (not f or f == d) else f"du {d} au {f}"


def _secteur_de(user_id):
    """Secteur du responsable, pour borner ce qu'il voit à son équipe."""
    user = get_user_info(user_id)
    try:
        return user['secteur_id'] if user else None
    except (KeyError, IndexError, TypeError):
        return None


@accueil_bp.route('/accueil')
@login_required
def accueil():
    """Le flux : les décisions du jour, puis l'horizon."""
    profil = session.get('profil')
    user_id = session.get('user_id')

    # L'accueil sans menu n'a de sens que pour qui y a droit ; les autres
    # gardent leur tableau de bord et son menu.
    if not navigation.est_eligible(profil, user_id):
        return redirect(url_for('dashboard_bp.dashboard'))

    secteur_id = _secteur_de(user_id) if profil == 'responsable' else None
    today = datetime.now()

    conn = get_db()
    try:
        actions = construire_actions(conn, profil, user_id, secteur_id=secteur_id)
        horizon = construire_horizon(conn, profil, user_id, secteur_id)
    finally:
        conn.close()

    actions = separer_actions(actions)
    prenom = session.get('prenom') or ''
    salutation = ('Bonjour' if today.hour < 18 else 'Bonsoir')

    return render_template(
        'accueil_flux.html',
        salutation=f"{salutation}{' ' + prenom if prenom else ''}.",
        date_texte=(f"{JOURS_SEMAINE[today.weekday()]} {today.day} "
                    f"{NOMS_MOIS[today.month].lower()} {today.year}"),
        actions=actions,
        nb_actions=len(actions),
        horizon=horizon,
    )


@accueil_bp.route('/mon-espace')
@login_required
def mon_espace():
    """Le dossier personnel : compteurs, dépôt d'une demande, demandes en cours."""
    user_id = session.get('user_id')
    profil = session.get('profil')
    conn = get_db()
    try:
        user = conn.execute(
            '''SELECT nom, prenom, profil,
                      COALESCE(cp_a_prendre, 0) AS cp_a_prendre,
                      COALESCE(cp_pris, 0) AS cp_pris,
                      COALESCE(cc_solde, 0) AS cc_solde
               FROM users WHERE id = ?''',
            (user_id,)
        ).fetchone()

        conges = conn.execute(
            '''SELECT id, type_conge, date_debut, date_fin, nb_jours, statut,
                      date_demande, motif_refus
               FROM demandes_conges WHERE user_id = ?
               ORDER BY date_demande DESC LIMIT 20''',
            (user_id,)
        ).fetchall()
        recups = conn.execute(
            '''SELECT id, date_debut, date_fin, nb_jours, nb_heures, statut,
                      date_demande, motif_refus
               FROM demandes_recup WHERE user_id = ?
               ORDER BY date_demande DESC LIMIT 20''',
            (user_id,)
        ).fetchall()
    finally:
        conn.close()

    solde_cp = (user['cp_a_prendre'] - user['cp_pris']) if user else 0
    solde_cc = user['cc_solde'] if user else 0
    try:
        solde_recup = calculer_solde_recup(user_id)
    except Exception:
        logger.warning("Solde de récupération illisible pour %s", user_id, exc_info=True)
        solde_recup = 0

    compteurs = [
        {'nom': 'Congés payés', 'valeur': f"{_fr_num(solde_cp)} j",
         'detail': f"Acquis {_fr_num(user['cp_a_prendre'])} · pris {_fr_num(user['cp_pris'])}"
                   if user else '',
         'ton': 'vert' if solde_cp >= 0 else 'orange'},
        {'nom': 'Congés conventionnels', 'valeur': f"{_fr_num(solde_cc)} j",
         'detail': 'Solde à planifier avec votre responsable',
         'ton': 'orange' if solde_cc >= 5 else 'neutre'},
        {'nom': 'Récupérations', 'valeur': f"{_fr_num(round(solde_recup, 1))} h",
         'detail': 'Heures acquises, nettes des heures déjà payées',
         'ton': 'orange' if solde_recup >= 7 else 'neutre'},
    ]

    demandes = []
    for c in conges:
        libelle, ton = _STATUTS.get(c['statut'], (c['statut'], 'clos'))
        demandes.append({
            'type': c['type_conge'] or 'Congé',
            'periode': _periode(c['date_debut'], c['date_fin']),
            'quantite': f"{_fr_num(c['nb_jours'])} j",
            'statut': libelle, 'ton': ton,
            'depot': _fr_date(c['date_demande']),
            'motif_refus': c['motif_refus'],
            'lien': url_for('recup_bp.mes_demandes_conges'),
            'tri': str(c['date_demande'] or ''),
        })
    for r in recups:
        libelle, ton = _STATUTS.get(r['statut'], (r['statut'], 'clos'))
        quantite = (f"{_fr_num(r['nb_heures'])} h" if r['nb_heures']
                    else f"{_fr_num(r['nb_jours'])} j")
        demandes.append({
            'type': 'Récupération',
            'periode': _periode(r['date_debut'], r['date_fin']),
            'quantite': quantite,
            'statut': libelle, 'ton': ton,
            'depot': _fr_date(r['date_demande']),
            'motif_refus': r['motif_refus'],
            'lien': url_for('recup_bp.mes_demandes_recup'),
            'tri': str(r['date_demande'] or ''),
        })
    demandes.sort(key=lambda d: d['tri'], reverse=True)

    # Types proposés au dépôt : ceux de la page « Demander un congé », plus la
    # récupération quand le profil y a droit (la direction est au forfait jour).
    from blueprints.recup import _types_conge_pour
    types = [{'nom': t, 'mode': 'conge'} for t in _types_conge_pour(profil)]
    if profil != 'directeur':
        types.append({'nom': 'Récupération', 'mode': 'recup'})

    return render_template(
        'mon_espace.html',
        compteurs=compteurs,
        demandes=demandes[:12],
        nb_attente=sum(1 for d in demandes if d['ton'] == 'attente'),
        types_demande=types,
        solde_cp=solde_cp,
        solde_cc=solde_cc,
        solde_recup=round(solde_recup, 1),
        aujourdhui=aujourd_hui().isoformat(),
    )


@accueil_bp.route('/api/accueil/flux-fragment')
@login_required
def api_flux_fragment():
    """Fragment HTML du fil d'actions (rafraîchissement sans rechargement)."""
    profil = session.get('profil')
    user_id = session.get('user_id')
    if not navigation.est_eligible(profil, user_id):
        return jsonify({'error': 'Accès non autorisé'}), 403
    secteur_id = _secteur_de(user_id) if profil == 'responsable' else None
    conn = get_db()
    try:
        actions = construire_actions(conn, profil, user_id, secteur_id=secteur_id)
    finally:
        conn.close()
    return render_template('_flux_actions.html', actions=separer_actions(actions))


@accueil_bp.route('/api/interface/basculer', methods=['POST'])
@login_required
def api_basculer():
    """Bascule l'utilisateur entre l'interface sans menu et le menu historique.

    Le choix est personnel : il ne change rien pour les autres utilisateurs, et
    ne peut pas donner accès à l'interface sans menu à qui n'y a pas droit.
    """
    from interface_flux import definir_preference_utilisateur
    profil = session.get('profil')
    user_id = session.get('user_id')
    if not navigation.est_eligible(profil, user_id):
        return jsonify({'error': 'Accès non autorisé'}), 403
    data = request.get_json(silent=True) or {}
    actif = bool(data.get('actif'))
    definir_preference_utilisateur(user_id, actif)
    cible = url_for('accueil_bp.accueil') if actif else url_for('dashboard_bp.dashboard')
    return jsonify({'success': True, 'actif': actif, 'redirect': cible})
