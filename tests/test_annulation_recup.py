"""Annulations et remplacements, données synthétiques uniquement."""
import importlib
import pytest
from utils import calculer_solde_recup
from tests.test_coherence_rh import ajouter_absence, approuver


def recuperation(db, client, uid, debut='2025-09-08', fin='2025-09-08', partielle=False):
    did = db.execute('''INSERT INTO demandes_recup
        (user_id,date_debut,date_fin,nb_jours,nb_heures,statut,type_demande,heure_debut,heure_fin)
        VALUES (?,?,?,?,?,'en_attente_direction',?,?,?)''',
        (uid,debut,fin,1 if partielle else 3 if fin!=debut else 1,
         3 if partielle else 21 if fin!=debut else 7,
         'partielle' if partielle else 'journee','14:00' if partielle else None,
         '17:00' if partielle else None)).lastrowid
    db.commit()
    approuver(client,did)
    assert db.execute('SELECT statut FROM demandes_recup WHERE id=?',(did,)).fetchone()[0]=='validee'
    return did


def annuler(client, did, **extra):
    return client.post(f'/recuperations/{did}/annuler',data={'motif':'Le salarié a finalement travaillé',**extra},follow_redirects=True)


@pytest.mark.parametrize('acteur',['admin_client','comptable_client'])
@pytest.mark.parametrize('partielle',[False,True])
def test_annulation_restitue_sans_inventer_heures(request,acteur,partielle,admin_client,db,sample_users,sample_planning):
    uid=sample_users['salarie_id'];did=recuperation(db,admin_client,uid,partielle=partielle)
    assert calculer_solde_recup(uid)==(-3 if partielle else -7)
    response=annuler(request.getfixturevalue(acteur),did)
    assert response.status_code==200
    assert db.execute('SELECT statut FROM demandes_recup WHERE id=?',(did,)).fetchone()[0]=='annulee'
    assert db.execute('SELECT COUNT(*) FROM heures_reelles WHERE user_id=?',(uid,)).fetchone()[0]==0
    assert calculer_solde_recup(uid)==0
    assert db.execute('SELECT COUNT(*) FROM rh_projections WHERE demande_recup_id=?',(did,)).fetchone()[0]==0


def test_arret_ne_remplace_que_jour_couvert(admin_client,db,sample_users,sample_planning):
    uid=sample_users['salarie_id'];did=recuperation(db,admin_client,uid,fin='2025-09-10')
    ajouter_absence(admin_client,uid,'2025-09-09',motif='Arrêt maladie')
    assert db.execute('SELECT motif FROM absences WHERE user_id=?',(uid,)).fetchone()[0]=='Arrêt maladie'
    assert [tuple(r) for r in db.execute('SELECT date,type_saisie FROM heures_reelles WHERE user_id=? ORDER BY date',(uid,))]==[
        ('2025-09-08','recup_journee'),('2025-09-09','absence'),('2025-09-10','recup_journee')]
    assert calculer_solde_recup(uid)==-14
    assert db.execute('SELECT statut FROM demandes_recup WHERE id=?',(did,)).fetchone()[0]=='validee'


@pytest.mark.parametrize('acteur',['auth_client','resp_client','prestataire_client','anonymous'])
def test_annulation_interdite(request,acteur,app,admin_client,db,sample_users,sample_planning):
    uid=sample_users['salarie_id'];did=recuperation(db,admin_client,uid)
    annuler(app.test_client() if acteur=='anonymous' else request.getfixturevalue(acteur),did)
    assert db.execute('SELECT statut FROM demandes_recup WHERE id=?',(did,)).fetchone()[0]=='validee'
    assert calculer_solde_recup(uid)==-7


def test_annulation_motif_requis(admin_client,db,sample_users,sample_planning):
    did=recuperation(db,admin_client,sample_users['salarie_id'])
    annuler(admin_client,did,motif=' ')
    assert db.execute('SELECT statut FROM demandes_recup WHERE id=?',(did,)).fetchone()[0]=='validee'


def test_double_annulation_idempotente(admin_client,db,sample_users,sample_planning):
    did=recuperation(db,admin_client,sample_users['salarie_id'])
    annuler(admin_client,did);annuler(admin_client,did)
    assert db.execute('SELECT COUNT(*) FROM recup_annulations WHERE demande_recup_id=?',(did,)).fetchone()[0]==1
    assert db.execute("SELECT COUNT(*) FROM historique_modifications WHERE action='annulation_recup'").fetchone()[0]==1


@pytest.mark.parametrize('motif',['Arrêt maladie','Accident du travail'])
@pytest.mark.parametrize('partielle',[False,True])
def test_arret_remplace_recuperation_complete(admin_client,db,sample_users,sample_planning,motif,partielle):
    uid=sample_users['salarie_id'];did=recuperation(db,admin_client,uid,partielle=partielle)
    ajouter_absence(admin_client,uid,'2025-09-08',motif=motif)
    assert db.execute('SELECT statut FROM demandes_recup WHERE id=?',(did,)).fetchone()[0]=='annulee'
    assert db.execute('SELECT type_saisie FROM heures_reelles WHERE user_id=?',(uid,)).fetchone()[0]=='absence'
    assert calculer_solde_recup(uid)==0
    a=db.execute('SELECT * FROM recup_annulations WHERE demande_recup_id=?',(did,)).fetchone()
    assert a['absence_id']==db.execute('SELECT id FROM absences').fetchone()[0]
    assert a['auteur_id']==sample_users['directeur_id']
    assert a['nb_heures']==(3 if partielle else 7)


