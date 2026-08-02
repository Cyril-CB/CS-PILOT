"""
Tests de l'interface sans menu.

Vérifient ce qui est facile à casser sans s'en apercevoir :
- qui bascule et qui ne bascule pas ;
- que le menu latéral disparaît bien pour les uns et reste pour les autres ;
- que la carte de navigation n'expose que des pages autorisées ;
- que l'accueil, « Mon espace » et les pages ordinaires s'affichent.
"""
import html as html_module
import json
import re

import pytest

import navigation


def _carte_embarquee(corps):
    """Relit la carte de navigation déposée dans l'attribut `data-carte`."""
    trouve = re.search(r'data-carte="([^"]*)"', corps)
    assert trouve, "attribut data-carte absent de la page"
    return json.loads(html_module.unescape(trouve.group(1)))


# ── Carte de navigation ────────────────────────────────────────────────────

def test_tous_les_endpoints_de_la_carte_existent(app):
    """Une entrée de menu qui pointe dans le vide casse la vue d'ensemble."""
    regles = {r.endpoint for r in app.url_map.iter_rules()}
    for groupe in navigation.ZONES + navigation.ACCES_DIRECTS:
        for page in groupe['pages']:
            assert page['endpoint'] in regles, (
                f"{groupe['id']} → endpoint inconnu : {page['endpoint']}")


def test_carte_du_salarie_ne_contient_aucune_page_de_direction(app):
    """Un salarié délégué ne doit rien gagner d'autre que sa délégation."""
    with app.test_request_context('/'):
        carte = navigation.carte_navigation({'profil': 'salarie', 'user_id': 1})
    endpoints = {p['endpoint']
                 for g in carte['zones'] + carte['directs']
                 for p in g['pages']}
    for interdit in ('admin_bp.gestion_users', 'factures_bp.liste_factures',
                     'infos_salaries_bp.infos_salaries', 'prepa_paie_bp.prepa_paie',
                     'tresorerie_bp.tresorerie', 'budget_bp.gestion_budgets'):
        assert interdit not in endpoints


def test_carte_du_responsable_respecte_les_options(app):
    """Les options d'administration ferment bien les pages concernées."""
    contexte = {'profil': 'responsable', 'user_id': 1,
                'can_access_vue_ensemble_validation': True,
                'generation_contrats_responsable_autorise': False,
                'budget_previsionnel_responsable_autorise': False}
    with app.test_request_context('/'):
        carte = navigation.carte_navigation(contexte)
    endpoints = {p['endpoint']
                 for g in carte['zones'] + carte['directs']
                 for p in g['pages']}
    assert 'generation_contrats_bp.generation_contrats' not in endpoints
    assert 'budget_bp.budget_previsionnel' not in endpoints
    assert 'budget_bp.mon_budget' in endpoints


def test_delegation_benevoles_ouvre_la_page_au_salarie(app):
    """Sans la délégation la page reste fermée ; avec elle, elle apparaît."""
    with app.test_request_context('/'):
        sans = navigation.carte_navigation({'profil': 'salarie', 'user_id': 1})
        avec = navigation.carte_navigation({'profil': 'salarie', 'user_id': 1,
                                            'is_delegue_benevoles': True})
    aplat = lambda c: {p['endpoint'] for g in c['zones'] + c['directs'] for p in g['pages']}
    assert 'benevoles_bp.gestion_benevoles' not in aplat(sans)
    assert 'benevoles_bp.gestion_benevoles' in aplat(avec)


def test_localiser_retrouve_la_zone_d_une_page(app):
    with app.test_request_context('/'):
        carte = navigation.carte_navigation({'profil': 'directeur', 'user_id': 1})
        zone, page = navigation.localiser(carte, 'factures_bp.liste_factures')
    assert zone['id'] == 'factures'
    assert page['label'] == 'Factures'


# ── Éligibilité ────────────────────────────────────────────────────────────

@pytest.mark.parametrize('profil,attendu', [
    ('directeur', True), ('comptable', True), ('responsable', True),
    ('salarie', False), ('prestataire', False),
])
def test_eligibilite_par_profil(app, sample_users, profil, attendu):
    with app.app_context():
        assert navigation.est_eligible(profil, sample_users['salarie_id']) is attendu


def test_salarie_delegue_devient_eligible(app, db, sample_users):
    """Une délégation de mission fait basculer un salarié."""
    from blueprints.delegations import (MISSION_SUIVI_VALIDATIONS_RELANCES,
                                        save_delegation)
    with app.app_context():
        assert not navigation.est_eligible('salarie', sample_users['salarie_id'])
        save_delegation(MISSION_SUIVI_VALIDATIONS_RELANCES,
                        sample_users['salarie_id'], sample_users['directeur_id'])
        assert navigation.est_eligible('salarie', sample_users['salarie_id'])


