"""Tests du classement unifié de la barre intelligente."""
from search_palette import construire_suggestions, normaliser


CARTE = {
    'zones': [
        {
            'id': 'validations', 'nom': 'Validations & suivi', 'icone': '✓',
            'description': 'Décisions en attente',
            'mots': 'validation facture conge suivi',
            'pages': [{
                'label': "Vue d'ensemble", 'resume': 'Les fiches à valider',
                'mots': 'fiche heure validation relance', 'expressions': [],
                'lien': '/validation',
            }, {
                'label': 'Approbation des factures', 'resume': '',
                'mots': 'facture valider approuver attente',
                'expressions': ['factures à valider'],
                'lien': '/factures/approbation',
            }],
        },
        {
            'id': 'factures', 'nom': 'Factures & achats', 'icone': 'F',
            'description': 'Achats et fournisseurs',
            'mots': 'facture fournisseur achat',
            'pages': [{
                'label': 'Factures', 'resume': 'Suivi des factures reçues',
                'mots': 'facture achat fournisseur', 'expressions': [],
                'lien': '/factures',
            }],
        },
        {
            'id': 'temps', 'nom': 'Temps & plannings', 'icone': 'T',
            'description': 'Temps de travail', 'mots': 'temps planning heure',
            'pages': [{
                'label': 'Mon planning', 'resume': '',
                'mots': 'planning horaire emploi temps',
                'expressions': ['mes horaires'], 'lien': '/planning',
            }],
        },
    ],
    'directs': [],
}


def test_normalisation_accents_et_pluriels():
    assert normaliser('Échéances — Congés') == 'echeances conges'


def test_page_precise_avant_zone_et_jamais_premiere_page_arbitraire():
    suggestions = construire_suggestions(CARTE, 'facture')
    assert suggestions[0]['titre'] == 'Factures'
    assert suggestions[0]['url'] == '/factures'
    zones = [s for s in suggestions if s.get('action') == 'explorer']
    assert zones and all('url' not in z for z in zones)
    assert all(s.get('url') != '/validation' for s in suggestions)


def test_expression_exacte_pointe_l_action_attendue():
    suggestions = construire_suggestions(CARTE, 'factures à valider')
    assert suggestions[0]['titre'] == 'Approbation des factures'


def test_faute_orthographique_classique_et_phrase_conversationnelle():
    assert construire_suggestions(CARTE, 'plannig')[0]['titre'] == 'Mon planning'
    assert construire_suggestions(CARTE, 'je veux voir mes factrues')[0]['titre'] == 'Factures'


def test_resultat_metier_precis_passe_en_premier():
    verdict = {
        'type': 'redirect', 'label': 'Facture 225678',
        'url': '/factures/12/detail',
    }
    suggestions = construire_suggestions(CARTE, 'facture 225678', verdict)
    assert suggestions[0]['action'] == 'metier'
    assert suggestions[0]['url'] == '/factures/12/detail'


def test_une_page_et_son_resultat_metier_ne_font_qu_une_ligne():
    # Le moteur route vers la même page avec un paramètre : « Factures » ne doit
    # pas apparaître deux fois, la carte la nommant déjà.
    verdict = {'type': 'redirect', 'label': 'Factures', 'url': '/factures?annee=2026'}
    suggestions = construire_suggestions(CARTE, 'factures', verdict)
    titres = [s['titre'] for s in suggestions]
    assert titres.count('Factures') == 1


def test_deux_enregistrements_du_meme_ecran_restent_distincts():
    # Même chemin, titres différents : ce sont deux factures, pas un doublon.
    verdict = {
        'type': 'choices', 'prompt': 'Deux factures portent ce numéro',
        'options': [
            {'label': 'Facture 880001 — EDF', 'url': '/factures/detail?id=1'},
            {'label': 'Facture 880002 — EDF', 'url': '/factures/detail?id=2'},
        ],
    }
    suggestions = construire_suggestions(CARTE, 'facture 8800', verdict)
    metiers = [s['titre'] for s in suggestions if s['action'] == 'metier']
    assert metiers == ['Facture 880001 — EDF', 'Facture 880002 — EDF']


def test_deux_homonymes_parfaits_restent_choisissables():
    # Même chemin *et* même titre : seuls deux salariés strictement homonymes le
    # permettent. Le choix leur est justement proposé pour les départager — en
    # effacer un rendrait sa fiche inatteignable depuis la barre.
    verdict = {
        'type': 'choices', 'prompt': 'Plusieurs salariés « Marie Dupont » :',
        'options': [
            {'label': 'Marie Dupont', 'sous_titre': 'Famille',
             'url': '/infos_salaries?user_id=1'},
            {'label': 'Marie Dupont', 'sous_titre': 'Enfance',
             'url': '/infos_salaries?user_id=2'},
        ],
    }
    suggestions = construire_suggestions(CARTE, 'salarié Marie Dupont', verdict)
    metiers = [(s['titre'], s['sous'], s['url'])
               for s in suggestions if s['action'] == 'metier']
    assert metiers == [
        ('Marie Dupont', 'Famille', '/infos_salaries?user_id=1'),
        ('Marie Dupont', 'Enfance', '/infos_salaries?user_id=2'),
    ]


def test_univers_complet_est_toujours_le_dernier_recours():
    suggestions = construire_suggestions(CARTE, 'zzztotalementinconnu')
    assert len(suggestions) == 1
    assert suggestions[0]['action'] == 'ensemble'
    assert suggestions[0]['titre'] == "Voir tout l'espace"
