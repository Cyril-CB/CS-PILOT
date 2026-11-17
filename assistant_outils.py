"""Outils de consultation bornés ; aucun outil n'écrit dans les dossiers métier."""
from datetime import timedelta
from urllib.parse import urlsplit

from flask import url_for

from assistant_stockage import AssistantErreur, transaction, verifier_tour
from utils import aujourd_hui, maintenant

OUTILS = [
    {'nom': 'rechercher', 'description': 'Retrouver une page ou un dossier réellement accessible.',
     'arguments': {'query': 'Texte de recherche précis, 200 caractères maximum'}},
    {'nom': 'priorites', 'description': 'Lire les cartes des décisions et les échéances visibles pour moi.',
     'arguments': {}},
    {'nom': 'planificateur', 'description': 'Lire mes blocs planifiés et mes tâches à faire sur les 14 prochains jours.',
     'arguments': {}},
    {'nom': 'lire_document', 'description': 'Lire les pages pertinentes du PDF personnel sélectionné dans la boîte de réception.',
     'arguments': {'query': 'Question sur le document, 200 caractères maximum'}},
]


def lien_interne(value):
    if not isinstance(value, str) or not value.startswith('/') or value.startswith('//'):
        return False
    parsed = urlsplit(value)
    return not parsed.scheme and not parsed.netloc and '\\' not in value and not any(ord(c) < 32 for c in value)


def valider_appels(appels):
    if not isinstance(appels, list) or len(appels) > 3:
        raise AssistantErreur('La réponse du modèle contient trop de consultations.', 502)
    for call in appels:
        if not isinstance(call, dict) or set(call) != {'nom', 'arguments'}:
            raise AssistantErreur('La demande de consultation du modèle est invalide.', 502)
        args = call['arguments']
        if not isinstance(args, dict):
            raise AssistantErreur('Arguments de consultation invalides.', 502)
        if call['nom'] in ('rechercher', 'lire_document'):
            if (set(args) != {'query'} or not isinstance(args['query'], str)
                    or not 1 <= len(args['query'].strip()) <= 200):
                raise AssistantErreur('Recherche proposée invalide.', 502)
        elif call['nom'] not in ('priorites', 'planificateur') or args:
            raise AssistantErreur('Cet outil ne fait pas partie des consultations autorisées.', 502)


def _rechercher(conn, user, args):
    from interface_flux import (carte_pour_utilisateur, endpoints_recherche_autorises,
                                recherche_globale_autorisee)
    from search_engine import analyser_recherche
    from search_palette import construire_suggestions
    carte = carte_pour_utilisateur(user['profil'], user['id'])
    verdict = None
    if recherche_globale_autorisee(user['profil']):
        verdict = analyser_recherche(conn, args['query'], user['profil'], aujourd_hui(),
                                     user_id=user['id'], endpoints_autorises=endpoints_recherche_autorises(
                                         user['profil'], user['id'], carte))
    propositions = construire_suggestions(carte, args['query'], verdict)
    return [{'titre': p.get('titre', '')[:200], 'detail': p.get('sous', '')[:300],
             'lien': p['url']} for p in propositions
            if p.get('action') != 'ensemble' and lien_interne(p.get('url'))][:8]


def _priorites(conn, user):
    from blueprints.accueil import _fil_du_profil
    from flux_accueil import construire_horizon
    actions = _fil_du_profil(conn, user['profil'], user['id'], user['secteur_id'])
    elements = [{'titre': a.get('titre', '')[:200], 'detail': a.get('detail', '')[:350],
                 'urgence': a.get('urgence', ''), 'lien': a.get('lien', '')}
                for a in actions[:12]]
    for element, action in zip(elements, actions[:12]):
        circuit = action.get('circuit')
        if circuit:
            element['circuit'] = {
                'intitule': circuit['intitule'], 'etape': circuit['rang'],
                'consequence': circuit.get('consequence'),
                'etapes': [{'titre': e['titre'], 'role': e['role_label'], 'statut': e['statut']}
                           for e in circuit['etapes'][:8]],
            }
    horizon = construire_horizon(conn, user['profil'], user['id'], user['secteur_id'])
    for ligne in horizon:
        elements.extend({'titre': i['titre'][:200], 'detail': i['detail'][:250],
                         'date': i['date'], 'lien': i['lien']} for i in ligne['items'][:4])
    return elements[:20]


def _planificateur(conn, user):
    debut = aujourd_hui().isoformat()
    fin = (aujourd_hui() + timedelta(days=14)).isoformat()
    # user_id est toujours issu du compte connecté ; jamais d'un argument IA.
    rows = conn.execute('''SELECT b.date,b.heure_debut,b.heure_fin,t.titre
        FROM planif_blocs b JOIN planif_taches t ON t.id=b.tache_id
        WHERE b.user_id=? AND t.user_id=? AND b.date BETWEEN ? AND ?
          AND b.statut='planifie'
        ORDER BY b.date,b.heure_debut LIMIT 12''', (user['id'], user['id'], debut, fin)).fetchall()
    resultat = [{'titre': r['titre'][:200], 'detail': f"{r['date']} · {r['heure_debut']}–{r['heure_fin']}",
                 'lien': url_for('planificateur_bp.planificateur')} for r in rows]
    taches = conn.execute('''SELECT titre,deadline FROM planif_taches WHERE user_id=?
        AND type='tache' AND statut='a_faire' AND (deadline IS NULL OR deadline='' OR deadline<=?)
        ORDER BY COALESCE(deadline,'9999'),id LIMIT 8''', (user['id'], fin)).fetchall()
    resultat.extend({'titre': r['titre'][:200], 'detail': 'Tâche à faire · échéance : ' + (r['deadline'] or 'non fixée'),
                     'lien': url_for('planificateur_bp.planificateur')} for r in taches)
    return resultat


def consulter(tour, appels):
    valider_appels(appels)
    sources, resultats = [], []
    with transaction() as conn:
        user, _ = verifier_tour(conn, tour)
        for call in appels:
            if call['nom'] == 'rechercher':
                items = _rechercher(conn, user, call['arguments'])
            elif call['nom'] == 'priorites':
                items = _priorites(conn, user)
            elif call['nom'] == 'lire_document':
                if not tour.get('document_id'):
                    raise AssistantErreur('Sélectionnez d’abord un PDF dans la boîte de réception.')
                from assistant_reception import texte_pour_question
                items = texte_pour_question(conn, user, tour['document_id'], call['arguments']['query'])
            else:
                items = _planificateur(conn, user)
            for item in items:
                if lien_interne(item.get('lien')):
                    sid = 'S' + str(len(sources) + 1)
                    sources.append({'id': sid, 'titre': item['titre'], 'url': item['lien']})
                    item['source'] = sid
            resultats.append({'outil': call['nom'], 'elements': items,
                              'consulte_le': maintenant().isoformat(),
                              'limite': 'Vue bornée ; un résultat vide ne prouve pas l’absence de dossier.'})
    return resultats, sources