def test_delegation_salles_seule_ne_suffit_pas(app, db, sample_users):
    """La récurrence de salle n'ouvre aucune page : elle ne fait pas basculer."""
    from blueprints.delegations import save_salle_recurrence_delegations
    with app.app_context():
        save_salle_recurrence_delegations([sample_users['salarie_id']],
                                          sample_users['directeur_id'])
        assert not navigation.est_eligible('salarie', sample_users['salarie_id'])


# ── Rendu des pages ────────────────────────────────────────────────────────

def test_le_directeur_arrive_sur_le_flux_sans_menu(admin_client):
    reponse = admin_client.get('/dashboard', follow_redirects=True)
    corps = reponse.get_data(as_text=True)
    assert reponse.status_code == 200
    assert 'flx-entete' in corps           # l'ossature sans menu est là
    assert 'class="sidebar"' not in corps  # le menu latéral a disparu
    assert "À l'horizon" in corps or 'flx-astuces' in corps


def test_le_salarie_garde_son_menu(auth_client):
    reponse = auth_client.get('/dashboard', follow_redirects=True)
    corps = reponse.get_data(as_text=True)
    assert reponse.status_code == 200
    assert 'class="sidebar"' in corps
    assert 'flx-entete' not in corps


def test_mon_espace_affiche_les_compteurs(admin_client):
    reponse = admin_client.get('/mon-espace')
    corps = reponse.get_data(as_text=True)
    assert reponse.status_code == 200
    assert 'Congés payés' in corps
    assert 'Récupérations' in corps
    assert 'Poser une demande' in corps
    # Retirés du modèle à la demande : pas de bulletins ni de documents.
    assert 'Bulletins de paie' not in corps
    assert 'Mes documents' not in corps


def test_le_salarie_non_eligible_ne_peut_pas_ouvrir_le_flux(auth_client):
    """L'accueil sans menu renvoie au tableau de bord habituel."""
    reponse = auth_client.get('/accueil')
    assert reponse.status_code == 302
    assert '/dashboard' in reponse.headers['Location']


def test_une_page_ordinaire_recoit_les_boutons_de_sa_zone(admin_client):
    """Sur Factures, les pages voisines de la zone remplacent le sous-menu."""
    reponse = admin_client.get('/factures')
    corps = reponse.get_data(as_text=True)
    assert reponse.status_code == 200
    assert 'flx-chips' in corps
    assert 'Factures &amp; achats' in corps or 'Factures & achats' in corps
    assert 'Fournisseurs' in corps and 'Écritures' in corps
    assert 'Revenir au flux' in corps


def test_le_flux_d_information_apparait_sur_les_factures(admin_client, db, sample_users):
    """Une facture en attente doit se voir avant la liste.

    Elle est assignée à la direction : c'est ce que la page d'approbation
    liste, et donc ce que le bandeau doit compter.
    """
    with db:
        db.execute(
            "INSERT INTO factures (numero_facture, montant_ttc, approbation, statut, "
            "assigned_direction) VALUES ('F-1', 100, 'en_attente', 'a_traiter', 1)"
        )
    corps = admin_client.get('/factures').get_data(as_text=True)
    assert 'flx-infos' in corps
    # L'apostrophe est échappée par Jinja dans le rendu HTML.
    assert 'facture(s) en attente d&#39;approbation' in corps
    assert 'facture(s) sans écriture — à générer' not in corps  # page Écritures


def test_bascule_vers_le_menu_classique_et_retour(admin_client):
    reponse = admin_client.post('/api/interface/basculer', json={'actif': False})
    assert reponse.status_code == 200
    assert reponse.get_json()['actif'] is False

    corps = admin_client.get('/dashboard_direction').get_data(as_text=True)
    assert 'class="sidebar"' in corps
    assert 'flx-entete' not in corps

    reponse = admin_client.post('/api/interface/basculer', json={'actif': True})
    assert reponse.status_code == 200
    corps = admin_client.get('/accueil').get_data(as_text=True)
    assert 'flx-entete' in corps


def test_bascule_refusee_pour_un_salarie_non_eligible(auth_client):
    reponse = auth_client.post('/api/interface/basculer', json={'actif': True})
    assert reponse.status_code == 403


def test_option_globale_desactivee_rend_le_menu(admin_client, app):
    with app.app_context():
        from app_options import set_option_bool
        set_option_bool('interface_sans_menu_active', False)
    corps = admin_client.get('/dashboard', follow_redirects=True).get_data(as_text=True)
    assert 'class="sidebar"' in corps
    assert 'flx-entete' not in corps


# ── « À l'horizon » ────────────────────────────────────────────────────────

