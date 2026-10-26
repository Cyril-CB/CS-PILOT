"""Journée de solidarité : configuration annuelle et circuits CP/CC."""
import pytest


def _ferie(db, jour='2026-11-11'):
    cur = db.execute('INSERT INTO jours_feries (annee,date,libelle) VALUES (?,?,?)',
                     (int(jour[:4]), jour, 'Férié test'))
    db.commit()
    return cur.lastrowid


def _designer(admin_client, ferie_id):
    return admin_client.post('/gestion_jours_feries', data={
        'action': 'solidarite', 'ferie_id': ferie_id}, follow_redirects=True)


@pytest.mark.parametrize('type_conge', ['Congé payé', 'Congé conventionnel'])
def test_conge_sur_solidarite_est_compte(auth_client, admin_client, db, sample_users, type_conge):
    _designer(admin_client, _ferie(db))
    # Les clients partagent la même session : rétablir le salarié explicitement.
    auth_client.post('/login', data={'login': 'salarie_test', 'password': 'sal123'})
    response = auth_client.post('/demande_conge', data={
        'type_conge': type_conge, 'date_debut': '2026-11-11', 'date_fin': '2026-11-11'})
    demande = db.execute('SELECT * FROM demandes_conges WHERE user_id=?',
                         (sample_users['salarie_id'],)).fetchone()
    assert demande is not None
    assert demande['nb_jours'] == 1
    assert demande['type_conge'] == type_conge


def _login(client, profil):
    comptes = {'salarie': ('salarie_test', 'sal123'), 'directeur': ('admin', 'Admin1234'),
               'comptable': ('compta_test', 'compta123'), 'responsable': ('resp_test', 'resp123')}
    login, password = comptes[profil]
    client.post('/login', data={'login': login, 'password': password})


@pytest.mark.parametrize('profil', ['directeur', 'comptable'])
def test_designation_annuelle_remplacement_et_retrait(client, db, sample_users, profil):
    ids = [_ferie(db, j) for j in ('2026-11-11', '2026-12-25', '2027-08-16')]
    _login(client, profil)
    for i in (0, 2, 1):
        assert 'désignée' in _designer(client, ids[i]).get_data(as_text=True)
    actifs = db.execute('SELECT date FROM jours_feries WHERE solidarite=1 ORDER BY date').fetchall()
    assert [r['date'] for r in actifs] == ['2026-12-25', '2027-08-16']
    _designer(client, ids[1])
    assert db.execute('SELECT COUNT(*) FROM jours_feries WHERE solidarite=1').fetchone()[0] == 1


@pytest.mark.parametrize('profil', ['salarie', 'responsable'])
def test_designation_interdite_autres_profils(client, db, sample_users, profil):
    fid = _ferie(db)
    _login(client, profil)
    response = client.post('/gestion_jours_feries', data={'action': 'solidarite', 'ferie_id': fid})
    assert response.status_code == 302
    assert db.execute('SELECT solidarite FROM jours_feries WHERE id=?', (fid,)).fetchone()[0] == 0


def test_designation_non_connecte_refusee(client, db):
    fid = _ferie(db)
    assert client.post('/gestion_jours_feries', data={'action': 'solidarite', 'ferie_id': fid}).status_code == 302
    assert db.execute('SELECT solidarite FROM jours_feries').fetchone()[0] == 0


@pytest.mark.parametrize('jour', ['2026-08-15', '2026-11-01'])
def test_weekend_refuse_et_ancienne_designation_preservee(admin_client, db, jour):
    fid = _ferie(db)
    _designer(admin_client, fid)
    response = _designer(admin_client, _ferie(db, jour))
    assert 'lundi au vendredi' in response.get_data(as_text=True)
    assert db.execute('SELECT solidarite FROM jours_feries WHERE id=?', (fid,)).fetchone()[0] == 1


def test_id_inconnu_refuse(admin_client, db):
    assert 'introuvable' in _designer(admin_client, 99999).get_data(as_text=True)
    assert db.execute('SELECT COUNT(*) FROM jours_feries').fetchone()[0] == 0