def test_annulation_partielle_puis_saisie_salarie(auth_client,admin_client,app,db,sample_users,sample_planning,sample_contrat):
    uid=sample_users['salarie_id'];did=recuperation(db,admin_client,uid,fin='2025-09-10')
    annuler(admin_client,did,date_debut='2025-09-09',date_fin='2025-09-09')
    from tests.conftest import _login
    sal=app.test_client();_login(sal,'salarie_test','sal123')
    sal.post('/saisie_heures',data={'date':'2025-09-09','heure_debut_matin':'08:30','heure_fin_matin':'12:00','heure_debut_aprem':'13:30','heure_fin_aprem':'17:00'},follow_redirects=True)
    row=db.execute("SELECT * FROM heures_reelles WHERE user_id=? AND date='2025-09-09'",(uid,)).fetchone()
    assert row is not None and row['type_saisie'] not in ('recup_journee','recup_partielle')
    assert calculer_solde_recup(uid)==-14


@pytest.mark.parametrize('operation',['annulation','arret'])
def test_mois_verrouille_rollback(admin_client,db,sample_users,sample_planning,operation):
    uid=sample_users['salarie_id'];did=recuperation(db,admin_client,uid,fin='2025-09-10')
    db.execute('INSERT INTO validations(user_id,mois,annee,bloque) VALUES (?,9,2025,1)',(uid,));db.commit()
    avant=[tuple(r) for r in db.execute('SELECT * FROM heures_reelles ORDER BY date')]
    if operation=='annulation':r=annuler(admin_client,did)
    else:r=ajouter_absence(admin_client,uid,'2025-09-09',motif='Arrêt maladie')
    assert 'verrouill' in r.get_data(as_text=True)
    assert [tuple(r) for r in db.execute('SELECT * FROM heures_reelles ORDER BY date')]==avant
    assert db.execute('SELECT COUNT(*) FROM recup_annulations').fetchone()[0]==0
    assert db.execute('SELECT COUNT(*) FROM absences').fetchone()[0]==0


@pytest.mark.parametrize('motif',['Congé payé','Congé parental','Autre'])
def test_autres_absences_ne_remplacent_pas(admin_client,db,sample_users,sample_planning,motif):
    uid=sample_users['salarie_id'];did=recuperation(db,admin_client,uid)
    ajouter_absence(admin_client,uid,'2025-09-08',motif=motif)
    assert db.execute('SELECT COUNT(*) FROM absences').fetchone()[0]==0
    assert db.execute('SELECT statut FROM demandes_recup WHERE id=?',(did,)).fetchone()[0]=='validee'


def test_historique_sans_preuve_reconnu_sans_confondre_id(admin_client,db,sample_users,sample_planning):
    uid=sample_users['salarie_id'];did=recuperation(db,admin_client,uid)
    db.execute('DELETE FROM rh_projections WHERE demande_recup_id=?',(did,));db.commit()
    annuler(admin_client,did)
    assert db.execute('SELECT statut FROM demandes_recup WHERE id=?',(did,)).fetchone()[0]=='annulee'


def test_historique_ambigu_refuse(admin_client,db,sample_users,sample_planning):
    uid=sample_users['salarie_id'];did=recuperation(db,admin_client,uid)
    db.execute('DELETE FROM rh_projections WHERE demande_recup_id=?',(did,))
    db.execute("UPDATE heures_reelles SET commentaire='Récupération - Demande #999 validée' WHERE user_id=?",(uid,));db.commit()
    annuler(admin_client,did)
    assert db.execute('SELECT statut FROM demandes_recup WHERE id=?',(did,)).fetchone()[0]=='validee'
    assert db.execute('SELECT COUNT(*) FROM recup_annulations').fetchone()[0]==0


def test_retrait_arret_ne_reactive_pas_recup(admin_client,db,sample_users,sample_planning):
    uid=sample_users['salarie_id'];did=recuperation(db,admin_client,uid)
    ajouter_absence(admin_client,uid,'2025-09-08',motif='Arrêt maladie')
    aid=db.execute('SELECT id FROM absences').fetchone()[0]
    admin_client.post(f'/absences/supprimer/{aid}')
    assert db.execute('SELECT statut FROM demandes_recup WHERE id=?',(did,)).fetchone()[0]=='annulee'
    assert db.execute('SELECT COUNT(*) FROM heures_reelles WHERE user_id=?',(uid,)).fetchone()[0]==0


def test_csrf_conserve(app,admin_client,db,sample_users,sample_planning,monkeypatch):
    did=recuperation(db,admin_client,sample_users['salarie_id'])
    monkeypatch.setitem(app.config,'WTF_CSRF_ENABLED',True)
    r=admin_client.post(f'/recuperations/{did}/annuler',data={'motif':'Test'})
    assert r.status_code==302 and '/login' in r.location
    assert db.execute('SELECT statut FROM demandes_recup WHERE id=?',(did,)).fetchone()[0]=='validee'


def test_migration_neuve_idempotente_sans_reprise(db,sample_users):
    m=importlib.import_module('migrations.0082_annulation_recuperations')
    db.execute('DROP TABLE recup_annulations');db.commit()
    for _ in range(2):m.upgrade(db);db.commit()
    assert db.execute('SELECT COUNT(*) FROM recup_annulations').fetchone()[0]==0
    from database import ALL_MIGRATION_VERSIONS
    assert any(v[0]=='0082' for v in ALL_MIGRATION_VERSIONS)