def test_horizon_separe_le_lointain_de_l_immediat(admin_client, db):
    """Une échéance à 3 jours reste dans le fil ; à 40 jours elle passe à l'horizon."""
    from datetime import timedelta

    from utils import aujourd_hui
    today = aujourd_hui()
    with db:
        db.execute("INSERT INTO subventions (nom, groupe, annee_action) "
                   "VALUES ('CAF CLAS', 'depose', ?)", (str(today.year),))
        sub_id = db.execute("SELECT id FROM subventions WHERE nom = 'CAF CLAS'").fetchone()['id']
        db.execute("INSERT INTO subventions_sous_elements "
                   "(subvention_id, nom, statut, date_echeance) VALUES (?, ?, 'non_commence', ?)",
                   (sub_id, 'Bilan qualitatif', (today + timedelta(days=3)).isoformat()))
        db.execute("INSERT INTO subventions_sous_elements "
                   "(subvention_id, nom, statut, date_echeance) VALUES (?, ?, 'non_commence', ?)",
                   (sub_id, 'Dépôt du dossier', (today + timedelta(days=40)).isoformat()))

    corps = admin_client.get('/accueil').get_data(as_text=True)
    # Le texte littéral d'un gabarit n'est pas échappé : seule la zone
    # « À l'horizon » sépare le fil de ce qui vient plus tard.
    fil, horizon = corps.split("À l'horizon", 1)
    assert 'Bilan qualitatif' in fil          # imminent : dans le fil
    assert 'Dépôt du dossier' not in fil      # lointain : pas dans le fil
    assert 'Dépôt du dossier' in horizon      # …mais bien à l'horizon
    assert 'Échéances' in horizon


def test_horizon_annonce_les_fins_de_contrat(admin_client, db, sample_users):
    """Une fin de CDD à venir doit apparaître dans la ligne RH."""
    from datetime import timedelta

    from utils import aujourd_hui
    today = aujourd_hui()
    with db:
        db.execute("INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin) "
                   "VALUES (?, 'CDD', ?, ?)",
                   (sample_users['salarie_id'], (today - timedelta(days=200)).isoformat(),
                    (today + timedelta(days=45)).isoformat()))

    corps = admin_client.get('/accueil').get_data(as_text=True)
    assert 'Fin de CDD — Jean Martin' in corps
    assert '>RH<' in corps


def test_page_hors_carte_garde_une_sortie(admin_client, db):
    """Une page absente de la carte doit tout de même offrir le retour au flux."""
    with db:
        db.execute("INSERT INTO factures (id, numero_facture, montant_ttc) VALUES (77, 'F-77', 10)")
    corps = admin_client.get('/factures/77/detail').get_data(as_text=True)
    assert 'Revenir au flux' in corps
    assert 'flx-chips' not in corps


def test_fragment_du_fil_est_rechargeable(admin_client, db, sample_users):
    """Le rafraîchissement automatique renvoie les cartes, sans l'ossature."""
    with db:
        db.execute(
            "INSERT INTO demandes_conges (user_id, type_conge, date_debut, date_fin, "
            "nb_jours, statut) VALUES (?, 'Congé payé', '2026-09-01', '2026-09-05', 5, "
            "'en_attente_direction')", (sample_users['salarie_id'],))
    reponse = admin_client.get('/api/accueil/flux-fragment')
    corps = reponse.get_data(as_text=True)
    assert reponse.status_code == 200
    assert 'flx-carte' in corps
    assert 'Demande de congé payé : Jean Martin' in corps
    assert '<html' not in corps          # fragment seul, pas la page entière


def test_fragment_du_fil_refuse_les_non_eligibles(auth_client):
    assert auth_client.get('/api/accueil/flux-fragment').status_code == 403


def test_le_salarie_delegue_recoit_le_flux_mais_pas_les_pages_de_direction(
        client, app, db, sample_users):
    """Le salarié délégué bascule, avec sa seule délégation en plus."""
    from blueprints.delegations import save_benevoles_delegations
    with app.app_context():
        save_benevoles_delegations([sample_users['salarie_id']],
                                   sample_users['directeur_id'])

    client.post('/login', data={'login': 'salarie_test', 'password': 'sal123'},
                follow_redirects=True)
    corps = client.get('/accueil').get_data(as_text=True)
    assert 'flx-entete' in corps
    assert 'class="sidebar"' not in corps

    # La carte de navigation voyage en JSON dans `data-carte` : on la relit
    # comme le fait le navigateur, plutôt que de chercher du texte échappé.
    carte = _carte_embarquee(corps)
    pages = {p['label'] for g in carte['zones'] + carte['directs'] for p in g['pages']}
    assert 'Bénévoles' in pages                    # sa délégation
    assert 'Préparation de la paie' not in pages   # rien de la direction
    assert 'Utilisateurs' not in pages
    assert 'Factures' not in pages


