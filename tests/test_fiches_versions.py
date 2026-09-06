"""Invariants métier des fiches : routes réelles et SQLite, sans mock des calculs."""
from datetime import date, timedelta

import pytest

from database import get_db


ANNEE, MOIS = 2026, 8


def client_role(app, users, role):
    client = app.test_client()
    from tests.conftest import _login
    conn = get_db()
    try:
        login = conn.execute('SELECT login FROM users WHERE id=?', (users[f'{role}_id'],)).fetchone()[0]
    finally:
        conn.close()
    passwords = {'admin': 'Admin1234', 'resp_test': 'resp123', 'salarie_test': 'sal123', 'compta_test': 'compta123'}
    _login(client, login, passwords[login])
    return client


def signer(client, user_id):
    from fiches_versions import empreinte
    from fiches_contenu import calculer_contenu
    conn = get_db()
    try:
        reference = empreinte(calculer_contenu(conn, user_id, MOIS, ANNEE))
    finally:
        conn.close()
    return client.post('/valider_mois', data={
        'user_id': user_id, 'mois': MOIS, 'annee': ANNEE, 'empreinte_fiche': reference,
    })


def validation(user_id):
    conn = get_db()
    try:
        row = conn.execute(
            'SELECT * FROM validations WHERE user_id=? AND annee=? AND mois=?',
            (user_id, ANNEE, MOIS),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


@pytest.fixture
def fiche_complete(app, db, sample_users, sample_contrat, sample_planning):
    user_id = sample_users['salarie_id']
    jour = date(ANNEE, MOIS, 1)
    while jour.month == MOIS:
        if jour.weekday() < 5:
            db.execute(
                """INSERT INTO heures_reelles
                   (user_id, date, declaration_conforme, type_saisie)
                   VALUES (?, ?, 1, 'normal')""",
                (user_id, jour.isoformat()),
            )
        jour += timedelta(days=1)
    db.commit()
    return user_id


def test_signature_ancienne_ne_verrouille_pas(app, sample_users, fiche_complete):
    responsable = client_role(app, sample_users, 'responsable')
    direction = client_role(app, sample_users, 'directeur')
    salarie = client_role(app, sample_users, 'salarie')
    signer(responsable, fiche_complete)
    salarie.post('/saisie_heures', data={
        'date': '2026-08-03', 'heure_debut_matin': '08:30',
        'heure_fin_matin': '12:00', 'heure_debut_aprem': '13:30',
        'heure_fin_aprem': '18:00', 'type_saisie': 'normal',
    })
    signer(direction, fiche_complete)
    assert not validation(fiche_complete)['bloque']
    signer(responsable, fiche_complete)
    assert validation(fiche_complete)['bloque']


def test_absence_ne_change_pas_une_fiche_verrouillee(app, sample_users, fiche_complete):
    signer(client_role(app, sample_users, 'responsable'), fiche_complete)
    direction = client_role(app, sample_users, 'directeur')
    signer(direction, fiche_complete)
    direction.post('/absences', data={
        'user_id': fiche_complete, 'motif': 'Arrêt maladie',
        'date_debut': '2026-08-03', 'date_fin': '2026-08-03',
        'date_reprise': '2026-08-04',
    })
    conn = get_db()
    try:
        assert conn.execute('SELECT COUNT(*) FROM absences').fetchone()[0] == 0
        assert conn.execute(
            "SELECT type_saisie FROM heures_reelles WHERE user_id=? AND date='2026-08-03'",
            (fiche_complete,),
        ).fetchone()[0] == 'normal'
    finally:
        conn.close()
    assert validation(fiche_complete)['bloque']


def test_post_fiche_incomplete_ne_cree_pas_de_signature(app, db, sample_users, fiche_complete):
    db.execute('DELETE FROM heures_reelles WHERE user_id=?', (fiche_complete,))
    db.commit()
    signer(client_role(app, sample_users, 'responsable'), fiche_complete)
    assert validation(fiche_complete) is None
    # La même fiche devient signable une fois les journées réellement saisies.
    from tests.test_validation import _creer_saisie_mois
    _creer_saisie_mois(db, fiche_complete, MOIS, ANNEE)
    signer(client_role(app, sample_users, 'responsable'), fiche_complete)
    v = validation(fiche_complete)
    assert v['version_responsable_id'] == v['version_courante_id']
    assert not v['bloque']


def verrouiller(app, users, user_id):
    signer(client_role(app, users, 'responsable'), user_id)
    signer(client_role(app, users, 'directeur'), user_id)
    assert validation(user_id)['bloque']


def etat_metier(user_id):
    """Inclut les effets indirects et le journal : un refus ne doit rien persister."""
    conn = get_db()
    tables = ('heures_reelles', 'absences', 'contrats', 'planning_theorique',
              'alternance_reference', 'jours_feries', 'periodes_vacances',
              'variables_paie', 'demandes_conges', 'demandes_recup',
              'validations', 'fiches_versions', 'fiches_evenements',
              'historique_modifications', 'users')
    try:
        return {table: [tuple(r) for r in conn.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                for table in tables}
    finally:
        conn.close()


@pytest.mark.parametrize('source', [
    'heures_modifier', 'heures_supprimer', 'planning_modifier', 'planning_supprimer',
    'contrat_modifier', 'contrat_supprimer', 'ferie', 'vacances',
    'solde_initial', 'hs_payees', 'heure_anterieure', 'absence_modifier',
])
def test_controle_central_annule_toute_la_transaction(
        app, db, sample_users, fiche_complete, source):
    from fiches_versions import FicheVerrouillee
    uid = fiche_complete
    if source == 'absence_modifier':
        db.execute("""INSERT INTO absences (user_id, motif, date_debut, date_fin, jours_ouvres, saisi_par)
                      VALUES (?, 'Arrêt maladie', '2026-08-03', '2026-08-03', 1, 1)""", (uid,))
        db.commit()
    verrouiller(app, sample_users, uid)
    avant = etat_metier(uid)
    conn = get_db()
    try:
        # Même une autre mutation déjà effectuée dans cette transaction est annulée.
        conn.execute("INSERT INTO demandes_conges (user_id,type_conge,date_debut,date_fin,nb_jours) "
                     "VALUES (?, 'Congé payé', '2026-09-07', '2026-09-07', 1)", (uid,))
        if source == 'heures_modifier':
            conn.cursor().execute("UPDATE heures_reelles SET commentaire='Correction' "
                                  "WHERE user_id=? AND date='2026-08-03'", (uid,))
        elif source == 'heures_supprimer':
            conn.executemany("DELETE FROM heures_reelles WHERE user_id=? AND date=?",
                             [(uid, '2026-08-03')])
        elif source == 'planning_modifier':
            conn.execute("UPDATE planning_theorique SET lundi_aprem_fin='18:00' WHERE user_id=?", (uid,))
        elif source == 'planning_supprimer':
            conn.execute('DELETE FROM planning_theorique WHERE user_id=?', (uid,))
        elif source == 'contrat_modifier':
            conn.execute("UPDATE contrats SET date_fin='2026-08-14' WHERE user_id=?", (uid,))
        elif source == 'contrat_supprimer':
            conn.execute('DELETE FROM contrats WHERE user_id=?', (uid,))
        elif source == 'ferie':
            conn.execute("INSERT INTO jours_feries (annee,date,libelle) VALUES (2026,'2026-08-03','Férié test')")
        elif source == 'vacances':
            conn.execute("INSERT INTO periodes_vacances (nom,date_debut,date_fin) "
                         "VALUES ('Période test','2026-08-03','2026-08-07')")
        elif source == 'solde_initial':
            conn.execute('UPDATE users SET solde_initial=4 WHERE id=?', (uid,))
        elif source == 'hs_payees':
            conn.execute("INSERT INTO variables_paie (user_id,annee,mois,heures_supps,hs_deduites_compteur) "
                         "VALUES (?,2026,8,2,1)", (uid,))
        elif source == 'heure_anterieure':
            conn.execute("INSERT INTO heures_reelles (user_id,date,heure_debut_matin,heure_fin_matin) "
                         "VALUES (?,'2026-07-30','08:00','12:00')", (uid,))
        else:
            conn.execute("UPDATE absences SET motif='Congé payé' WHERE user_id=?", (uid,))
        with pytest.raises(FicheVerrouillee, match='réouvrir'):
            conn.commit()
        assert not conn.in_transaction
    finally:
        conn.close()
    assert etat_metier(uid) == avant


@pytest.mark.parametrize('premier,second', [('responsable', 'directeur'), ('directeur', 'responsable')])
def test_ordre_libre_signatures_et_meme_seconde(app, db, monkeypatch, sample_users, fiche_complete, premier, second):
    from datetime import datetime
    import fiches_versions
    import blueprints.validation as routes
    instant = datetime(2026, 9, 1, 9, 0, 0)
    monkeypatch.setattr(fiches_versions, 'maintenant', lambda: instant)
    monkeypatch.setattr(routes, 'maintenant', lambda: instant)
    uid = fiche_complete
    signer(client_role(app, sample_users, premier), uid)
    v1 = validation(uid)['version_courante_id']
    db.execute("UPDATE heures_reelles SET commentaire='Correction dans la même seconde' "
               "WHERE user_id=? AND date='2026-08-03'", (uid,))
    db.commit()
    v2 = validation(uid)['version_courante_id']
    assert v2 != v1
    signer(client_role(app, sample_users, second), uid)
    v = validation(uid)
    assert not v['bloque']
    assert v[f'version_{premier}_id'] == v1
    assert v[f'version_{second}_id'] == v2
    signer(client_role(app, sample_users, premier), uid)
    v = validation(uid)
    assert v['bloque'] and v['version_directeur_id'] == v['version_responsable_id'] == v2
    assert v['date_directeur'] == v['date_responsable']


def test_formulaire_ancien_refuse_sans_mutation(app, db, sample_users, fiche_complete):
    from tests.conftest import _reference_fiche
    uid = fiche_complete
    responsable = client_role(app, sample_users, 'responsable')
    ref = _reference_fiche(responsable, uid, MOIS, ANNEE)
    db.execute("UPDATE heures_reelles SET commentaire='Changement pendant la lecture' WHERE user_id=?", (uid,))
    db.commit()
    avant = etat_metier(uid)
    response = responsable.post('/valider_mois', data={
        'user_id': uid, 'mois': MOIS, 'annee': ANNEE, 'empreinte_fiche': ref,
    }, follow_redirects=True)
    assert 'Relisez la fiche actualisée' in response.get_data(as_text=True)
    assert etat_metier(uid) == avant


def test_reference_manquante_refuse_meme_si_complet(app, sample_users, fiche_complete):
    responsable = client_role(app, sample_users, 'responsable')
    responsable.post('/valider_mois', data={'user_id': fiche_complete, 'mois': MOIS, 'annee': ANNEE})
    assert validation(fiche_complete) is None


@pytest.mark.parametrize('role', ['salarie', 'comptable', 'prestataire', 'responsable_tiers', 'anonyme'])
def test_signature_et_reouverture_respectent_les_droits(app, db, sample_users, fiche_complete, role):
    uid = fiche_complete
    client = app.test_client()
    if role != 'anonyme':
        from werkzeug.security import generate_password_hash
        from tests.conftest import _login
        profil = 'responsable' if role == 'responsable_tiers' else role
        db.execute("INSERT INTO users (nom, prenom, login, password, profil) VALUES ('Tiers', 'Test', 'tiers', ?, ?)",
                   (generate_password_hash('tiers123'), profil))
        db.commit()
        _login(client, 'tiers', 'tiers123')
    signer(client, uid)
    assert validation(uid) is None
    verrouiller(app, sample_users, uid)
    avant = etat_metier(uid)
    client.post('/deverrouiller_mois', data={'user_id': uid, 'mois': MOIS, 'annee': ANNEE, 'motif': 'Test'})
    assert etat_metier(uid) == avant


def test_reouverture_explicite_et_nouvelles_signatures(app, sample_users, fiche_complete):
    uid = fiche_complete
    verrouiller(app, sample_users, uid)
    ancienne = validation(uid)['version_courante_id']
    direction = client_role(app, sample_users, 'directeur')
    avant = etat_metier(uid)
    direction.post('/deverrouiller_mois', data={'user_id': uid, 'mois': MOIS, 'annee': ANNEE})
    assert etat_metier(uid) == avant
    direction.post('/deverrouiller_mois', data={
        'user_id': uid, 'mois': MOIS, 'annee': ANNEE, 'motif': 'Arrêt reçu après clôture',
    })
    assert validation(uid) is None
    direction.post('/absences', data={'user_id': uid, 'motif': 'Arrêt maladie',
                                     'date_debut': '2026-08-03', 'date_fin': '2026-08-03'})
    signer(direction, uid)
    assert not validation(uid)['bloque']
    signer(client_role(app, sample_users, 'responsable'), uid)
    v = validation(uid)
    assert v['bloque'] and v['version_courante_id'] != ancienne
    conn = get_db()
    try:
        events = [dict(r) for r in conn.execute('SELECT * FROM fiches_evenements WHERE user_id=? ORDER BY id', (uid,))]
        assert sum(e['evenement'] == 'verrouillage' for e in events) == 2
        ouverture = next(e for e in events if e['evenement'] == 'reouverture')
        assert 'Arrêt reçu après clôture' in ouverture['details']
        assert ouverture['auteur_id'] == sample_users['directeur_id']
        assert len([e for e in events if e['evenement'] == 'signature']) == 4
    finally:
        conn.close()


@pytest.mark.parametrize('type_demande', ['conge', 'journee', 'partielle'])
def test_demande_sur_mois_verrouille_reste_en_attente(app, db, sample_users, fiche_complete, type_demande):
    uid = fiche_complete
    if type_demande == 'conge':
        table, formulaire = 'demandes_conges', 'conge'
        cur = db.execute("INSERT INTO demandes_conges (user_id,type_conge,date_debut,date_fin,nb_jours) "
                         "VALUES (?,'Congé payé','2026-08-03','2026-08-03',1)", (uid,))
    else:
        table, formulaire = 'demandes_recup', 'recup'
        cur = db.execute("""INSERT INTO demandes_recup
                            (user_id,date_debut,date_fin,nb_jours,nb_heures,type_demande,heure_debut,heure_fin)
                            VALUES (?,'2026-08-03','2026-08-03',1,1,?,'10:00','11:00')""",
                         (uid, type_demande))
    demande_id = cur.lastrowid
    db.commit()
    verrouiller(app, sample_users, uid)
    avant = etat_metier(uid)
    direction = client_role(app, sample_users, 'directeur')
    response = direction.post('/validation_demandes_recup', data={
        'demande_id': demande_id, 'demande_type': formulaire, 'action': 'valider',
    }, follow_redirects=True)
    assert 'verrouill' in response.get_data(as_text=True).lower()
    assert etat_metier(uid) == avant
    assert db.execute(f'SELECT statut FROM {table} WHERE id=?', (demande_id,)).fetchone()[0] == 'en_attente_responsable'


def test_absence_multi_mois_et_conge_apres_signature(app, db, sample_users, fiche_complete):
    uid = fiche_complete
    responsable = client_role(app, sample_users, 'responsable')
    direction = client_role(app, sample_users, 'directeur')
    signer(responsable, uid)
    v1 = validation(uid)['version_courante_id']
    direction.post('/absences', data={'user_id': uid, 'motif': 'Arrêt maladie',
                                     'date_debut': '2026-07-31', 'date_fin': '2026-08-03'})
    assert validation(uid)['version_courante_id'] != v1
    html = responsable.get(f'/vue_mensuelle?user_id={uid}&mois=8&annee=2026').get_data(as_text=True)
    assert 'une nouvelle signature est nécessaire' in html
    signer(responsable, uid)
    v2 = validation(uid)['version_courante_id']
    cur = db.execute("INSERT INTO demandes_conges (user_id,type_conge,date_debut,date_fin,nb_jours) "
                     "VALUES (?,'Congé payé','2026-08-04','2026-08-04',1)", (uid,))
    demande_id = cur.lastrowid
    db.commit()
    direction.post('/validation_demandes_recup', data={'demande_id': demande_id,
                   'demande_type': 'conge', 'action': 'valider'})
    assert validation(uid)['version_courante_id'] != v2
    signer(direction, uid)
    assert not validation(uid)['bloque']


def test_planning_futur_et_modification_sans_effet_autorises(app, db, sample_users, fiche_complete):
    uid = fiche_complete
    verrouiller(app, sample_users, uid)
    v = validation(uid)
    # Modifier une colonne sans effet sur la fiche ne doit pas imposer sa réouverture.
    db.execute("UPDATE users SET email='fictif@example.invalid' WHERE id=?", (uid,))
    db.execute("""INSERT INTO planning_theorique (user_id,type_periode,date_debut_validite,type_alternance,
                  lundi_matin_debut,lundi_matin_fin) VALUES (?,'periode_scolaire','2027-01-01','fixe','09:00','12:00')""", (uid,))
    db.commit()
    assert validation(uid) == v


def test_sql_commit_direct_et_context_manager_ne_contournent_pas_le_controle(app, sample_users, fiche_complete):
    import sqlite3
    from fiches_versions import FicheVerrouillee
    uid = fiche_complete
    verrouiller(app, sample_users, uid)
    avant = etat_metier(uid)
    conn = get_db()
    try:
        conn.execute("UPDATE heures_reelles SET commentaire='Tentative' WHERE user_id=?", (uid,))
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute('COMMIT')
        with pytest.raises(FicheVerrouillee):
            conn.commit()
        with pytest.raises(FicheVerrouillee):
            with conn:
                conn.execute("UPDATE heures_reelles SET commentaire='Tentative 2' WHERE user_id=?", (uid,))
    finally:
        conn.close()
    assert etat_metier(uid) == avant

@pytest.mark.parametrize('exception', ['repos', 'ferie', 'debut_contrat', 'fin_contrat', 'trou_contrats'])
def test_completude_backend_conserve_les_jours_non_dus(app, db, sample_users, fiche_complete, exception):
    uid = fiche_complete
    db.execute("DELETE FROM heures_reelles WHERE user_id=? AND date='2026-08-03'", (uid,))
    if exception == 'repos':
        db.execute("UPDATE planning_theorique SET lundi_matin_debut=NULL,lundi_matin_fin=NULL,"
                   "lundi_aprem_debut=NULL,lundi_aprem_fin=NULL WHERE user_id=?", (uid,))
    elif exception == 'ferie':
        db.execute("INSERT INTO jours_feries (annee,date,libelle) VALUES (2026,'2026-08-03','Test')")
    elif exception == 'debut_contrat':
        db.execute("UPDATE contrats SET date_debut='2026-08-04' WHERE user_id=?", (uid,))
    elif exception == 'fin_contrat':
        db.execute("UPDATE contrats SET date_fin='2026-08-02' WHERE user_id=?", (uid,))
    else:
        db.execute("UPDATE contrats SET date_fin='2026-07-31' WHERE user_id=?", (uid,))
        db.execute("INSERT INTO contrats (user_id,type_contrat,date_debut) VALUES (?,'CDD','2026-08-04')", (uid,))
    db.commit()
    signer(client_role(app, sample_users, 'responsable'), uid)
    assert validation(uid)['version_responsable_id']


@pytest.mark.parametrize('chemin', ['planning_ajout', 'planning_suppression', 'absence_suppression',
                                    'contrat_fin', 'contrat_suppression', 'heures'])
def test_routes_indirectes_preservent_fiche_et_pieces(
        app, db, tmp_path, sample_users, fiche_complete, chemin, monkeypatch):
    from io import BytesIO
    import blueprints.absences as absences
    uid = fiche_complete
    direction = client_role(app, sample_users, 'directeur')
    salarie = client_role(app, sample_users, 'salarie')
    monkeypatch.setattr(absences, 'DOCUMENTS_DIR', str(tmp_path))
    if chemin == 'absence_suppression':
        direction.post('/absences', data={'user_id': uid, 'motif': 'Arrêt maladie',
                       'date_debut': '2026-08-03', 'date_fin': '2026-08-03',
                       'justificatif': (BytesIO(b'%PDF-fictif'), 'justificatif.pdf')})
        absence = db.execute('SELECT * FROM absences WHERE user_id=?', (uid,)).fetchone()
        assert absence is not None
    verrouiller(app, sample_users, uid)
    avant = etat_metier(uid)
    fichiers_avant = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file() and p.suffix == '.pdf'}
    if chemin == 'planning_ajout':
        data = {'type_periode': 'periode_scolaire', 'date_debut_validite': '2026-08-01', 'type_alternance': 'fixe'}
        for jour in ('lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi'):
            data.update({f'{jour}_matin_debut': '08:00', f'{jour}_matin_fin': '12:00',
                         f'{jour}_aprem_debut': '13:00', f'{jour}_aprem_fin': '17:00'})
        response = salarie.post('/planning_theorique', data=data, follow_redirects=True)
    elif chemin == 'planning_suppression':
        pid = db.execute('SELECT id FROM planning_theorique WHERE user_id=?', (uid,)).fetchone()[0]
        response = salarie.post(f'/planning_theorique/supprimer/{pid}', follow_redirects=True)
    elif chemin == 'absence_suppression':
        response = direction.post(f'/absences/supprimer/{absence["id"]}', follow_redirects=True)
    elif chemin == 'contrat_fin':
        cid = db.execute('SELECT id FROM contrats WHERE user_id=?', (uid,)).fetchone()[0]
        response = direction.post(f'/infos_salaries/contrat/{cid}/date_fin',
                                  data={'date_fin': '2026-08-14'}, follow_redirects=True)
    elif chemin == 'contrat_suppression':
        cid = db.execute('SELECT id FROM contrats WHERE user_id=?', (uid,)).fetchone()[0]
        response = direction.post(f'/infos_salaries/supprimer_contrat/{cid}', follow_redirects=True)
    else:
        response = salarie.post('/saisie_heures', data={'date': '2026-08-03',
                                'type_saisie': 'normal', 'heure_debut_matin': '09:00',
                                'heure_fin_matin': '12:00'}, follow_redirects=True)
    assert response.status_code == 200
    assert 'verrouill' in response.get_data(as_text=True).lower()
    assert etat_metier(uid) == avant
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file() and p.suffix == '.pdf'} == fichiers_avant


