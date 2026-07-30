"""
Filet de sécurité sur le contrôle d'accès des routes sensibles.

POURQUOI CE FICHIER
-------------------
Chaque route de CS PILOT est protégée « à la main » (un test de profil au début
de la vue). Rien ne garantit qu'une route ajoutée plus tard soit protégée : un
oubli ne déclenche aucune alerte. Ce fichier centralise donc une table de
référence des routes qui exposent des données ou des actions sensibles, et
vérifie automatiquement, pour chacune, que :

1. un visiteur NON CONNECTÉ est renvoyé vers `/login` ;
2. un profil NON AUTORISÉ est refusé (403 pour les routes d'API, redirection
   pour les pages HTML) ;
3. le chemin et la méthode déclarés existent réellement dans l'application
   (sans quoi le test passerait à vide sur une route fantôme).

MODE D'EMPLOI — AJOUTER UNE ROUTE
---------------------------------
Quand vous ajoutez une fonctionnalité qui touche à l'argent, à la paie, aux
données nominatives, à l'administration, aux clés API ou à une suppression,
ajoutez une ligne dans `ROUTES_SENSIBLES` :

    RouteSensible(
        'mon_identifiant',        # identifiant unique, sert d'id pytest lisible
        '/ma/route',              # chemin ; jetons acceptés : {secteur_id},
                                  # {salarie_id}, {id_inexistant}
        'POST',                   # méthode HTTP
        ('directeur', 'comptable'),  # profils réellement autorisés
        '/dashboard',             # forme du refus : chemin de redirection
                                  # attendu, ou REFUS_403 pour une API JSON
        corps={'cle': 'valeur'},  # optionnel : corps JSON envoyé à la route
    )

Les profils déclarés doivent correspondre au code, pas à l'intention : une
ligne fausse rend le filet inutile. En cas d'échec, ne relâchez jamais
l'assertion — vérifiez d'abord si la vue protège vraiment ce qu'elle prétend.

PIÈGE : les fixtures de clients authentifiés (`auth_client`, `resp_client`…)
partagent le même objet client. On utilise donc `client` et on gère les
connexions/déconnexions explicitement.
"""
from collections import namedtuple
from urllib.parse import urlsplit

import pytest


# ── Profils et identifiants de test (voir tests/conftest.py) ─────────────────

PROFILS = {
    'salarie': ('salarie_test', 'sal123'),
    'responsable': ('resp_test', 'resp123'),
    'comptable': ('compta_test', 'compta123'),
    'directeur': ('admin', 'Admin1234'),
    'prestataire': ('presta_test', 'presta123'),
}

TOUS_LES_PROFILS = ('salarie', 'responsable', 'comptable', 'directeur', 'prestataire')

# Marqueur de refus pour les routes d'API, qui répondent en JSON au lieu de
# rediriger. Les autres routes déclarent le chemin de redirection attendu.
REFUS_403 = 403

# Identifiant volontairement absent de la base de test.
#
# LIMITE ASSUMÉE : pour les routes à paramètre (<int:id>) qui ne portent pas
# sur une ressource créée par les fixtures, on appelle la route avec cet
# identifiant. Ce n'est PAS une assertion complaisante : dans toutes les vues
# concernées, le contrôle de profil s'exécute AVANT la lecture de la ressource
# en base. Le refus attendu (403 ou redirection) est donc bien le refus
# d'autorisation, jamais un 404 accidentel — et l'assertion vérifie le statut
# exact, pas un simple « différent de 200 ». Si une vue venait à inverser cet
# ordre (lecture puis contrôle), le test échouerait, ce qui est le
# comportement voulu.
ID_INEXISTANT = 999999

# Année figée : les tests ne doivent pas dépendre de l'heure réelle. Le refus
# étudié intervient de toute façon avant tout calcul lié à l'année.
ANNEE_REFERENCE = 2026


RouteSensible = namedtuple(
    'RouteSensible',
    'identifiant chemin methode autorises refus corps',
    defaults=(None,),
)