def test_le_message_du_cse_apparait_sur_le_flux(admin_client, db, sample_users):
    """La bannière CSE suivait les tableaux de bord : elle suit l'accueil aussi."""
    from datetime import timedelta

    from utils import aujourd_hui
    with db:
        db.execute(
            "INSERT INTO cse_messages (titre, contenu, date_validite, cree_par) "
            "VALUES ('Réunion du 12', 'Ordre du jour joint.', ?, ?)",
            ((aujourd_hui() + timedelta(days=10)).isoformat(), sample_users['directeur_id']))
    corps = admin_client.get('/accueil').get_data(as_text=True)
    assert 'cse-banner' in corps
    assert 'Message du CSE à lire' in corps


# ── Revue Codex #232 : parité, cadrage des données et cohérence ────────────

def test_le_flux_direction_porte_les_factures_et_les_relances(
        admin_client, db, sample_users):
    """L'accueil remplace le centre de contrôle : il en garde la file étendue."""
    from datetime import timedelta

    from utils import aujourd_hui
    with db:
        db.execute("INSERT INTO fournisseurs (nom) VALUES ('ALTEO')")
        f_id = db.execute("SELECT id FROM fournisseurs LIMIT 1").fetchone()['id']
        db.execute(
            "INSERT INTO factures (fournisseur_id, numero_facture, montant_ttc, "
            "date_echeance, approbation, assigned_direction, statut) "
            "VALUES (?, '225678', 2480.0, ?, 'en_attente', 1, 'a_traiter')",
            (f_id, (aujourd_hui() + timedelta(days=3)).isoformat()))

    corps = admin_client.get('/accueil').get_data(as_text=True)
    assert 'ALTEO' in corps
    assert 'data-flx-act="facture"' in corps
    # Les fiches du mois précédent ne sont validées pour personne : la relance
    # doit être proposée, comme sur le tableau de bord direction.
    assert 'data-flx-act="relance"' in corps


def test_le_salarie_delegue_ne_voit_pas_les_demandes_des_autres(
        client, app, db, sample_users):
    """Un délégué « bénévoles » n'a rien à valider : rien ne doit filtrer."""
    from blueprints.delegations import save_benevoles_delegations
    with app.app_context():
        save_benevoles_delegations([sample_users['salarie_id']],
                                   sample_users['directeur_id'])
    with db:
        db.execute(
            "INSERT INTO demandes_conges (user_id, type_conge, date_debut, date_fin, "
            "nb_jours, statut) VALUES (?, 'Congé payé', '2026-09-01', '2026-09-05', 5, "
            "'en_attente_direction')", (sample_users['comptable_id'],))
        db.execute(
            "INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin) "
            "VALUES (?, 'CDD', '2026-01-01', '2026-09-15')",
            (sample_users['comptable_id'],))

    client.post('/login', data={'login': 'salarie_test', 'password': 'sal123'},
                follow_redirects=True)
    corps = client.get('/accueil').get_data(as_text=True)
    assert 'flx-entete' in corps                      # il est bien sur le flux
    assert 'Durand' not in corps                       # ni la demande du comptable
    assert 'Fin de CDD' not in corps                   # ni son contrat
    assert 'data-flx-act="valider"' not in corps       # ni un bouton de validation


def test_le_responsable_ne_voit_que_son_equipe(resp_client, db, sample_users):
    """Le cadrage par secteur vaut aussi pour l'accueil sans menu."""
    with db:
        db.execute(
            "INSERT INTO demandes_conges (user_id, type_conge, date_debut, date_fin, "
            "nb_jours, statut) VALUES (?, 'Congé payé', '2026-09-01', '2026-09-05', 5, "
            "'en_attente_responsable')", (sample_users['comptable_id'],))
    corps = resp_client.get('/accueil').get_data(as_text=True)
    assert 'Sophie Durand' not in corps


def test_une_echeance_rh_imminente_reste_visible(admin_client, db, sample_users):
    """Un CDD qui se termine demain ne doit disparaître de nulle part."""
    from datetime import timedelta

    from utils import aujourd_hui
    demain = aujourd_hui() + timedelta(days=1)
    with db:
        db.execute("INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin) "
                   "VALUES (?, 'CDD', '2026-01-01', ?)",
                   (sample_users['salarie_id'], demain.isoformat()))
    corps = admin_client.get('/accueil').get_data(as_text=True)
    assert 'Fin de CDD — Jean Martin' in corps


def test_option_globale_desactivee_ferme_aussi_l_accueil(admin_client, app):
    """Sans l'option du centre, l'accueil ne doit pas s'ouvrir dans le menu."""
    with app.app_context():
        from app_options import set_option_bool
        set_option_bool('interface_sans_menu_active', False)

    for chemin in ('/accueil', '/mon-espace'):
        reponse = admin_client.get(chemin)
        assert reponse.status_code == 302, chemin
        assert '/dashboard' in reponse.headers['Location'], chemin

    assert admin_client.get('/api/accueil/flux-fragment').status_code == 403

    # Le bouton « Essayer la nouvelle interface » disparaît lui aussi.
    corps = admin_client.get('/dashboard_direction').get_data(as_text=True)
    assert 'Essayer la nouvelle interface' not in corps