def test_migration_historique_idempotente(app, db, sample_users, fiche_complete, monkeypatch):
    """Ancien schéma réel, signatures préservées, aucune précision inventée."""
    import importlib
    import sqlite3
    import database
    uid = fiche_complete
    db.close()
    old = sqlite3.connect(database.DATABASE)
    old.row_factory = sqlite3.Row
    try:
        for row in old.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'fiche_source_%'").fetchall():
            old.execute(f'DROP TRIGGER "{row[0]}"')
        for col in ('version_courante_id', 'version_salarie_id', 'version_responsable_id', 'version_directeur_id'):
            old.execute(f'ALTER TABLE validations DROP COLUMN {col}')
        for table in ('fiches_versions', 'fiches_evenements', 'fiches_a_recalculer'):
            old.execute(f'DROP TABLE {table}')
        old.execute("DELETE FROM schema_migrations WHERE version='0065'")
        old.execute("INSERT INTO validations (user_id,annee,mois,validation_responsable,date_responsable,bloque) "
                    "VALUES (?,2026,8,'Ancienne responsable','2026-09-01 08:00:00',0)", (uid,))
        old.execute("INSERT INTO validations (user_id,annee,mois,validation_responsable,validation_directeur,bloque) "
                    "VALUES (?,2026,7,'Ancienne responsable','Ancienne direction',1)", (uid,))
        old.commit()
        anciennes_heures = [tuple(r) for r in old.execute('SELECT * FROM heures_reelles ORDER BY id')]
        upgrade = importlib.import_module('migrations.0065_versions_fiches_mensuelles').upgrade
        # Une reprise interrompue annule aussi le DDL, avant une relance réussie.
        import fiches_versions
        with monkeypatch.context() as patch:
            def interrompre(conn):
                raise RuntimeError('Interruption simulée')
            patch.setattr(fiches_versions, 'actualiser_versions', interrompre)
            with pytest.raises(RuntimeError, match='Interruption simulée'):
                upgrade(old)
            old.rollback()
        assert not old.execute("SELECT 1 FROM sqlite_master WHERE name='fiches_versions'").fetchone()
        assert 'version_courante_id' not in {r[1] for r in old.execute('PRAGMA table_info(validations)')}
        upgrade(old)
        old.commit()
        premieres_versions = [tuple(r) for r in old.execute('SELECT * FROM fiches_versions ORDER BY id')]
        premiers_evenements = [tuple(r) for r in old.execute('SELECT * FROM fiches_evenements ORDER BY id')]
        upgrade(old)
        old.commit()
        assert [tuple(r) for r in old.execute('SELECT * FROM fiches_versions ORDER BY id')] == premieres_versions
        assert [tuple(r) for r in old.execute('SELECT * FROM fiches_evenements ORDER BY id')] == premiers_evenements
        assert [tuple(r) for r in old.execute('SELECT * FROM heures_reelles ORDER BY id')] == anciennes_heures
        ouverte = old.execute('SELECT * FROM validations WHERE user_id=? AND mois=8', (uid,)).fetchone()
        fermee = old.execute('SELECT * FROM validations WHERE user_id=? AND mois=7', (uid,)).fetchone()
        assert ouverte['validation_responsable'] == 'Ancienne responsable'
        assert ouverte['version_responsable_id'] is None
        assert fermee['bloque'] and fermee['validation_directeur'] == 'Ancienne direction'
        assert fermee['version_courante_id'] and fermee['version_directeur_id'] is None
    finally:
        old.close()
    signer(client_role(app, sample_users, 'directeur'), uid)
    assert not validation(uid)['bloque']
    signer(client_role(app, sample_users, 'responsable'), uid)
    assert validation(uid)['bloque']


