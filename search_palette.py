"""Classement unifié de la barre intelligente de l'interface sans menu.

Ce module ne connaît ni Flask ni la base. Il reçoit la carte de navigation déjà
filtrée par les droits de l'utilisateur et, éventuellement, le verdict du moteur
métier. Le résultat est une liste unique, stable et directement affichable.
"""
import re
import unicodedata


_MOTS_CONVERSATION = {
    'a', 'aller', 'aux', 'chez', 'comment', 'dans', 'de', 'des', 'du', 'en',
    'faire', 'je', 'la', 'le', 'les', 'ma', 'mes', 'mon', 'ou', 'ouvrir',
    'peux', 'pour', 'sur', 'trouver', 'un', 'une', 'vais', 'veut', 'voir',
    'veux', 'vers',
}

# Les variantes sont ramenées à un vocabulaire commun avant le calcul du score.
# On garde ici les formes très fréquentes et les fautes bénignes ; les fautes
# libres sont prises en charge par la distance d'édition plus bas.
_CANONIQUES = {
    'achats': 'achat',
    'conges': 'conge',
    'contrats': 'contrat',
    'echeances': 'echeance',
    'employe': 'salarie',
    'employee': 'salarie',
    'employes': 'salarie',
    'employees': 'salarie',
    'factrue': 'facture',
    'factrues': 'facture',
    'factures': 'facture',
    'fournisseurs': 'fournisseur',
    'heures': 'heure',
    'horaires': 'horaire',
    'plannig': 'planning',
    'plannings': 'planning',
    'recuperations': 'recuperation',
    'reservations': 'reservation',
    'salariee': 'salarie',
    'salaries': 'salarie',
    'salles': 'salle',
    'subventions': 'subvention',
}


def normaliser(texte):
    """Retourne une forme comparable : minuscules, sans accents ni ponctuation."""
    nfkd = unicodedata.normalize('NFKD', str(texte or ''))
    sans_accents = ''.join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', sans_accents.lower())).strip()


def _canonique(mot):
    if mot in _CANONIQUES:
        return _CANONIQUES[mot]
    if len(mot) > 4 and mot.endswith('s') and mot not in {'mois', 'temps', 'tous'}:
        return mot[:-1]
    return mot


def _tokens(texte, sans_outils=False):
    mots = [_canonique(m) for m in normaliser(texte).split()]
    if sans_outils:
        utiles = [m for m in mots if m not in _MOTS_CONVERSATION]
        return utiles or mots
    return mots