def test_la_delegation_des_validations_expose_la_vue_d_ensemble(app):
    """La page accordée par la délégation doit figurer dans la carte."""
    with app.test_request_context('/'):
        carte = navigation.carte_navigation({
            'profil': 'salarie', 'user_id': 1,
            'can_access_vue_ensemble_validation': True})
    endpoints = {p['endpoint']
                 for g in carte['zones'] + carte['directs'] for p in g['pages']}
    assert 'validation_bp.vue_ensemble_validation' in endpoints
    # Sans la délégation, elle reste fermée.
    with app.test_request_context('/'):
        sans = navigation.carte_navigation({'profil': 'salarie', 'user_id': 1})
    assert 'validation_bp.vue_ensemble_validation' not in {
        p['endpoint'] for g in sans['zones'] + sans['directs'] for p in g['pages']}


def test_le_calcul_des_jours_ouvres_exclut_les_feries(admin_client, db):
    """Le décompte affiché doit coïncider avec celui du serveur."""
    with db:
        db.execute("INSERT OR IGNORE INTO jours_feries (date, libelle, annee) "
                   "VALUES ('2026-08-15', 'Assomption', 2026)")
    corps = admin_client.get('/mon-espace').get_data(as_text=True)
    assert '2026-08-15' in corps        # la liste est bien transmise au gabarit
    assert 'FERIES.indexOf' in corps    # …et réellement utilisée dans le calcul


# ── Invariant : la carte n'excède jamais le menu latéral ───────────────────

def _liens_du_menu(corps):
    """Liens réellement rendus dans le menu latéral."""
    aside = re.search(r'<aside class="sidebar".*?</aside>', corps, re.S)
    return {h for h in re.findall(r'href="([^"]+)"', aside.group(0) if aside else '')
            if h.startswith('/')}


def _liens_de_la_carte(corps):
    carte = _carte_embarquee(corps)
    return {p['lien'] for g in carte['zones'] + carte['directs'] for p in g['pages']}


# Pages dont l'écart avec le menu est voulu : « Mon espace » est créé par cette
# interface, les tableaux de bord historiques sont ce que le flux remplace, et
# la déconnexion vit dans l'en-tête plutôt que dans la carte.
_ECARTS_ATTENDUS = {
    '/',                     # le logo, présent dans les deux en-têtes
    '/mon-espace',           # créé par cette interface
    '/logout',               # dans l'en-tête du flux, pas dans la carte
    '/dashboard', '/dashboard_direction',
    '/dashboard_responsable', '/dashboard_comptable',
}


@pytest.mark.parametrize('login,mdp,profil', [
    ('admin', 'Admin1234', 'directeur'),
    ('resp_test', 'resp123', 'responsable'),
    ('salarie_test', 'sal123', 'salarie'),
])
def test_la_carte_n_ouvre_rien_de_plus_que_le_menu(client, app, db, sample_users,
                                                   login, mdp, profil):
    """Garantie centrale : la vue d'ensemble ne montre que des pages autorisées.

    On compare la carte réellement transmise au navigateur (`data-carte`) aux
    liens réellement rendus dans le menu latéral du même utilisateur. Aucune
    page ne doit apparaître d'un côté sans l'autre — hors écarts voulus.
    """
    from app_options import set_option_bool
    if profil == 'salarie':   # un salarié ne bascule qu'avec une délégation
        from blueprints.delegations import save_benevoles_delegations
        with app.app_context():
            save_benevoles_delegations([sample_users['salarie_id']],
                                       sample_users['directeur_id'])

    with app.app_context():
        set_option_bool('interface_sans_menu_active', False)
    client.post('/login', data={'login': login, 'password': mdp}, follow_redirects=True)
    menu = _liens_du_menu(client.get('/dashboard', follow_redirects=True).get_data(as_text=True))
    assert menu, "le menu latéral attendu est vide"

    with app.app_context():
        set_option_bool('interface_sans_menu_active', True)
    carte = _liens_de_la_carte(
        client.get('/accueil', follow_redirects=True).get_data(as_text=True))

    en_trop = carte - menu - _ECARTS_ATTENDUS
    assert not en_trop, f"{profil} : pages dans la carte mais pas dans le menu : {sorted(en_trop)}"
    perdues = menu - carte - _ECARTS_ATTENDUS
    assert not perdues, f"{profil} : pages du menu absentes de la carte : {sorted(perdues)}"