@pytest.mark.parametrize('type_conge,compteur', [('Congé payé', 'cp_pris'), ('Congé conventionnel', 'cc_solde')])
def test_validation_report_compteur_idempotence_et_annulation(admin_client, db, sample_users, type_conge, compteur):
    _designer(admin_client, _ferie(db))
    uid = sample_users['salarie_id']
    db.execute('UPDATE users SET cp_a_prendre=10,cp_pris=0,cc_solde=8 WHERE id=?', (uid,))
    db.commit()
    _login(admin_client, 'salarie')
    admin_client.post('/demande_conge', data={'type_conge': type_conge,
        'date_debut': '2026-11-11', 'date_fin': '2026-11-11'})
    demande = db.execute('SELECT * FROM demandes_conges WHERE user_id=?', (uid,)).fetchone()
    assert demande['nb_jours'] == 1
    assert db.execute(f'SELECT {compteur} FROM users WHERE id=?', (uid,)).fetchone()[0] == (0 if compteur=='cp_pris' else 8)
    _login(admin_client, 'directeur')
    for _ in range(2):
        admin_client.post('/validation_demandes_recup', data={
            'demande_id': demande['id'], 'demande_type': 'conge', 'action': 'valider'})
    absence = db.execute('SELECT * FROM absences WHERE user_id=?', (uid,)).fetchone()
    assert absence['jours_ouvres'] == 1
    assert db.execute('SELECT COUNT(*) FROM absences WHERE user_id=?', (uid,)).fetchone()[0] == 1
    assert db.execute('SELECT type_saisie FROM heures_reelles WHERE user_id=? AND date=?', (uid,'2026-11-11')).fetchone()[0] == 'absence'
    assert db.execute('SELECT COUNT(*) FROM rh_projections WHERE absence_id=?', (absence['id'],)).fetchone()[0] == 1
    assert db.execute(f'SELECT {compteur} FROM users WHERE id=?', (uid,)).fetchone()[0] == (1 if compteur=='cp_pris' else 7)
    admin_client.post(f"/absences/supprimer/{absence['id']}")
    assert db.execute(f'SELECT {compteur} FROM users WHERE id=?', (uid,)).fetchone()[0] == (0 if compteur=='cp_pris' else 8)
    assert db.execute('SELECT COUNT(*) FROM heures_reelles WHERE user_id=?', (uid,)).fetchone()[0] == 0


@pytest.mark.parametrize('type_conge', ['Congé payé', 'Congé conventionnel'])
def test_saisie_manuelle_cp_cc_sur_solidarite(comptable_client, db, sample_users, type_conge):
    _designer(comptable_client, _ferie(db))
    uid = sample_users['salarie_id']
    response = comptable_client.post('/absences', data={'user_id': uid, 'motif': type_conge,
        'date_debut': '2026-11-11', 'date_fin': '2026-11-11'}, follow_redirects=True)
    assert 'enregistrée avec succès' in response.get_data(as_text=True)
    assert db.execute('SELECT jours_ouvres FROM absences WHERE user_id=?', (uid,)).fetchone()[0] == 1
    assert db.execute('SELECT type_saisie FROM heures_reelles WHERE user_id=?', (uid,)).fetchone()[0] == 'absence'


@pytest.mark.parametrize('type_conge,compteur', [('Congé payé', 'conge_paye'), ('Congé conventionnel', 'conge_conv')])
def test_directeur_auto_validation_et_solde_forfait(admin_client, app, db, sample_users, type_conge, compteur):
    from utils import calculer_stats_forfait_jour
    _designer(admin_client, _ferie(db))
    uid = sample_users['directeur_id']
    with app.app_context():
        avant = calculer_stats_forfait_jour(uid,2026)
    response = admin_client.post('/demande_conge', data={'type_conge': type_conge,
        'date_debut':'2026-11-11','date_fin':'2026-11-11'},follow_redirects=True)
    assert 'validé' in response.get_data(as_text=True)
    assert db.execute('SELECT statut FROM demandes_conges WHERE user_id=?',(uid,)).fetchone()[0]=='validee'
    assert db.execute('SELECT type_journee FROM presence_forfait_jour WHERE user_id=? AND date=?',(uid,'2026-11-11')).fetchone()[0]==compteur
    with app.app_context():
        apres = calculer_stats_forfait_jour(uid,2026)
    assert apres[compteur] == avant[compteur]+1
    assert apres['config']['jours_repos_forfait'] == avant['config']['jours_repos_forfait']
    assert not db.execute('SELECT cp_pris FROM users WHERE id=?',(uid,)).fetchone()[0]


