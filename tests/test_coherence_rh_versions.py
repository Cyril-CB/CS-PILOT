"""Réouvertures, concurrence et rollback intégral du lot B7/B8/B9."""
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from database import get_db
from tests.conftest import _login
from tests.test_coherence_rh import ajouter_absence, approuver, etat, traiter


def completer(db, uid, mois):
    j=date(2026,mois,1)
    while j.month==mois:
        if j.weekday()<5:
            db.execute("INSERT OR IGNORE INTO heures_reelles(user_id,date,type_saisie,declaration_conforme) VALUES (?,?,'normal',1)",(uid,j.isoformat()))
        j+=timedelta(days=1)
    db.commit()


def signer_mois(client, uid, mois):
    from fiches_contenu import calculer_contenu
    from fiches_versions import empreinte
    conn=get_db()
    try:ref=empreinte(calculer_contenu(conn,uid,mois,2026))
    finally:conn.close()
    return client.post('/valider_mois',data={'user_id':uid,'mois':mois,'annee':2026,'empreinte_fiche':ref})


@pytest.fixture
def acteurs(app, sample_users):
    clients=[]
    for login,password in [('salarie_test','sal123'),('resp_test','resp123'),('admin','Admin1234')]:
        c=app.test_client();_login(c,login,password);clients.append(c)
    return clients


def fermer(acteurs,uid,mois):
    for c in acteurs:signer_mois(c,uid,mois)


def rouvrir(c,uid,mois):
    return c.post('/deverrouiller_mois',data={'user_id':uid,'mois':mois,'annee':2026,'motif':'Correction de récupération reçue après clôture'})


@pytest.mark.parametrize('mois_fermes',[(8,),(7,8)])
def test_b9_multimois_pas_de_report_partiel(db,sample_users,sample_planning,sample_contrat,acteurs,mois_fermes,monkeypatch):
    uid=sample_users['salarie_id'];direction=acteurs[2]
    completer(db,uid,7);completer(db,uid,8)
    did=db.execute("""INSERT INTO demandes_recup(user_id,date_debut,date_fin,nb_jours,nb_heures,statut)
        VALUES (?,'2026-07-31','2026-08-03',2,14,'en_attente_direction')""",(uid,)).lastrowid
    db.commit()
    for mois in mois_fermes:fermer(acteurs,uid,mois)
    assert all(db.execute('SELECT bloque FROM validations WHERE mois=? AND user_id=?',(m,uid)).fetchone()[0] for m in mois_fermes)
    # La clôture ne supprime pas une précédente vérification de paie.
    appels=[];monkeypatch.setattr('blueprints.recup.is_email_configured',lambda:appels.append(True) or False)
    avant=etat(db);response=approuver(direction,did)
    assert 'verrouill' in response.get_data(as_text=True)
    assert etat(db)==avant and not appels
    if len(mois_fermes)==2:
        rouvrir(direction,uid,7)
        avant=etat(db);approuver(direction,did)
        assert etat(db)==avant and not appels
    rouvrir(direction,uid,8)
    approuver(direction,did)
    assert db.execute('SELECT statut FROM demandes_recup WHERE id=?',(did,)).fetchone()[0]=='validee'
    assert db.execute('SELECT COUNT(*) FROM rh_projections WHERE demande_recup_id=?',(did,)).fetchone()[0]==2
    assert db.execute('SELECT COUNT(*) FROM validations WHERE user_id=? AND bloque=1',(uid,)).fetchone()[0]==0
    apres=etat(db);approuver(direction,did);assert etat(db)==apres
    # La direction ne peut clôturer immédiatement après le report.
    signer_mois(direction,uid,8)
    assert not db.execute('SELECT 1 FROM validations WHERE user_id=? AND mois=8 AND bloque=1',(uid,)).fetchone()
    fermer(acteurs,uid,8)
    v=db.execute('SELECT * FROM validations WHERE user_id=? AND mois=8',(uid,)).fetchone()
    assert v['bloque'] and v['version_salarie_id']==v['version_responsable_id']==v['version_directeur_id']==v['version_courante_id']
    assert db.execute('SELECT COUNT(*) FROM fiches_versions WHERE user_id=? AND mois=8',(uid,)).fetchone()[0]>=2