def test_une_zone_entierement_fermee_disparait(client, app, sample_users):
    """Un responsable n'a aucune page d'administration : la zone n'existe pas."""
    client.post('/login', data={'login': 'resp_test', 'password': 'resp123'},
                follow_redirects=True)
    carte = _carte_embarquee(client.get('/accueil').get_data(as_text=True))
    ids = {g['id'] for g in carte['zones'] + carte['directs']}
    assert 'administration' not in ids
    assert 'comptabilite' not in ids
    assert 'validations' in ids          # celle-ci, il y a droit


# ── Seuils d'alerte, réglables depuis l'accueil ────────────────────────────

def test_les_seuils_se_reglent_depuis_l_accueil(admin_client):
    """L'accueil remplace le centre de contrôle : il en porte aussi les réglages."""
    corps = admin_client.get('/accueil').get_data(as_text=True)
    assert 'ccSeuilsModal' in corps
    assert 'ccOuvrirSeuils()' in corps
    assert 'Score de surcharge' in corps


def test_le_responsable_n_a_pas_les_seuils(resp_client):
    """Les seuils pilotent la file étendue : ils ne concernent pas un responsable."""
    corps = resp_client.get('/accueil').get_data(as_text=True)
    assert 'ccSeuilsModal' not in corps


def test_un_seuil_enregistre_depuis_l_accueil_change_le_fil(admin_client, db, sample_users):
    """Enregistrer un seuil doit réellement modifier ce que le fil affiche."""
    with db:
        db.execute('UPDATE users SET cc_solde = 9 WHERE id = ?',
                   (sample_users['salarie_id'],))

    # Seuil bas : le solde de congés conventionnels remonte dans le fil.
    reponse = admin_client.post('/api/dashboard-direction/seuils', json={'conges': 5})
    assert reponse.status_code == 200
    assert 'Solde congés conventionnels élevé' in admin_client.get('/accueil').get_data(as_text=True)

    # Seuil relevé au-dessus : il n'a plus lieu d'être signalé.
    admin_client.post('/api/dashboard-direction/seuils', json={'conges': 20})
    assert 'Solde congés conventionnels élevé' not in admin_client.get('/accueil').get_data(as_text=True)


def test_le_centre_de_controle_partage_le_meme_gabarit(admin_client):
    """Les deux pages règlent exactement les mêmes valeurs."""
    accueil = admin_client.get('/accueil').get_data(as_text=True)
    controle = admin_client.get('/dashboard_direction').get_data(as_text=True)
    for champ in ('ccSeuilTreso', 'ccSeuilBudget', 'ccSeuilConges',
                  'ccSeuilSurcharge', 'ccSeuilDigest'):
        assert champ in accueil, champ
        assert champ in controle, champ


# ── Revue Codex n°2 : ne jamais pointer vers une page fermée au lecteur ────

def test_le_bandeau_factures_compte_ce_que_la_page_d_approbation_montre(
        admin_client, db, sample_users):
    """Le compteur ne doit pas promettre plus que sa destination n'affiche."""
    with db:
        db.execute("INSERT INTO secteurs (nom) VALUES ('Enfance')")
        sect = db.execute("SELECT id FROM secteurs WHERE nom='Enfance'").fetchone()['id']
        # Une facture assignée : elle apparaît sur la page d'approbation.
        db.execute("INSERT INTO factures (numero_facture, montant_ttc, approbation, "
                   "secteur_id) VALUES ('F-A', 100, 'en_attente', ?)", (sect,))
        # Deux factures encore non assignées : la page ne les liste pas.
        db.execute("INSERT INTO factures (numero_facture, montant_ttc, approbation, "
                   "assigned_direction) VALUES ('F-B', 100, 'en_attente', 0)")
        db.execute("INSERT INTO factures (numero_facture, montant_ttc, approbation, "
                   "assigned_direction) VALUES ('F-C', 100, 'en_attente', 0)")

    corps = admin_client.get('/factures').get_data(as_text=True)
    approbation = admin_client.get('/factures/approbation').get_data(as_text=True)
    assert 'F-A' in approbation and 'F-B' not in approbation

    bandeaux = re.findall(r'flx-info-valeur">(\d+)</span>\s*<span class="flx-info-libelle">([^<]+)',
                          corps)
    par_libelle = {libelle.strip(): int(n) for n, libelle in bandeaux}
    assert par_libelle.get("facture(s) en attente d&#39;approbation") == 1
    # Les non assignées sont signalées à part, vers leur vraie destination.
    assert par_libelle.get('facture(s) à assigner à un secteur') == 2