def test_signature_concurrente_et_modification_ont_un_ordre_atomique(app, sample_users, fiche_complete, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import blueprints.validation as routes
    from fiches_versions import FicheVerrouillee
    uid = fiche_complete
    signer(client_role(app, sample_users, 'responsable'), uid)
    verifiee, modification_commencee, continuer = Event(), Event(), Event()
    original = routes.enregistrer_version

    def signature_en_cours(*args, **kwargs):
        verifiee.set()
        assert continuer.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(routes, 'enregistrer_version', signature_en_cours)

    def modifier():
        conn = get_db()
        try:
            modification_commencee.set()
            conn.execute("UPDATE heures_reelles SET commentaire='Concurrence' WHERE user_id=?", (uid,))
            conn.commit()
            return 'modifie'
        except FicheVerrouillee:
            return 'refuse'
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        signature = pool.submit(signer, client_role(app, sample_users, 'directeur'), uid)
        assert verifiee.wait(5)
        modification = pool.submit(modifier)
        assert modification_commencee.wait(5)
        continuer.set()
        assert signature.result(timeout=8).status_code == 302
        assert modification.result(timeout=8) == 'refuse'
    v = validation(uid)
    assert v['bloque'] and v['version_directeur_id'] == v['version_responsable_id']


def test_modification_concurrente_rend_la_page_de_signature_perimee(app, sample_users, fiche_complete):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from tests.conftest import _reference_fiche
    uid = fiche_complete
    signer(client_role(app, sample_users, 'responsable'), uid)
    direction = client_role(app, sample_users, 'directeur')
    reference = _reference_fiche(direction, uid, MOIS, ANNEE)
    conn = get_db()
    demarree = Event()
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("UPDATE heures_reelles SET commentaire='Avant signature concurrente' WHERE user_id=?", (uid,))
        def signer_page():
            demarree.set()
            return direction.post('/valider_mois', data={
                'user_id': uid, 'mois': MOIS, 'annee': ANNEE, 'empreinte_fiche': reference,
            })
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(signer_page)
            assert demarree.wait(5)
            conn.commit()
            assert future.result(timeout=8).status_code == 302
    finally:
        conn.close()
    v = validation(uid)
    assert not v['bloque'] and v['version_directeur_id'] is None
    assert v['version_responsable_id'] != v['version_courante_id']


def test_pdf_reproduit_les_totaux_figes(app, sample_users, fiche_complete):
    from io import BytesIO
    import pdfplumber
    uid = fiche_complete
    verrouiller(app, sample_users, uid)
    client = client_role(app, sample_users, 'directeur')
    response = client.get(f'/export_pdf_mensuel?user_id={uid}&annee={ANNEE}&mois={MOIS}')
    assert response.status_code == 200 and response.mimetype == 'application/pdf'
    with pdfplumber.open(BytesIO(response.data)) as pdf:
        texte = '\n'.join(page.extract_text() for page in pdf.pages)
    assert '147.00' in texte or '147,00' in texte


def test_directeur_responsable_signe_la_nouvelle_version_dans_les_deux_roles(
        app, db, sample_users, fiche_complete):
    uid = fiche_complete
    signer(client_role(app, sample_users, 'responsable'), uid)
    precedente = validation(uid)['version_courante_id']
    db.execute("UPDATE heures_reelles SET commentaire='Correction avant double signature' WHERE user_id=?", (uid,))
    db.execute('UPDATE users SET responsable_id=? WHERE id=?', (sample_users['directeur_id'], uid))
    db.commit()
    signer(client_role(app, sample_users, 'directeur'), uid)
    v = validation(uid)
    assert v['bloque'] and v['version_courante_id'] != precedente
    assert v['version_directeur_id'] == v['version_responsable_id'] == v['version_courante_id']


def test_fiche_personnelle_responsable_et_signature_salarie_obsolete_dans_pdf(
        app, db, sample_users, fiche_complete):
    from io import BytesIO
    import pdfplumber
    from fiches_versions import presenter_validation
    uid = fiche_complete
    db.execute("UPDATE users SET profil='responsable' WHERE id=?", (uid,))
    db.commit()
    propre_client = client_role(app, {**sample_users, 'responsable_id': uid}, 'responsable')
    signer(propre_client, uid)
    ancienne = validation(uid)['version_salarie_id']
    db.execute("UPDATE validations SET date_salarie='2001-02-03 04:05:06' WHERE user_id=?", (uid,))
    db.execute("UPDATE heures_reelles SET commentaire='Correction personnelle' WHERE user_id=?", (uid,))
    db.commit()
    direction = client_role(app, sample_users, 'directeur')
    signer(direction, uid)
    v = validation(uid)
    assert v['bloque'] and v['version_directeur_id'] == v['version_courante_id']
    assert v['version_responsable_id'] is None
    assert v['version_salarie_id'] == ancienne != v['version_courante_id']
    presentee = presenter_validation(v)
    assert not presentee['historique_non_versionne']
    assert presentee['validation_salarie'] is None and presentee['date_salarie'] is None
    response = direction.get(f'/export_pdf_mensuel?user_id={uid}&annee={ANNEE}&mois={MOIS}')
    assert response.status_code == 200
    with pdfplumber.open(BytesIO(response.data)) as pdf:
        texte = '\n'.join(page.extract_text() for page in pdf.pages)
    assert '2001-02-03' not in texte


def test_revocation_compte_avec_fiche_verrouillee(app, db, sample_users, fiche_complete):
    """Le verrou métier ne doit pas empêcher une révocation de sécurité."""
    from tests.conftest import _login
    uid = fiche_complete
    verrouiller(app, sample_users, uid)
    avant = etat_metier(uid)
    avant.pop('users')
    compte_avant = dict(db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())
    sal = app.test_client()
    _login(sal, 'salarie_test', 'sal123')
    direction = client_role(app, sample_users, 'directeur')
    direction.post(f'/toggle_user/{uid}')
    assert db.execute('SELECT actif FROM users WHERE id=?', (uid,)).fetchone()[0] == 0
    assert sal.get('/vue_mensuelle').headers['Location'] == '/login'
    apres = etat_metier(uid)
    apres.pop('users')
    assert apres == avant
    compte_apres = dict(db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())
    assert compte_apres == {**compte_avant, 'actif': 0, 'session_version': compte_avant['session_version'] + 1}