def test_b9_partielle_verrouillee_reprise_version(db,sample_users,sample_planning,sample_contrat,acteurs):
    uid=sample_users['salarie_id'];completer(db,uid,8)
    did=db.execute("""INSERT INTO demandes_recup(user_id,date_debut,date_fin,nb_jours,nb_heures,type_demande,heure_debut,heure_fin,statut)
        VALUES (?,'2026-08-03','2026-08-03',.43,3,'partielle','14:00','17:00','en_attente_direction')""",(uid,)).lastrowid
    db.commit();fermer(acteurs,uid,8)
    avant=etat(db);approuver(acteurs[2],did);assert etat(db)==avant
    rouvrir(acteurs[2],uid,8);approuver(acteurs[2],did)
    assert db.execute('SELECT heure_fin_aprem FROM heures_reelles WHERE date="2026-08-03" AND user_id=?',(uid,)).fetchone()[0]=='14:00'
    signer_mois(acteurs[1],uid,8)
    assert not db.execute('SELECT 1 FROM validations WHERE user_id=?',(uid,)).fetchone()
    fermer(acteurs,uid,8)
    assert db.execute('SELECT bloque FROM validations WHERE user_id=?',(uid,)).fetchone()[0]


def test_b7_multimois_versions_et_refus_verrou(db,sample_users,sample_planning,sample_contrat,acteurs):
    uid=sample_users['salarie_id']
    completer(db,uid,7);completer(db,uid,8)
    for m in (7,8):signer_mois(acteurs[0],uid,m)
    anciennes={r['mois']:r['version_courante_id'] for r in db.execute('SELECT * FROM validations WHERE user_id=?',(uid,))}
    ajouter_absence(acteurs[2],uid,'2026-07-31','2026-08-03',motif='Arrêt maladie')
    for v in db.execute('SELECT * FROM validations WHERE user_id=?',(uid,)):
        assert v['version_courante_id']!=anciennes[v['mois']]
        assert v['version_salarie_id']!=v['version_courante_id']
    fermer(acteurs,uid,8)
    avant=etat(db)
    ajouter_absence(acteurs[2],uid,'2026-08-03','2026-08-04')
    assert etat(db)==avant
    aid=db.execute('SELECT id FROM absences').fetchone()[0]
    acteurs[2].post(f'/absences/supprimer/{aid}')
    assert etat(db)==avant


def test_b7_deux_creations_concurrentes(app,db,sample_users):
    clients=[app.test_client(),app.test_client()]
    for c in clients:_login(c,'admin','Admin1234')
    barriere=Barrier(2)
    def creer(c):
        barriere.wait(timeout=10)
        return ajouter_absence(c,sample_users['salarie_id']).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:assert list(pool.map(creer,clients))==[200,200]
    assert db.execute('SELECT COUNT(*) FROM absences').fetchone()[0]==1
    assert db.execute('SELECT cp_pris FROM users WHERE id=?',(sample_users['salarie_id'],)).fetchone()[0]==1


def test_b8_rollback_absence_ne_devalide_pas_paie(db,sample_users,sample_planning,sample_contrat,acteurs):
    uid=sample_users['salarie_id'];completer(db,uid,8);fermer(acteurs,uid,8)
    # Vérification réelle d'août via son formulaire, puis absence bloquée.
    import re
    html=acteurs[2].get('/prepa_paie?mois=8&annee=2026').get_data(as_text=True)
    ref=re.search(r'name="reference_'+str(uid)+r'" value="([^"]+)"',html).group(1)
    acteurs[2].post('/prepa_paie/traiter',data={'mois':8,'annee':2026,'user_ids':[uid],f'traite_{uid}':'1',f'reference_{uid}':ref})
    assert db.execute('SELECT traite FROM prepa_paie_statut WHERE user_id=?',(uid,)).fetchone()[0]==1
    avant=etat(db);ajouter_absence(acteurs[2],uid,'2026-08-03',motif='Arrêt maladie');assert etat(db)==avant