def test_le_responsable_ne_compte_que_les_fiches_de_son_equipe(
        resp_client, db, sample_users):
    """Le bandeau suit le cadrage de la page qu'il décore."""
    with db:
        db.execute("INSERT INTO secteurs (nom) VALUES ('Ailleurs')")
        autre = db.execute("SELECT id FROM secteurs WHERE nom='Ailleurs'").fetchone()['id']
        db.execute("INSERT INTO users (nom, prenom, login, password, profil, secteur_id) "
                   "VALUES ('Loin', 'Paul', 'ploin', 'x', 'salarie', ?)", (autre,))

    corps = resp_client.get('/vue_ensemble_validation').get_data(as_text=True)
    assert 'dans votre équipe' in corps
    bandeaux = re.findall(r'flx-info-valeur">(\d+)</span>', corps)
    # Son équipe : le salarié de test et lui-même — pas le salarié d'ailleurs
    # ni le comptable.
    assert bandeaux and int(bandeaux[0]) == 2


def test_le_delegue_aux_validations_ne_voit_pas_les_demandes_a_valider(
        client, app, db, sample_users):
    """Sa délégation porte sur le suivi des fiches, pas sur les congés."""
    from blueprints.delegations import (MISSION_SUIVI_VALIDATIONS_RELANCES,
                                        save_delegation)
    with app.app_context():
        save_delegation(MISSION_SUIVI_VALIDATIONS_RELANCES,
                        sample_users['salarie_id'], sample_users['directeur_id'])
    with db:
        db.execute(
            "INSERT INTO demandes_conges (user_id, type_conge, date_debut, date_fin, "
            "nb_jours, statut) VALUES (?, 'Congé payé', '2026-09-01', '2026-09-05', 5, "
            "'en_attente_direction')", (sample_users['comptable_id'],))

    client.post('/login', data={'login': 'salarie_test', 'password': 'sal123'},
                follow_redirects=True)
    corps = client.get('/vue_ensemble_validation').get_data(as_text=True)
    assert corps.count('flx-info') > 0                      # il voit bien la page
    assert 'demande(s) en attente de validation' not in corps
    assert '/validation_demandes_recup' not in corps


def test_pas_de_carte_de_subvention_pour_un_salarie_delegue(
        client, app, db, sample_users):
    """La page et l'action « C'est fait » lui sont fermées : pas de carte."""
    from blueprints.delegations import save_benevoles_delegations
    with app.app_context():
        save_benevoles_delegations([sample_users['salarie_id']],
                                   sample_users['directeur_id'])
    with db:
        db.execute("INSERT INTO subventions (nom, groupe, annee_action) "
                   "VALUES ('CAF CLAS', 'depose', '2026')")
        sub = db.execute("SELECT id FROM subventions LIMIT 1").fetchone()['id']
        db.execute("INSERT INTO subventions_sous_elements (subvention_id, nom, statut, "
                   "date_echeance, assignee_id) VALUES (?, 'Bilan', 'non_commence', "
                   "'2026-08-05', ?)", (sub, sample_users['salarie_id']))

    client.post('/login', data={'login': 'salarie_test', 'password': 'sal123'},
                follow_redirects=True)
    corps = client.get('/accueil').get_data(as_text=True)
    assert 'Bilan' not in corps
    assert 'data-flx-act="subvention"' not in corps


def test_pas_de_retour_d_absence_pour_un_responsable(resp_client, db, sample_users):
    """La page des absences lui est fermée : la carte ne doit pas exister."""
    from datetime import timedelta

    from utils import aujourd_hui
    with db:
        db.execute("INSERT INTO absences (user_id, motif, date_debut, date_fin, "
                   "jours_ouvres, saisi_par) VALUES (?, 'maladie', ?, ?, 20, ?)",
                   (sample_users['salarie_id'],
                    (aujourd_hui() - timedelta(days=10)).isoformat(),
                    (aujourd_hui() + timedelta(days=20)).isoformat(),
                    sample_users['directeur_id']))
    corps = resp_client.get('/accueil').get_data(as_text=True)
    assert 'Retour de' not in corps

    # La direction, elle, peut ouvrir la page : la carte lui est proposée.
    assert '/absences' not in corps


# ── Barre intelligente : recherche métier vs navigation locale ─────────────

def _drapeau_recherche(corps):
    trouve = re.search(r'data-recherche-globale="([01])"', corps)
    assert trouve, 'drapeau de recherche absent du socle'
    return trouve.group(1) == '1'


def test_la_recherche_metier_est_offerte_a_qui_l_api_autorise(admin_client):
    """Direction : la palette peut proposer « Rechercher »."""
    from blueprints.recherche import PROFILS_AUTORISES
    assert 'directeur' in PROFILS_AUTORISES
    corps = admin_client.get('/accueil').get_data(as_text=True)
    assert _drapeau_recherche(corps) is True
    assert admin_client.post('/api/search', json={'query': 'budget'}).status_code == 200


