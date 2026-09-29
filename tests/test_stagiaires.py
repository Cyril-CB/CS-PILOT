"""Suivi des stagiaires : droits, fiche, emploi du temps et annonce dans le fil."""
from datetime import date
import importlib
import re

import pytest

import dashboard_actions
import navigation
import stagiaires as service
from database import ALL_MIGRATION_VERSIONS

# L'anonymisation quotidienne se déclenche à la première requête du jour, sur
# la date réelle : les tests qui ne la visent pas l'écartent pour rester
# déterministes quelle que soit la date d'exécution.
ANONYMISER = service.anonymiser_stages_termines


@pytest.fixture(autouse=True)
def _sans_anonymisation_implicite(monkeypatch):
    monkeypatch.setattr(service, 'anonymiser_stages_termines', lambda *args: 0)


def _stagiaire(db, debut='2026-10-05', fin='2026-10-09', nom='Martin', prenom='Léa',
               tuteur_id=None, etudes='3e', etablissement='Collège Jean Moulin'):
    curseur = db.execute(
        '''INSERT INTO stagiaires (nom, prenom, etudes, etablissement, tuteur_id,
                                   date_debut, date_fin)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (nom, prenom, etudes, etablissement, tuteur_id, debut, fin))
    db.commit()
    return curseur.lastrowid


def _creneau(db, stagiaire_id, jour, demi_journee, secteur_id):
    db.execute('''INSERT INTO stagiaires_creneaux (stagiaire_id, date, demi_journee, secteur_id)
                  VALUES (?, ?, ?, ?)''', (stagiaire_id, jour, demi_journee, secteur_id))
    db.commit()


def _autre_secteur(db, nom='Petite enfance'):
    curseur = db.execute('INSERT INTO secteurs (nom) VALUES (?)', (nom,))
    db.commit()
    return curseur.lastrowid


def _formulaire(**valeurs):
    donnees = {'nom': 'Martin', 'prenom': 'Léa', 'etudes': '3e',
               'etablissement': 'Collège Jean Moulin', 'tuteur_id': '',
               'date_debut': '2026-10-05', 'date_fin': '2026-10-09'}
    donnees.update(valeurs)
    return donnees


def _creneaux(db, stagiaire_id):
    return {(r['date'], r['demi_journee'], r['secteur_id']) for r in db.execute(
        'SELECT date, demi_journee, secteur_id FROM stagiaires_creneaux WHERE stagiaire_id = ?',
        (stagiaire_id,))}


def _cartes_stagiaires(app, db, monkeypatch, profil, user_id, secteur_id, today):
    monkeypatch.setattr('dashboard_actions.aujourd_hui', lambda: today)
    with app.test_request_context('/'):
        actions = dashboard_actions.construire_actions(db, profil, user_id, secteur_id=secteur_id)
    return actions, [a for a in actions if a['categorie'] == 'stagiaire']


# ── Droits ─────────────────────────────────────────────────────────────────

def test_non_connecte_renvoye_vers_la_connexion(client, sample_users):
    reponse = client.get('/stagiaires')
    assert reponse.status_code == 302
    assert '/login' in reponse.headers['Location']


@pytest.mark.parametrize('fixture', ['auth_client', 'prestataire_client'])
def test_salarie_et_prestataire_refuses_meme_par_url(request, db, sample_users, fixture):
    visiteur = request.getfixturevalue(fixture)
    stagiaire_id = _stagiaire(db)
    assert visiteur.get('/stagiaires').status_code == 403
    assert visiteur.get(f'/stagiaires/{stagiaire_id}').status_code == 403
    assert visiteur.post('/stagiaires/nouveau', data=_formulaire(nom='Intrus')).status_code == 403
    assert visiteur.post(f'/stagiaires/{stagiaire_id}/informations',
                         data=_formulaire(nom='Modifié')).status_code == 403
    assert visiteur.post(f'/stagiaires/{stagiaire_id}/emploi-du-temps', data={
        'creneau_2026-10-05_matin': str(sample_users['secteur_id'])}).status_code == 403
    assert visiteur.post(f'/stagiaires/{stagiaire_id}/supprimer').status_code == 403
    assert [tuple(r) for r in db.execute('SELECT nom FROM stagiaires')] == [('Martin',)]
    assert _creneaux(db, stagiaire_id) == set()


@pytest.mark.parametrize('fixture', ['admin_client', 'resp_client', 'comptable_client'])
def test_gestionnaires_ouvrent_la_liste_vide(request, fixture):
    corps = request.getfixturevalue(fixture).get('/stagiaires')
    assert corps.status_code == 200
    texte = corps.get_data(as_text=True)
    assert 'Aucun stagiaire enregistré' in texte
    assert 'Ajouter un stagiaire' in texte


def test_fiche_inexistante(resp_client):
    assert resp_client.get('/stagiaires/999999').status_code == 404
    assert resp_client.post('/stagiaires/999999/supprimer').status_code == 404


def test_page_dans_la_carte_des_gestionnaires_seulement(app, sample_users):
    def endpoints(profil):
        with app.test_request_context('/'):
            carte = navigation.carte_navigation({'profil': profil, 'user_id': 1})
        return {p['endpoint'] for g in carte['zones'] + carte['directs'] for p in g['pages']}
    for profil in ('directeur', 'comptable', 'responsable'):
        assert 'stagiaires_bp.liste' in endpoints(profil)
    assert 'stagiaires_bp.liste' not in endpoints('salarie')


# ── Fiche ──────────────────────────────────────────────────────────────────

def test_creation_par_un_responsable(resp_client, db, sample_users):
    reponse = resp_client.post('/stagiaires/nouveau', data=_formulaire(
        nom='  Martin ', prenom='Léa', etablissement='Collège   Jean Moulin',
        tuteur_id=str(sample_users['responsable_id'])))
    assert reponse.status_code == 302
    ligne = db.execute('SELECT * FROM stagiaires').fetchone()
    assert reponse.headers['Location'].endswith(f"/stagiaires/{ligne['id']}#emploi-du-temps")
    assert (ligne['nom'], ligne['prenom'], ligne['etudes'], ligne['etablissement']) == (
        'Martin', 'Léa', '3e', 'Collège Jean Moulin')
    assert ligne['tuteur_id'] == sample_users['responsable_id']
    assert (ligne['date_debut'], ligne['date_fin']) == ('2026-10-05', '2026-10-09')
    assert ligne['cree_par'] == sample_users['responsable_id']

    fiche = resp_client.get(f"/stagiaires/{ligne['id']}").get_data(as_text=True)
    assert 'Emploi du temps' in fiche
    assert fiche.count('<fieldset class="stagiaires-jour') == 5
    assert 'Lundi 5 octobre' in fiche and 'Vendredi 9 octobre' in fiche


@pytest.mark.parametrize('valeurs, message', [
    ({'nom': '   '}, 'Nom : champ obligatoire.'),
    ({'date_fin': '2026-10-04'}, 'La date de fin doit suivre'),
    ({'date_debut': '2026-02-31'}, 'Date de début : date invalide.'),
    ({'date_fin': '05/10/2026'}, 'Date de fin : date invalide.'),
    ({'date_fin': '2027-01-05'}, 'limitée à 92 jours'),
    ({'tuteur_id': '999999'}, 'Le tuteur doit être un responsable'),
    ({'tuteur_id': 'abc'}, 'Tuteur inconnu'),
    ({'etudes': 'x' * 81}, 'Études : 80 caractères au maximum.'),
])
def test_creation_refuse_une_saisie_invalide(resp_client, db, valeurs, message):
    reponse = resp_client.post('/stagiaires/nouveau', data=_formulaire(**valeurs))
    assert reponse.status_code == 400
    assert message in reponse.get_data(as_text=True)
    assert db.execute('SELECT COUNT(*) FROM stagiaires').fetchone()[0] == 0


def test_tuteur_doit_etre_un_responsable_actif(admin_client, db, sample_users):
    presta = db.execute(
        "INSERT INTO users (nom, prenom, login, password, profil) "
        "VALUES ('Cabinet', 'Paie', 'presta_tuteur', 'x', 'prestataire')").lastrowid
    ancien = db.execute(
        "INSERT INTO users (nom, prenom, login, password, profil, actif) "
        "VALUES ('Ancien', 'Resp', 'ancien_resp', 'x', 'responsable', 0)").lastrowid
    db.commit()
    fiche = admin_client.get('/stagiaires/nouveau').get_data(as_text=True)
    assert f'<option value="{sample_users["responsable_id"]}"' in fiche
    for autre in (sample_users['salarie_id'], sample_users['comptable_id'],
                  sample_users['directeur_id'], presta, ancien):
        assert f'<option value="{autre}"' not in fiche
        reponse = admin_client.post('/stagiaires/nouveau', data=_formulaire(tuteur_id=str(autre)))
        assert reponse.status_code == 400
        assert 'Le tuteur doit être un responsable' in reponse.get_data(as_text=True)
    assert db.execute('SELECT COUNT(*) FROM stagiaires').fetchone()[0] == 0


def test_tuteur_desactive_conserve_tant_qu_il_n_est_pas_change(admin_client, db, sample_users):
    tuteur = sample_users['responsable_id']
    stagiaire_id = _stagiaire(db, tuteur_id=tuteur)
    db.execute('UPDATE users SET actif = 0 WHERE id = ?', (tuteur,))
    db.commit()
    fiche = admin_client.get(f'/stagiaires/{stagiaire_id}').get_data(as_text=True)
    assert '(compte désactivé)' in fiche

    reponse = admin_client.post(f'/stagiaires/{stagiaire_id}/informations', data=_formulaire(
        tuteur_id=str(tuteur), etudes='Seconde'))
    assert reponse.status_code == 302
    ligne = db.execute('SELECT etudes, tuteur_id, modifie_par FROM stagiaires').fetchone()
    assert tuple(ligne) == ('Seconde', tuteur, sample_users['directeur_id'])


def test_raccourcir_la_periode_retire_les_demi_journees_sorties(resp_client, db, sample_users):
    secteur = sample_users['secteur_id']
    stagiaire_id = _stagiaire(db)
    _creneau(db, stagiaire_id, '2026-10-05', 'matin', secteur)
    _creneau(db, stagiaire_id, '2026-10-09', 'matin', secteur)
    _creneau(db, stagiaire_id, '2026-10-09', 'apres_midi', secteur)
    reponse = resp_client.post(f'/stagiaires/{stagiaire_id}/informations',
                               data=_formulaire(date_fin='2026-10-08'), follow_redirects=True)
    assert reponse.status_code == 200
    assert '2 demi-journées hors de la nouvelle période ont été retirées' in reponse.get_data(as_text=True)
    assert _creneaux(db, stagiaire_id) == {('2026-10-05', 'matin', secteur)}


def test_modification_invalide_ne_change_rien(resp_client, db, sample_users):
    stagiaire_id = _stagiaire(db)
    _creneau(db, stagiaire_id, '2026-10-09', 'matin', sample_users['secteur_id'])
    reponse = resp_client.post(f'/stagiaires/{stagiaire_id}/informations',
                               data=_formulaire(date_fin='2026-10-08', prenom=''))
    assert reponse.status_code == 400
    assert db.execute('SELECT date_fin FROM stagiaires').fetchone()[0] == '2026-10-09'
    assert len(_creneaux(db, stagiaire_id)) == 1


# ── Emploi du temps ────────────────────────────────────────────────────────

def test_emploi_du_temps_par_demi_journee_et_secteur(resp_client, db, sample_users):
    secteur, autre = sample_users['secteur_id'], _autre_secteur(db)
    stagiaire_id = _stagiaire(db, debut='2026-10-05', fin='2026-10-06')
    _creneau(db, stagiaire_id, '2026-10-06', 'matin', autre)
    reponse = resp_client.post(f'/stagiaires/{stagiaire_id}/emploi-du-temps', data={
        'creneau_2026-10-05_matin': str(secteur),
        'creneau_2026-10-05_apres_midi': str(autre),
        'creneau_2026-10-06_matin': '',
        # Hors période : jamais lu, même si le navigateur l'envoie.
        'creneau_2026-10-12_matin': str(secteur),
    }, follow_redirects=True)
    assert reponse.status_code == 200
    assert 'Emploi du temps enregistré : 2 demi-journées au centre.' in reponse.get_data(as_text=True)
    assert _creneaux(db, stagiaire_id) == {('2026-10-05', 'matin', secteur),
                                           ('2026-10-05', 'apres_midi', autre)}
    assert db.execute('SELECT modifie_par FROM stagiaires').fetchone()[0] == sample_users['responsable_id']

    fiche = resp_client.get(f'/stagiaires/{stagiaire_id}').get_data(as_text=True)
    assert f'<option value="{secteur}" selected>Secteur Test</option>' in fiche
    assert '2 demi-journées au centre sur 4.' in fiche


@pytest.mark.parametrize('valeur', ['999999', 'abc', '-1'])
def test_emploi_du_temps_refuse_un_secteur_inconnu(resp_client, db, sample_users, valeur):
    secteur = sample_users['secteur_id']
    stagiaire_id = _stagiaire(db)
    _creneau(db, stagiaire_id, '2026-10-05', 'matin', secteur)
    reponse = resp_client.post(f'/stagiaires/{stagiaire_id}/emploi-du-temps', data={
        'creneau_2026-10-05_matin': '',
        'creneau_2026-10-06_matin': str(secteur),
        'creneau_2026-10-07_matin': valeur,
    })
    assert reponse.status_code == 400
    texte = reponse.get_data(as_text=True)
    assert "Un secteur choisi n&#39;existe plus" in texte
    # La saisie refusée est réaffichée, la base reste intacte.
    assert re.search(rf'name="creneau_2026-10-06_matin">\s*<option value="">—</option>\s*'
                     rf'<option value="{secteur}" selected>', texte)
    assert _creneaux(db, stagiaire_id) == {('2026-10-05', 'matin', secteur)}


def test_suppression_efface_fiche_et_emploi_du_temps(admin_client, db, sample_users):
    stagiaire_id = _stagiaire(db)
    _creneau(db, stagiaire_id, '2026-10-05', 'matin', sample_users['secteur_id'])
    reponse = admin_client.post(f'/stagiaires/{stagiaire_id}/supprimer')
    assert reponse.status_code == 302
    assert reponse.headers['Location'].endswith('/stagiaires')
    assert db.execute('SELECT COUNT(*) FROM stagiaires').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM stagiaires_creneaux').fetchone()[0] == 0


def test_liste_classe_en_cours_a_venir_et_termines(resp_client, db, sample_users, monkeypatch):
    monkeypatch.setattr('blueprints.stagiaires.aujourd_hui', lambda: date(2026, 10, 7))
    en_cours = _stagiaire(db, prenom='Léa')
    _creneau(db, en_cours, '2026-10-05', 'matin', sample_users['secteur_id'])
    _stagiaire(db, debut='2026-11-02', fin='2026-11-06', prenom='Hugo', etudes='', etablissement='')
    _stagiaire(db, debut='2026-06-01', fin='2026-06-05', prenom='Inès')
    texte = resp_client.get('/stagiaires').get_data(as_text=True)
    assert texte.index('En cours') < texte.index('Léa Martin') < texte.index('À venir') \
        < texte.index('Hugo Martin') < texte.index('Stages terminés (1)') < texte.index('Inès Martin')
    assert 'Secteur Test' in texte
    assert 'Emploi du temps à remplir' in texte


# ── Annonce dans le fil d'actions ──────────────────────────────────────────

@pytest.mark.parametrize('today, attendu', [
    (date(2026, 10, 5), date(2026, 10, 6)),   # lundi → mardi
    (date(2026, 10, 8), date(2026, 10, 9)),   # jeudi → vendredi
    (date(2026, 10, 9), date(2026, 10, 12)),  # vendredi → lundi
    (date(2026, 10, 10), date(2026, 10, 12)),  # samedi → lundi
    (date(2026, 10, 11), date(2026, 10, 12)),  # dimanche → lundi
])
def test_fenetre_d_annonce_jusqu_au_prochain_jour_ouvre(today, attendu):
    assert service.fin_fenetre_annonce(today) == attendu


def test_fil_annonce_la_veille_au_responsable_du_secteur(app, db, sample_users, monkeypatch):
    stagiaire_id = _stagiaire(db, tuteur_id=sample_users['responsable_id'])
    _creneau(db, stagiaire_id, '2026-10-06', 'apres_midi', sample_users['secteur_id'])
    _creneau(db, stagiaire_id, '2026-10-06', 'matin', sample_users['secteur_id'])
    actions, cartes = _cartes_stagiaires(app, db, monkeypatch, 'responsable',
                                         sample_users['responsable_id'],
                                         sample_users['secteur_id'], date(2026, 10, 5))
    assert len(cartes) == 1
    carte = cartes[0]
    assert carte['titre'] == 'Demain, accueil d’un(e) stagiaire sur votre secteur : Léa Martin'
    assert carte['detail'] == 'Toute la journée — 3e · Collège Jean Moulin — tuteur : Marie Dupont'
    assert carte['urgence'] == 'urgent'
    assert carte['badge'] == 'Demain'
    assert carte['lien'].endswith(f'/stagiaires/{stagiaire_id}#emploi-du-temps')
    assert actions.index(carte) == min(i for i, a in enumerate(actions) if a['urgence'] == 'urgent')


def test_fil_du_jour_meme_et_du_vendredi_pour_le_lundi(app, db, sample_users, monkeypatch):
    secteur = sample_users['secteur_id']
    stagiaire_id = _stagiaire(db, debut='2026-10-09', fin='2026-10-13')
    _creneau(db, stagiaire_id, '2026-10-09', 'matin', secteur)
    _creneau(db, stagiaire_id, '2026-10-12', 'apres_midi', secteur)
    _creneau(db, stagiaire_id, '2026-10-13', 'matin', secteur)
    _, cartes = _cartes_stagiaires(app, db, monkeypatch, 'responsable',
                                   sample_users['responsable_id'], secteur, date(2026, 10, 9))
    assert [c['titre'].split(',')[0] for c in cartes] == ["Aujourd'hui", 'Lundi 12 octobre']
    assert [c['badge'] for c in cartes] == [None, 'Lundi']
    assert cartes[0]['detail'].startswith('Matin — ')
    assert cartes[1]['detail'].startswith('Après-midi — ')


def test_fil_ignore_autres_secteurs_jours_lointains_et_passes(app, db, sample_users, monkeypatch):
    secteur, autre = sample_users['secteur_id'], _autre_secteur(db)
    stagiaire_id = _stagiaire(db)
    _creneau(db, stagiaire_id, '2026-10-06', 'matin', autre)    # demain, autre secteur
    _creneau(db, stagiaire_id, '2026-10-07', 'matin', secteur)  # après-demain
    _creneau(db, stagiaire_id, '2026-10-02', 'matin', secteur)  # passé
    _, cartes = _cartes_stagiaires(app, db, monkeypatch, 'responsable',
                                   sample_users['responsable_id'], secteur, date(2026, 10, 5))
    assert cartes == []


@pytest.mark.parametrize('profil, cle', [('directeur', 'directeur_id'),
                                         ('comptable', 'comptable_id'),
                                         ('salarie', 'salarie_id')])
def test_fil_reserve_au_responsable(app, db, sample_users, monkeypatch, profil, cle):
    stagiaire_id = _stagiaire(db)
    _creneau(db, stagiaire_id, '2026-10-06', 'matin', sample_users['secteur_id'])
    _, cartes = _cartes_stagiaires(app, db, monkeypatch, profil, sample_users[cle],
                                   sample_users['secteur_id'], date(2026, 10, 5))
    assert cartes == []


def test_fil_nomme_deux_stagiaires_puis_resume_le_reste(app, db, sample_users, monkeypatch):
    secteur = sample_users['secteur_id']
    for prenom in ('Ana', 'Basile', 'Chloé'):
        _creneau(db, _stagiaire(db, prenom=prenom), '2026-10-06', 'matin', secteur)
    _, cartes = _cartes_stagiaires(app, db, monkeypatch, 'responsable',
                                   sample_users['responsable_id'], secteur, date(2026, 10, 5))
    assert [c['titre'].rsplit(': ', 1)[-1] for c in cartes[:2]] == ['Ana Martin', 'Basile Martin']
    assert cartes[2]['titre'] == 'et 1 autre accueil de stagiaire'
    assert cartes[2]['detail'] == 'à retrouver dans la liste des stagiaires'
    assert cartes[2]['lien'].endswith('/stagiaires')


def test_carte_affichee_dans_l_accueil_du_responsable(resp_client, db, sample_users, monkeypatch):
    from utils import aujourd_hui
    demain = service.fin_fenetre_annonce(aujourd_hui())
    stagiaire_id = _stagiaire(db, debut=demain.isoformat(), fin=demain.isoformat())
    _creneau(db, stagiaire_id, demain.isoformat(), 'matin', sample_users['secteur_id'])
    for page in ('/accueil', '/dashboard_responsable'):
        texte = resp_client.get(page, follow_redirects=True).get_data(as_text=True)
        assert 'accueil d’un(e) stagiaire sur votre secteur : Léa Martin' in texte, page
    assert 'Vie associative' in resp_client.get('/accueil').get_data(as_text=True)


# ── Anonymisation à six mois ───────────────────────────────────────────────

@pytest.mark.parametrize('today, limite', [
    (date(2026, 10, 1), date(2026, 4, 1)),    # anonymisé le jour anniversaire
    (date(2026, 8, 28), date(2026, 2, 28)),
    (date(2026, 8, 31), date(2026, 2, 28)),
    (date(2026, 3, 15), date(2025, 9, 15)),
    (date(2027, 2, 28), date(2026, 8, 31)),   # fin 31 août → 28 février
    (date(2026, 9, 30), date(2026, 3, 31)),
])
def test_limite_d_anonymisation_six_mois(today, limite):
    assert service.limite_anonymisation(today) == limite


def test_anonymisation_efface_l_identite_et_garde_le_suivi(db, sample_users):
    ancien = _stagiaire(db, debut='2026-03-23', fin='2026-03-31', tuteur_id=sample_users['responsable_id'])
    _creneau(db, ancien, '2026-03-23', 'matin', sample_users['secteur_id'])
    anniversaire = _stagiaire(db, debut='2026-03-30', fin='2026-04-01', prenom='Inès')
    recent = _stagiaire(db, debut='2026-03-30', fin='2026-04-02', prenom='Hugo')
    assert ANONYMISER(db, date(2026, 10, 1), '2026-10-01 08:00:00') == 2
    assert db.execute('SELECT prenom FROM stagiaires WHERE id = ?', (anniversaire,)).fetchone()[0] == ''
    db.commit()
    ligne = db.execute('SELECT * FROM stagiaires WHERE id = ?', (ancien,)).fetchone()
    assert (ligne['nom'], ligne['prenom'], ligne['etablissement']) == (f'Stagiaire-{ancien}', '', '')
    assert (ligne['etudes'], ligne['tuteur_id'], ligne['date_fin']) == (
        '3e', sample_users['responsable_id'], '2026-03-31')
    assert ligne['anonymise_le'] == '2026-10-01 08:00:00'
    assert len(_creneaux(db, ancien)) == 1
    assert db.execute('SELECT prenom, anonymise_le FROM stagiaires WHERE id = ?',
                      (recent,)).fetchone()[0] == 'Hugo'
    # Idempotente : une fiche déjà anonymisée n'est pas réécrite.
    assert ANONYMISER(db, date(2026, 10, 1), '2026-10-02 08:00:00') == 0


def test_anonymisation_declenchee_par_la_premiere_requete_du_jour(resp_client, db, monkeypatch):
    stagiaire_id = _stagiaire(db, debut='2026-03-23', fin='2026-03-27')
    monkeypatch.setattr(service, 'anonymiser_stages_termines', ANONYMISER)
    monkeypatch.setattr('blueprints.stagiaires.aujourd_hui', lambda: date(2026, 10, 1))
    monkeypatch.setattr('blueprints.stagiaires._anonymisation_traitee', None)
    texte = resp_client.get('/stagiaires').get_data(as_text=True)
    assert f'Stagiaire-{stagiaire_id}' in texte and 'Léa' not in texte
    assert db.execute('SELECT anonymise_le FROM stagiaires').fetchone()[0] is not None


def test_fiche_anonymisee_en_lecture_seule(resp_client, db, sample_users):
    stagiaire_id = _stagiaire(db, debut='2026-03-23', fin='2026-03-27')
    _creneau(db, stagiaire_id, '2026-03-23', 'matin', sample_users['secteur_id'])
    ANONYMISER(db, date(2026, 10, 1), '2026-10-01 08:00:00')
    db.commit()
    fiche = resp_client.get(f'/stagiaires/{stagiaire_id}').get_data(as_text=True)
    assert 'Fiche anonymisée le 01/10/2026' in fiche
    assert fiche.count('<fieldset class="stagiaires-lecture" disabled>') == 2
    assert 'Enregistrer la fiche' not in fiche and 'Enregistrer l’emploi du temps' not in fiche

    reponse = resp_client.post(f'/stagiaires/{stagiaire_id}/informations',
                               data=_formulaire(),
                               follow_redirects=True)
    assert 'ne peut plus être modifiée' in reponse.get_data(as_text=True)
    reponse = resp_client.post(f'/stagiaires/{stagiaire_id}/emploi-du-temps', data={})
    assert reponse.status_code == 302
    ligne = db.execute('SELECT nom, prenom FROM stagiaires').fetchone()
    assert tuple(ligne) == (f'Stagiaire-{stagiaire_id}', '')
    assert len(_creneaux(db, stagiaire_id)) == 1
    assert resp_client.post(f'/stagiaires/{stagiaire_id}/supprimer').status_code == 302
    assert db.execute('SELECT COUNT(*) FROM stagiaires').fetchone()[0] == 0


# ── Schéma ─────────────────────────────────────────────────────────────────

def test_schema_neuf_et_migration_0075_idempotente(db, sample_users):
    migration = importlib.import_module('migrations.0075_suivi_stagiaires')
    assert ('0075', migration.NOM) in ALL_MIGRATION_VERSIONS

    def ddl():
        return sorted(r[0] for r in db.execute(
            "SELECT sql FROM sqlite_master WHERE tbl_name IN ('stagiaires', 'stagiaires_creneaux') "
            "AND sql IS NOT NULL"))
    neuf = ddl()
    migration.downgrade(db)
    migration.upgrade(db)
    stagiaire_id = _stagiaire(db)
    _creneau(db, stagiaire_id, '2026-10-05', 'matin', sample_users['secteur_id'])
    migration.upgrade(db)
    db.commit()
    assert ddl() == neuf
    assert db.execute('SELECT COUNT(*) FROM stagiaires_creneaux').fetchone()[0] == 1


def test_supprimer_un_secteur_retire_ses_demi_journees(admin_client, db, sample_users):
    """Sans foreign_keys activé, l'orphelin ferait refuser les sauvegardes."""
    secteur, autre = sample_users['secteur_id'], _autre_secteur(db)
    stagiaire_id = _stagiaire(db)
    _creneau(db, stagiaire_id, '2026-10-05', 'matin', autre)
    _creneau(db, stagiaire_id, '2026-10-05', 'apres_midi', secteur)
    reponse = admin_client.post('/gestion_secteurs', data={'action': 'supprimer', 'secteur_id': str(autre)},
                                follow_redirects=True)
    assert '1 demi-journée d&#39;emploi du temps de stagiaire retirée' in reponse.get_data(as_text=True)
    assert db.execute('SELECT 1 FROM secteurs WHERE id = ?', (autre,)).fetchone() is None
    assert _creneaux(db, stagiaire_id) == {('2026-10-05', 'apres_midi', secteur)}
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_badge_du_fil_dit_le_vrai_jour(resp_client, db, sample_users):
    from utils import aujourd_hui
    demain = service.fin_fenetre_annonce(aujourd_hui())
    stagiaire_id = _stagiaire(db, debut=demain.isoformat(), fin=demain.isoformat())
    _creneau(db, stagiaire_id, demain.isoformat(), 'matin', sample_users['secteur_id'])
    texte = resp_client.get('/accueil').get_data(as_text=True)
    badge = 'Demain' if (demain - aujourd_hui()).days == 1 else 'Lundi'
    assert f'<span class="flx-badge">{badge}</span>' in texte