# ── Table de référence des routes sensibles ─────────────────────────────────
#
# Colonnes : identifiant | chemin | méthode | profils autorisés | refus attendu
#
# « refus attendu » = REFUS_403 pour une route d'API (réponse JSON), sinon le
# chemin vers lequel la vue redirige un profil non autorisé.

ROUTES_SENSIBLES = [
    # ── Administration système et opérations destructives ────────────────────
    RouteSensible('administration', '/administration', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('administration_options', '/administration/options', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('administration_migrations', '/administration/appliquer_toutes', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('administration_reinitialiser_bdd', '/administration/reinitialiser_bdd', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('sauvegardes_liste', '/sauvegardes', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('sauvegardes_creer', '/sauvegardes/creer', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('sauvegardes_restaurer', '/sauvegardes/restaurer', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('sauvegardes_supprimer', '/sauvegardes/supprimer', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('sauvegardes_telecharger', '/sauvegardes/telecharger/cs_pilot.db', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('mise_a_jour_page', '/mise-a-jour', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('mise_a_jour_lancer', '/api/mise-a-jour/lancer', 'POST',
                  ('directeur', 'comptable'), REFUS_403),

    # ── Comptes utilisateurs et délégations ──────────────────────────────────
    RouteSensible('gestion_users', '/gestion_users', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('creer_user', '/creer_user', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('modifier_user', '/modifier_user/{salarie_id}', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('toggle_user', '/toggle_user/{salarie_id}', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('gestion_secteurs', '/gestion_secteurs', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('delegations', '/delegations', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),

    # ── Clés API (secrets) ───────────────────────────────────────────────────
    RouteSensible('cles_api_page', '/gestion_cles_api', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('cles_api_enregistrer', '/api/api_keys/save', 'POST',
                  ('directeur', 'comptable'), REFUS_403),
    RouteSensible('cles_api_supprimer', '/api/api_keys/delete', 'POST',
                  ('directeur', 'comptable'), REFUS_403),
    RouteSensible('cles_api_statut', '/api/api_keys/status', 'GET',
                  ('directeur', 'comptable'), REFUS_403),

    # ── Journaux de sécurité et traçabilité ──────────────────────────────────
    RouteSensible('journal_acces', '/securite/journal-acces', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('journal_acces_export', '/securite/journal-acces/export', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('journal_actions', '/securite/journal-actions', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('journal_recherches', '/securite/journal-recherches', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('historique_modifications', '/historique_modifications', 'GET',
                  ('directeur',), '/dashboard'),

    # ── Trésorerie ───────────────────────────────────────────────────────────
    RouteSensible('tresorerie', '/tresorerie', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('tresorerie_comptes', '/tresorerie/comptes', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('tresorerie_reinitialiser', '/api/tresorerie/reinitialiser', 'POST',
                  ('directeur', 'comptable'), REFUS_403),
    RouteSensible('tresorerie_supprimer_comptes', '/api/tresorerie/comptes/supprimer_tous', 'POST',
                  ('directeur', 'comptable'), REFUS_403),
    RouteSensible('tresorerie_import_fec', '/api/tresorerie/import_fec', 'POST',
                  ('directeur', 'comptable'), REFUS_403),

    # ── Comptabilité et états financiers ─────────────────────────────────────
    RouteSensible('compte_resultat', '/compte-resultat', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('compte_resultat_export_pdf', '/api/cr/export-pdf', 'GET',
                  ('directeur', 'comptable'), REFUS_403),
    RouteSensible('indicateurs_financiers', '/indicateurs-financiers', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('indicateurs_export_pdf', '/api/indicateurs/export-pdf', 'GET',
                  ('directeur', 'comptable'), REFUS_403),
    RouteSensible('plan_comptable_general', '/plan-comptable-general', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('plan_general_supprimer_compte', '/api/plan-general/comptes/{id_inexistant}',
                  'DELETE', ('directeur', 'comptable'), REFUS_403),
    RouteSensible('plan_comptable_analytique', '/plan-comptable-analytique', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('analytique_supprimer_compte', '/api/comptabilite/comptes/{id_inexistant}',
                  'DELETE', ('directeur', 'comptable'), REFUS_403),
    RouteSensible('ecritures', '/ecritures', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('ecritures_generer', '/ecritures/generer', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('exportation', '/exportation', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('exportation_exporter', '/exportation/exporter', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('exportation_archive_supprimer',
                  '/exportation/archives/{id_inexistant}/supprimer', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('regles_comptables_supprimer', '/regles-comptables/{id_inexistant}/supprimer',
                  'POST', ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('fournisseurs_supprimer', '/fournisseurs/{id_inexistant}/supprimer', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('import_bi', '/import-bi', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('bilan_supprimer_annee', f'/api/bilan/annee/{ANNEE_REFERENCE}', 'DELETE',
                  ('directeur', 'comptable'), REFUS_403),
    RouteSensible('bilan_secteurs', '/bilan-secteurs', 'GET',
                  ('directeur', 'comptable', 'responsable'), '/dashboard'),
    RouteSensible('bilan_action', '/bilan-action', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('analyse_alsh', '/analyse-alsh', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),

    # ── Budget (l'option « responsable autorisé » est activée par défaut) ────
    RouteSensible('gestion_budgets', '/gestion_budgets', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('budget_secteur', '/budget_secteur/{secteur_id}', 'GET',
                  ('directeur', 'comptable', 'responsable'), '/dashboard'),
    RouteSensible('budget_previsionnel', '/budget-previsionnel', 'GET',
                  ('directeur', 'comptable', 'responsable'), '/dashboard'),
    RouteSensible('budget_previsionnel_export_pdf',
                  '/api/budget-previsionnel/export-pdf'
                  f'?type_budget=initial&annee={ANNEE_REFERENCE}' + '&secteur_id={secteur_id}',
                  'GET', ('directeur', 'comptable', 'responsable'), REFUS_403),
    # Le contrôle de profil de cette route s'exécute après la validation des
    # paramètres : on envoie donc un corps complet et un secteur réel.
    RouteSensible('budget_enregistrer', '/api/budget/save', 'POST',
                  ('directeur', 'comptable', 'responsable'), REFUS_403,
                  corps={'secteur_id': '{secteur_id}', 'annee': ANNEE_REFERENCE,
                         'montant_global': 0, 'lignes': []}),

    # ── Subventions et factures (cloisonnement par secteur) ─────────────────
    RouteSensible('subventions', '/subventions', 'GET',
                  ('directeur', 'comptable', 'responsable'), '/dashboard'),
    RouteSensible('subventions_ajouter', '/api/subventions/ajouter', 'POST',
                  ('directeur', 'comptable', 'responsable'), REFUS_403),
    RouteSensible('subventions_supprimer', '/api/subventions/{id_inexistant}/supprimer', 'POST',
                  ('directeur', 'comptable', 'responsable'), REFUS_403),
    RouteSensible('subventions_supprimer_type', '/api/subventions/types/{id_inexistant}/supprimer',
                  'POST', ('directeur', 'comptable'), REFUS_403),
    RouteSensible('subventions_justificatif', '/subventions/justificatif/{id_inexistant}', 'GET',
                  ('directeur', 'comptable', 'responsable'), '/subventions'),
    RouteSensible('factures', '/factures', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('factures_importer', '/factures/importer', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('factures_supprimer', '/factures/{id_inexistant}/supprimer', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('factures_relancer', '/factures/relancer', 'POST',
                  ('directeur', 'comptable'), '/factures'),
    RouteSensible('factures_approbation', '/factures/approbation', 'GET',
                  ('directeur', 'comptable', 'responsable'), '/dashboard'),
    RouteSensible('factures_telecharger', '/factures/{id_inexistant}/telecharger', 'GET',
                  ('directeur', 'comptable', 'responsable'), '/dashboard'),

    # ── Données RH et paie nominatives ───────────────────────────────────────
    RouteSensible('infos_salaries', '/infos_salaries', 'GET',
                  ('directeur', 'comptable', 'responsable'), '/dashboard'),
    RouteSensible('infos_salaries_document', '/infos_salaries/telecharger_document/{id_inexistant}',
                  'GET', ('directeur', 'comptable', 'responsable'), '/dashboard'),
    RouteSensible('infos_salaries_supprimer_document',
                  '/infos_salaries/supprimer_document/{id_inexistant}', 'POST',
                  ('directeur', 'comptable', 'responsable'), '/dashboard'),
    RouteSensible('infos_salaries_contrat', '/infos_salaries/telecharger_contrat/{id_inexistant}',
                  'GET', ('directeur', 'comptable', 'responsable', 'prestataire'), '/dashboard'),
    RouteSensible('soldes_conges', '/soldes_conges', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('prepa_paie', '/prepa_paie', 'GET',
                  ('directeur', 'comptable', 'prestataire'), '/dashboard'),
    RouteSensible('prepa_paie_export_excel', '/prepa_paie/export_excel', 'GET',
                  ('directeur', 'comptable', 'prestataire'), '/dashboard'),
    RouteSensible('prepa_paie_traiter', '/prepa_paie/traiter', 'POST',
                  ('directeur', 'comptable', 'prestataire'), '/dashboard'),
    RouteSensible('variables_paie', '/variables_paie', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('variables_paie_enregistrer', '/variables_paie/enregistrer', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('variables_paie_cloturer', '/variables_paie/cloturer_conges', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('rh_statistiques', '/rh/statistiques', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('contrats', '/contrats', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('generation_contrats', '/generation_contrats', 'GET',
                  ('directeur', 'comptable', 'responsable'), '/dashboard'),
    RouteSensible('presence_effectif', '/presence-effectif', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('pesee_alisfa', '/pesee_alisfa', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('pesee_alisfa_supprimer_poste', '/api/pesee_alisfa/poste/{id_inexistant}',
                  'DELETE', ('directeur', 'comptable'), REFUS_403),
    RouteSensible('absences_justificatif', '/absences/justificatif/{id_inexistant}', 'GET',
                  ('directeur', 'comptable', 'prestataire'), '/dashboard'),
    RouteSensible('absences_supprimer', '/absences/supprimer/{id_inexistant}', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('dashboard_direction', '/dashboard_direction', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('dashboard_direction_seuils', '/api/dashboard-direction/seuils', 'POST',
                  ('directeur', 'comptable'), REFUS_403),
    RouteSensible('deverrouiller_mois', '/deverrouiller_mois', 'POST',
                  ('directeur',), '/dashboard'),
    RouteSensible('rapport_forfait_jour_pdf', f'/rapport_forfait_jour_pdf/1/{ANNEE_REFERENCE}',
                  'GET', ('directeur',), '/dashboard'),

    # ── Configuration email et recherche transverse ──────────────────────────
    RouteSensible('configuration_email', '/configuration_email', 'POST',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('email_test', '/api/email/test', 'POST',
                  ('directeur', 'comptable'), REFUS_403),
    RouteSensible('recherche_globale', '/api/search', 'POST',
                  ('directeur', 'comptable'), REFUS_403),

    # ── Suivi des heures de bénévolat ────────────────────────────────────────
    # Le calendrier des activités est commun à l'association : un responsable,
    # qui ne voit qu'une partie des bénévoles, n'y touche pas.
    RouteSensible('benevoles_heures_page', '/benevoles/heures', 'GET',
                  ('directeur', 'comptable'), '/dashboard'),
    RouteSensible('benevoles_activite_ajouter', '/api/benevoles/activites/ajouter', 'POST',
                  ('directeur', 'comptable'), REFUS_403, corps={'nom': 'CA'}),
    RouteSensible('benevoles_activite_modifier', '/api/benevoles/activites/1/modifier', 'POST',
                  ('directeur', 'comptable'), REFUS_403,
                  corps={'field': 'nom', 'value': 'X'}),
    RouteSensible('benevoles_activite_supprimer', '/api/benevoles/activites/1/supprimer',
                  'POST', ('directeur', 'comptable'), REFUS_403),
    RouteSensible('benevoles_seance_ajouter', '/api/benevoles/activites/1/seances/ajouter',
                  'POST', ('directeur', 'comptable'), REFUS_403,
                  corps={'date': '2026-01-15'}),
    RouteSensible('benevoles_seance_modifier', '/api/benevoles/seances/1/modifier', 'POST',
                  ('directeur', 'comptable'), REFUS_403,
                  corps={'field': 'heures', 'value': 2}),
    RouteSensible('benevoles_seance_supprimer', '/api/benevoles/seances/1/supprimer', 'POST',
                  ('directeur', 'comptable'), REFUS_403),
    RouteSensible('benevoles_participant_ajouter',
                  '/api/benevoles/activites/1/participants/ajouter', 'POST',
                  ('directeur', 'comptable'), REFUS_403, corps={'benevole_id': 1}),
    RouteSensible('benevoles_participation_modifier',
                  '/api/benevoles/participations/1/modifier', 'POST',
                  ('directeur', 'comptable'), REFUS_403, corps={'absences': 1}),
    RouteSensible('benevoles_participation_supprimer',
                  '/api/benevoles/participations/1/supprimer', 'POST',
                  ('directeur', 'comptable'), REFUS_403),
    RouteSensible('benevoles_presence', '/api/benevoles/presences', 'POST',
                  ('directeur', 'comptable'), REFUS_403,
                  corps={'seance_id': 1, 'benevole_id': 1, 'present': True}),
    RouteSensible('benevoles_heures_autres_ajouter', '/api/benevoles/heures-autres/ajouter',
                  'POST', ('directeur', 'comptable'), REFUS_403,
                  corps={'benevole_id': 1, 'heures': 2}),
    RouteSensible('benevoles_heures_autres_supprimer',
                  '/api/benevoles/heures-autres/1/supprimer', 'POST',
                  ('directeur', 'comptable'), REFUS_403),
]

IDS_ROUTES = [route.identifiant for route in ROUTES_SENSIBLES]


# ── Utilitaires ─────────────────────────────────────────────────────────────

def _resoudre(gabarit, sample_users):
    """Remplace les jetons du gabarit par les identifiants réels du jeu d'essai."""
    return gabarit.format(
        secteur_id=sample_users['secteur_id'],
        salarie_id=sample_users['salarie_id'],
        id_inexistant=ID_INEXISTANT,
    )


def _resoudre_corps(corps, sample_users):
    """Résout les jetons présents dans les valeurs du corps JSON."""
    if corps is None:
        return None
    return {
        cle: (_resoudre(valeur, sample_users) if isinstance(valeur, str) else valeur)
        for cle, valeur in corps.items()
    }


def _appeler(client, route, sample_users):
    """Appelle la route sans suivre les redirections (le refus doit rester visible)."""
    chemin = _resoudre(route.chemin, sample_users)
    corps = _resoudre_corps(route.corps, sample_users)
    if corps is None:
        return client.open(chemin, method=route.methode, follow_redirects=False)
    return client.open(chemin, method=route.methode, json=corps, follow_redirects=False)


def _chemin_redirection(reponse):
    """Chemin visé par une redirection (sans schéma ni hôte)."""
    return urlsplit(reponse.headers.get('Location', '')).path


def _diagnostic(route, profil, reponse):
    """Message d'échec nommant la route fautive et le profil concerné."""
    destination = _chemin_redirection(reponse) or 'aucune redirection'
    return (
        f"Contrôle d'accès insuffisant sur {route.methode} {route.chemin} "
        f"(entrée « {route.identifiant} ») : le profil « {profil} » a obtenu "
        f"le statut {reponse.status_code} (destination : {destination}) "
        f"alors que seuls {', '.join(route.autorises)} sont autorisés."
    )


def _verifier_refus(route, profil, reponse):
    """Vérifie que la réponse est bien le refus déclaré dans la table."""
    if route.refus == REFUS_403:
        assert reponse.status_code == 403, _diagnostic(route, profil, reponse)
        return
    assert reponse.status_code in (301, 302), _diagnostic(route, profil, reponse)
    assert _chemin_redirection(reponse) == route.refus, _diagnostic(route, profil, reponse)


def _connexion(client, profil):
    """Connecte le client de test avec les identifiants du profil demandé."""
    identifiant, mot_de_passe = PROFILS[profil]
    return client.post(
        '/login',
        data={'login': identifiant, 'password': mot_de_passe},
        follow_redirects=True,
    )


@pytest.fixture
def client_anonyme(client, sample_users, prestataire_client):
    """Client de test déconnecté, les cinq profils étant présents en base.

    `prestataire_client` sert uniquement à créer le compte prestataire ; comme
    cette fixture connecte au passage le client partagé, on referme la session
    pour repartir d'un visiteur réellement anonyme.
    """
    client.get('/logout', follow_redirects=True)
    return client


# ── Tests ───────────────────────────────────────────────────────────────────

def test_table_de_reference_est_coherente(app, sample_users):
    """La table doit décrire des routes réelles : identifiants uniques, chemins
    et méthodes existants, profils connus. Sans ce garde-fou, une faute de
    frappe rendrait les tests suivants vides de sens."""
    assert len(IDS_ROUTES) == len(set(IDS_ROUTES)), \
        'Deux entrées de ROUTES_SENSIBLES partagent le même identifiant.'

    adaptateur = app.url_map.bind('localhost')
    for route in ROUTES_SENSIBLES:
        chemin = _resoudre(route.chemin, sample_users).split('?')[0]
        try:
            adaptateur.match(chemin, method=route.methode)
        except Exception as erreur:
            pytest.fail(
                f"Entrée « {route.identifiant} » : {route.methode} {chemin} "
                f"ne correspond à aucune route de l'application ({erreur})."
            )

        assert route.autorises, \
            f"Entrée « {route.identifiant} » : aucun profil autorisé déclaré."
        inconnus = set(route.autorises) - set(TOUS_LES_PROFILS)
        assert not inconnus, \
            f"Entrée « {route.identifiant} » : profils inconnus {sorted(inconnus)}."
        assert set(route.autorises) != set(TOUS_LES_PROFILS), \
            (f"Entrée « {route.identifiant} » : tous les profils sont autorisés, "
             f"la route n'a rien de sensible à vérifier.")


@pytest.mark.parametrize('route', ROUTES_SENSIBLES, ids=IDS_ROUTES)
def test_route_sensible_refuse_anonymes_et_profils_non_autorises(
    route, app, sample_users, client_anonyme
):
    """Chaque route sensible refuse le visiteur anonyme et tout profil non
    autorisé. Les fixtures de clients authentifiés partagent le même client :
    on enchaîne donc les profils par connexion/déconnexion explicites."""
    client = client_anonyme

    # 1. Visiteur non connecté : renvoyé vers la page de connexion.
    reponse = _appeler(client, route, sample_users)
    assert reponse.status_code in (301, 302), _diagnostic(route, 'anonyme', reponse)
    assert _chemin_redirection(reponse) == '/login', _diagnostic(route, 'anonyme', reponse)

    # 2. Profils non autorisés : refus explicite (403) ou redirection.
    for profil in TOUS_LES_PROFILS:
        if profil in route.autorises:
            continue
        _connexion(client, profil)
        reponse = _appeler(client, route, sample_users)
        _verifier_refus(route, profil, reponse)
        client.get('/logout', follow_redirects=True)


def test_setup_ne_recree_pas_un_administrateur_quand_des_comptes_existent(
    app, db, client, sample_users
):
    """La page d'installation initiale crée le premier administrateur : elle
    doit être fermée dès qu'un compte existe, sinon un visiteur anonyme
    obtiendrait les pleins pouvoirs."""
    reponse = client.get('/setup', follow_redirects=False)
    assert reponse.status_code in (301, 302)
    assert _chemin_redirection(reponse) == '/login'

    reponse = client.post('/setup', data={
        'nom': 'Pirate',
        'prenom': 'Anonyme',
        'login': 'pirate_test',
        'password': 'Pirate1234!',
        'password_confirm': 'Pirate1234!',
    }, follow_redirects=False)
    assert reponse.status_code in (301, 302)
    assert _chemin_redirection(reponse) == '/login'

    with app.app_context():
        cree = db.execute(
            "SELECT 1 FROM users WHERE login = 'pirate_test'"
        ).fetchone()
    assert cree is None, "La page /setup a créé un compte alors que la base n'est pas vierge."