def test_le_responsable_garde_la_navigation_sans_recherche_metier(resp_client):
    """`/api/search` lui répond 403 : la palette ne doit pas la lui proposer.

    Sa barre reste utile — elle ouvre zones et pages, ce qui remplace le menu.
    """
    assert resp_client.post('/api/search', json={'query': 'budget'}).status_code == 403
    corps = resp_client.get('/accueil').get_data(as_text=True)
    assert _drapeau_recherche(corps) is False
    assert 'Où voulez-vous aller' in corps
    # La navigation locale, elle, est bien alimentée.
    carte = _carte_embarquee(corps)
    assert carte['zones'], 'la palette du responsable serait vide'


def test_le_salarie_delegue_garde_la_navigation_sans_recherche_metier(
        client, app, db, sample_users):
    from blueprints.delegations import save_benevoles_delegations
    with app.app_context():
        save_benevoles_delegations([sample_users['salarie_id']],
                                   sample_users['directeur_id'])
    client.post('/login', data={'login': 'salarie_test', 'password': 'sal123'},
                follow_redirects=True)
    assert client.post('/api/search', json={'query': 'budget'}).status_code == 403
    corps = client.get('/accueil').get_data(as_text=True)
    assert _drapeau_recherche(corps) is False
    assert _carte_embarquee(corps)['zones']


def test_le_drapeau_suit_la_liste_d_autorisation_de_l_api(app):
    """Palette et API lisent la même source : elles ne peuvent pas diverger."""
    import interface_flux
    from blueprints.recherche import PROFILS_AUTORISES
    for profil in ('directeur', 'comptable', 'responsable', 'salarie', 'prestataire'):
        with app.app_context():
            assert (interface_flux.recherche_globale_autorisee(profil)
                    is (profil in PROFILS_AUTORISES)), profil


# ── Retours d'usage : largeur, téléphone ───────────────────────────────────

UA_BUREAU = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
             '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')
UA_IPHONE = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
             'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')
UA_ANDROID = ('Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36')
UA_IPAD = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
           '(KHTML, like Gecko) Version/17.0 Safari/605.1.15')


def test_les_pages_ordinaires_recuperent_la_place_du_menu(admin_client):
    """Un tableau ne doit pas être plus à l'étroit qu'avec le menu latéral."""
    lecture = admin_client.get('/accueil').get_data(as_text=True)
    tableau = admin_client.get('/presence-effectif').get_data(as_text=True)
    # La colonne étroite du modèle ne concerne que les pages de lecture.
    assert 'class="flx flx-lecture"' in lecture
    assert 'class="flx"' in tableau and 'flx-lecture' not in tableau


@pytest.mark.parametrize('agent', [UA_IPHONE, UA_ANDROID])
def test_le_telephone_garde_l_interface_classique(client, sample_users, agent):
    """Sur téléphone, le menu latéral reste plus confortable."""
    client.post('/login', data={'login': 'admin', 'password': 'Admin1234'},
                follow_redirects=True, headers={'User-Agent': agent})
    corps = client.get('/dashboard', follow_redirects=True,
                       headers={'User-Agent': agent}).get_data(as_text=True)
    assert 'class="sidebar"' in corps
    assert 'flx-entete' not in corps
    # Et l'accueil sans menu n'est pas atteignable depuis le téléphone.
    reponse = client.get('/accueil', headers={'User-Agent': agent})
    assert reponse.status_code == 302
    # Inutile de lui proposer une bascule qui ne changerait rien.
    assert 'Essayer la nouvelle interface' not in corps


@pytest.mark.parametrize('agent', [UA_BUREAU, UA_IPAD])
def test_le_bureau_et_la_tablette_gardent_le_flux(client, sample_users, agent):
    """Un iPad récent annonce un Safari de bureau : son écran suffit."""
    client.post('/login', data={'login': 'admin', 'password': 'Admin1234'},
                follow_redirects=True, headers={'User-Agent': agent})
    corps = client.get('/dashboard', follow_redirects=True,
                       headers={'User-Agent': agent}).get_data(as_text=True)
    assert 'flx-entete' in corps
    assert 'class="sidebar"' not in corps


def test_le_meme_compte_suit_l_appareil(client, sample_users):
    """Flux au bureau, menu classique sur le téléphone — sans rien régler."""
    client.post('/login', data={'login': 'admin', 'password': 'Admin1234'},
                follow_redirects=True, headers={'User-Agent': UA_BUREAU})
    bureau = client.get('/dashboard', follow_redirects=True,
                        headers={'User-Agent': UA_BUREAU}).get_data(as_text=True)
    telephone = client.get('/dashboard', follow_redirects=True,
                           headers={'User-Agent': UA_IPHONE}).get_data(as_text=True)
    assert 'flx-entete' in bureau and 'class="sidebar"' not in bureau
    assert 'class="sidebar"' in telephone and 'flx-entete' not in telephone