def test_periode_englobante_fait_exception_une_fois(admin_client, db, sample_users):
    from solidarite import jours_absence
    _designer(admin_client, _ferie(db))
    _ferie(db,'2026-11-12')
    assert jours_absence(db,'2026-11-09','2026-11-15','Congé payé') == ['2026-11-09','2026-11-10','2026-11-11','2026-11-13']
    assert jours_absence(db,'2026-11-09','2026-11-15','Arrêt maladie') == ['2026-11-09','2026-11-10','2026-11-13']
    assert jours_absence(db,'2026-11-15','2026-11-09','Congé payé') == []
    _login(admin_client,'salarie')
    admin_client.post('/demande_conge',data={'type_conge':'Congé payé','date_debut':'2026-11-09','date_fin':'2026-11-15'})
    assert db.execute('SELECT nb_jours FROM demandes_conges').fetchone()[0] == 4


def test_ferie_ordinaire_reste_exclu(auth_client, db, sample_users):
    _ferie(db)
    auth_client.post('/demande_conge',data={'type_conge':'Congé payé','date_debut':'2026-11-11','date_fin':'2026-11-11'})
    assert db.execute('SELECT COUNT(*) FROM demandes_conges').fetchone()[0] == 0


@pytest.mark.parametrize('motif,nombre',[('Congé payé',1),('Congé conventionnel',1),('Forfait jour',0),('Arrêt maladie',0)])
def test_api_apercu_absence_aligne_motif(admin_client, db, motif, nombre):
    _designer(admin_client,_ferie(db))
    response=admin_client.get('/api/absences/jours_ouvres',query_string={
        'date_debut':'2026-11-11','date_fin':'2026-11-11','motif':motif})
    assert response.json == {'jours_ouvres':nombre}


@pytest.mark.parametrize('partielle',[False,True])
@pytest.mark.parametrize('periode',[('2026-11-11','2026-11-11'),('2026-11-10','2026-11-12')])
def test_recuperation_creation_refusee(admin_client, db, sample_users, sample_planning, partielle, periode):
    _designer(admin_client,_ferie(db))
    _login(admin_client,'salarie')
    debut,fin=periode
    if partielle:
        debut=fin='2026-11-11'
    data={'date_debut':debut,'date_fin':fin,'type_demande':'partielle' if partielle else 'journee',
          'heure_debut':'08:30','heure_fin':'10:30'}
    admin_client.post('/demande_recup',data=data)
    assert db.execute('SELECT COUNT(*) FROM demandes_recup').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM heures_reelles').fetchone()[0] == 0


@pytest.mark.parametrize('partielle',[False,True])
def test_recuperation_historique_validation_refusee_atomiquement(admin_client, db, sample_users, sample_planning, partielle):
    _designer(admin_client,_ferie(db))
    uid=sample_users['salarie_id']
    cur=db.execute('''INSERT INTO demandes_recup(user_id,date_debut,date_fin,nb_jours,nb_heures,type_demande,heure_debut,heure_fin,statut)
        VALUES(?,?,?,?,?,?,?,?,?)''',(uid,'2026-11-11','2026-11-11',1,7,'partielle' if partielle else 'journee','08:30','12:00','en_attente_direction'))
    did=cur.lastrowid;db.commit()
    response=admin_client.post('/validation_demandes_recup',data={'demande_id':did,'action':'valider'},follow_redirects=True)
    assert 'ne peut pas être prise en récupération' in response.get_data(as_text=True)
    assert db.execute('SELECT statut FROM demandes_recup WHERE id=?',(did,)).fetchone()[0] == 'en_attente_direction'
    assert db.execute('SELECT COUNT(*) FROM heures_reelles').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM rh_projections').fetchone()[0] == 0