def _distance(a, b):
    """Distance de Damerau-Levenshtein, suffisante pour les petites requêtes."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cout = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1,
                          d[i][j - 1] + 1,
                          d[i - 1][j - 1] + cout)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def _qualite_mot(recherche, candidat):
    """1 exact, 0,9 préfixe, 0,72 faute probable, 0 sans correspondance."""
    if recherche == candidat:
        return 1.0
    if len(recherche) >= 3 and candidat.startswith(recherche):
        return 0.9
    if len(candidat) >= 3 and recherche.startswith(candidat):
        return 0.82
    longueur = max(len(recherche), len(candidat))
    limite = 1 if longueur >= 4 else 0
    if longueur >= 8:
        limite = 2
    if limite and _distance(recherche, candidat) <= limite:
        return 0.72
    return 0.0


def _couverture(recherche, candidat):
    """Part des mots de recherche retrouvés et qualité moyenne des appariements."""
    if not recherche or not candidat:
        return 0.0, 0.0
    qualites = [max((_qualite_mot(mot, c) for c in candidat), default=0.0)
                for mot in recherche]
    trouves = [q for q in qualites if q]
    return len(trouves) / len(qualites), (sum(trouves) / len(trouves) if trouves else 0.0)


def _score_page(query_norm, query_tokens, groupe, page):
    label = normaliser(page.get('label'))
    expressions = [normaliser(e) for e in page.get('expressions', [])]
    if query_norm == label:
        return 330
    if query_norm in expressions:
        return 325
    if query_tokens == _tokens(label):
        return 315
    if len(query_norm) >= 3 and label.startswith(query_norm):
        return 300
    if len(query_norm) >= 4 and query_norm in label:
        return 285

    vocabulaire = _tokens(' '.join((page.get('label', ''), page.get('resume', ''),
                                    page.get('mots', ''), ' '.join(expressions))))
    couverture, qualite = _couverture(query_tokens, vocabulaire)
    if couverture == 1:
        return int(225 + 55 * qualite)
    if couverture >= 0.66:
        return int(145 + 55 * couverture * qualite)
    if len(query_tokens) == 1 and couverture:
        return int(120 + 50 * qualite)
    return 0


def _score_groupe(query_norm, query_tokens, groupe):
    nom = normaliser(groupe.get('nom'))
    if query_norm == nom:
        return 190
    vocabulaire = _tokens(' '.join((groupe.get('nom', ''), groupe.get('description', ''),
                                    groupe.get('mots', ''))))
    couverture, qualite = _couverture(query_tokens, vocabulaire)
    if couverture == 1:
        return int(120 + 50 * qualite)
    return 0


def _items_metier(verdict, query_tokens):
    if not verdict or verdict.get('type') == 'none':
        return []
    specifique = len(query_tokens) > 1 or any(t.isdigit() for t in query_tokens)
    if verdict.get('type') == 'redirect':
        return [{
            'icone': '⌕',
            'titre': verdict.get('label', 'Résultat'),
            'sous': 'Résultat précis',
            'url': verdict.get('url'),
            'action': 'metier',
            'score': 360 if specifique else 245,
        }]
    return [{
        'icone': '⌕',
        'titre': option.get('label', 'Résultat'),
        'sous': option.get('sous_titre') or verdict.get('prompt', 'Résultat précis'),
        'url': option.get('url'),
        'action': 'metier',
        'score': 355,
    } for option in verdict.get('options', []) if option.get('url')]


def construire_suggestions(carte, query, verdict=None, limite=10):
    """Fusionne pages, entités métier et zones, puis conserve les meilleurs.

    La dernière proposition est toujours la vue complète. Une zone ne possède
    volontairement pas d'URL : la sélectionner déplie cette zone au lieu
    d'ouvrir sa première page sans rapport avec la demande.
    """
    query_norm = normaliser(query)
    query_tokens = _tokens(query, sans_outils=True)
    groupes = (carte or {}).get('zones', []) + (carte or {}).get('directs', [])
    candidats = []

    for groupe in groupes:
        for page in groupe.get('pages', []):
            score = _score_page(query_norm, query_tokens, groupe, page)
            if score:
                candidats.append({
                    'icone': groupe.get('icone', '→'),
                    'titre': page.get('label', ''),
                    'sous': f"Page · {groupe.get('nom', '')}",
                    'url': page.get('lien'),
                    'zone': groupe.get('id'),
                    'action': 'page',
                    'score': score,
                })
        score = _score_groupe(query_norm, query_tokens, groupe)
        if score:
            candidats.append({
                'icone': groupe.get('icone', '⊕'),
                'titre': f"Explorer {groupe.get('nom', '')}",
                'sous': groupe.get('description', ''),
                'zone': groupe.get('id'),
                'action': 'explorer',
                'score': score,
            })

    candidats.extend(_items_metier(verdict, query_tokens))
    candidats.sort(key=lambda item: (-item['score'], normaliser(item['titre'])))

    # Une page et un verdict métier peuvent pointer vers la même destination.
    # Le meilleur libellé suffit ; montrer deux lignes identiques crée du doute.
    uniques, urls = [], set()
    for item in candidats:
        url = item.get('url')
        if url and url in urls:
            continue
        if url:
            urls.add(url)
        uniques.append(item)
        if len(uniques) >= limite:
            break

    for index, item in enumerate(uniques):
        item['entete'] = 'Meilleur résultat' if index == 0 else (
            'Autres possibilités' if index == 1 else None)
        item.pop('score', None)

    uniques.append({
        'entete': 'Explorer' if uniques else 'Aucun résultat précis',
        'icone': '⊕',
        'titre': "Voir tout l'espace",
        'sous': 'Toutes les zones et toutes les pages accessibles',
        'action': 'ensemble',
    })
    return uniques