def test_saisie_directe_recuperation_refusee(admin_client, db, sample_users, sample_contrat):
    _designer(admin_client,_ferie(db))
    _login(admin_client,'salarie')
    response=admin_client.post('/saisie_heures',data={'date':'2026-11-11','recup_journee':'1'},follow_redirects=True)
    assert 'ne peut pas être prise en récupération' in response.get_data(as_text=True)
    assert db.execute('SELECT COUNT(*) FROM heures_reelles').fetchone()[0] == 0


@pytest.mark.parametrize('origine',['absence','conge','recup'])
@pytest.mark.parametrize('action',['deplacer','retirer','supprimer'])
def test_reconfiguration_refusee_si_date_utilisee(admin_client, db, sample_users, origine, action):
    premier=_ferie(db);second=_ferie(db,'2026-12-25');_designer(admin_client,premier)
    uid=sample_users['salarie_id']
    if origine=='absence':
        db.execute("INSERT INTO absences(user_id,motif,date_debut,date_fin,jours_ouvres,saisi_par) VALUES(?,'Congé payé','2026-11-11','2026-11-11',1,?)",(uid,sample_users['directeur_id']))
    else:
        table='demandes_conges' if origine=='conge' else 'demandes_recup'
        extra=",type_conge" if origine=='conge' else ',nb_heures'
        valeur=",'Congé payé'" if origine=='conge' else ',7'
        db.execute(f"INSERT INTO {table}(user_id,date_debut,date_fin,nb_jours,statut{extra}) VALUES(?,'2026-11-11','2026-11-11',1,'en_attente_direction'{valeur})",(uid,))
    db.commit()
    if action=='supprimer':
        response=admin_client.post('/gestion_jours_feries',data={'action':'supprimer','ferie_id':premier},follow_redirects=True)
    else:
        response=_designer(admin_client,second if action=='deplacer' else premier)
    assert 'aucun décompte existant' in response.get_data(as_text=True)
    assert db.execute('SELECT solidarite FROM jours_feries WHERE id=?',(premier,)).fetchone()[0] == 1
    assert db.execute('SELECT COUNT(*) FROM jours_feries').fetchone()[0] == 2


def test_aucun_changement_aux_jours_ouvres_generaux(admin_client, db):
    from utils import calculer_jours_ouvres
    _designer(admin_client,_ferie(db))
    assert calculer_jours_ouvres('2026-11-11','2026-11-11') == 0


def test_migration_ancien_schema_idempotence_donnees_et_unicite():
    import importlib
    import sqlite3
    migration=importlib.import_module('migrations.0081_journee_solidarite')
    conn=sqlite3.connect(':memory:')
    conn.executescript("CREATE TABLE jours_feries(id INTEGER PRIMARY KEY,annee INTEGER,date TEXT UNIQUE,libelle TEXT); INSERT INTO jours_feries VALUES(1,2026,'2026-11-11','Armistice'),(2,2026,'2026-12-25','Noël');")
    migration.upgrade(conn);migration.upgrade(conn)
    assert conn.execute('SELECT * FROM jours_feries ORDER BY id').fetchall()==[(1,2026,'2026-11-11','Armistice',0),(2,2026,'2026-12-25','Noël',0)]
    conn.execute('UPDATE jours_feries SET solidarite=1 WHERE id=1')
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('UPDATE jours_feries SET solidarite=1 WHERE id=2')
    with pytest.raises(ValueError,match='retour arrière refusé'):
        migration.downgrade(conn)
    conn.execute('UPDATE jours_feries SET solidarite=0')
    migration.downgrade(conn);migration.upgrade(conn)
    assert conn.execute('SELECT COUNT(*) FROM jours_feries').fetchone()[0]==2
    conn.close()


def test_schema_neuf_migration_enregistree_et_rollback(db):
    from database import ALL_MIGRATION_VERSIONS
    assert any(version=='0081' for version,_ in ALL_MIGRATION_VERSIONS)
    assert 'solidarite' in {r['name'] for r in db.execute('PRAGMA table_info(jours_feries)')}
    fid=_ferie(db)
    db.execute('BEGIN IMMEDIATE')
    db.execute('UPDATE jours_feries SET solidarite=1 WHERE id=?',(fid,))
    db.rollback()
    assert db.execute('SELECT solidarite FROM jours_feries WHERE id=?',(fid,)).fetchone()[0]==0


def test_annulation_forfait_ne_transforme_pas_ferie_en_travail(admin_client, app, db, sample_users):
    from utils import calculer_stats_forfait_jour
    _designer(admin_client,_ferie(db))
    uid=sample_users['directeur_id']
    admin_client.post('/demande_conge',data={'type_conge':'Congé payé','date_debut':'2026-11-11','date_fin':'2026-11-11'})
    aid=db.execute('SELECT id FROM absences WHERE user_id=?',(uid,)).fetchone()[0]
    with app.app_context():
        avant=calculer_stats_forfait_jour(uid,2026)
    admin_client.post(f'/absences/supprimer/{aid}')
    with app.app_context():
        apres=calculer_stats_forfait_jour(uid,2026)
    assert apres['conge_paye']==0
    assert apres['travaille']==avant['travaille']
    assert not db.execute('SELECT 1 FROM presence_forfait_jour WHERE user_id=? AND date=?',(uid,'2026-11-11')).fetchone()


def test_deplacement_refuse_si_nouvelle_date_utilisee(admin_client, db, sample_users):
    premier=_ferie(db);second=_ferie(db,'2026-12-25');_designer(admin_client,premier)
    db.execute("INSERT INTO demandes_conges(user_id,type_conge,date_debut,date_fin,nb_jours,statut) VALUES(?,'Congé payé','2026-12-24','2026-12-28',2,'en_attente_direction')",(sample_users['salarie_id'],));db.commit()
    assert 'aucun décompte existant' in _designer(admin_client,second).get_data(as_text=True)
    assert db.execute('SELECT solidarite FROM jours_feries WHERE id=?',(premier,)).fetchone()[0]==1


def test_session_revoquee_ne_peut_designer(admin_client, db, sample_users):
    fid=_ferie(db)
    db.execute('UPDATE users SET actif=0 WHERE id=?',(sample_users['directeur_id'],));db.commit()
    response=admin_client.post('/gestion_jours_feries',data={'action':'solidarite','ferie_id':fid})
    assert response.status_code==302
    assert db.execute('SELECT solidarite FROM jours_feries WHERE id=?',(fid,)).fetchone()[0]==0


def test_projection_forfait_et_fiches_sont_alignees(admin_client, app, db, sample_users, sample_contrat):
    from blueprints.recup import _projection_conge
    _designer(admin_client,_ferie(db))
    with app.app_context():
        projection=_projection_conge(db,sample_users['directeur_id'],'directeur','Congé payé','2026-11-11','2026-11-11',1)
    assert projection==[{'annee':2026,'jours':1,'solde_apres':24}]
    # Le libellé est aussi servi par le calendrier horaire.
    _login(admin_client,'salarie')
    response=admin_client.get('/vue_calendrier?mois=11&annee=2026')
    assert 'Journée de solidarité' in response.get_data(as_text=True)


def test_projection_et_decompte_sur_deux_annees(admin_client, app, db, sample_users):
    from solidarite import jours_absence
    from blueprints.recup import _projection_conge
    for jour in ('2026-12-31','2027-01-01'):
        _designer(admin_client,_ferie(db,jour))
    assert len(jours_absence(db,'2026-12-31','2027-01-01','Congé conventionnel'))==2
    with app.app_context():
        projection=_projection_conge(db,sample_users['directeur_id'],'directeur','Congé conventionnel','2026-12-31','2027-01-01',2)
    assert projection==[{'annee':2026,'jours':1,'solde_apres':7},{'annee':2027,'jours':1,'solde_apres':7}]
