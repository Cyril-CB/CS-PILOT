"""Migration 0068 : aucun historique reconstitué, installation et rollback."""
import importlib
import pytest

MIGRATION=importlib.import_module('migrations.0068_coherence_rh')


def retirer_schema_68(db):
    triggers=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND (name LIKE 'coherence_%' OR name LIKE 'paie_%')")]
    for nom in triggers:db.execute(f'DROP TRIGGER {nom}')
    for table in ('rh_projections','rh_projections_a_verifier','paie_a_recalculer'):db.execute(f'DROP TABLE {table}')
    for colonne in ('empreinte_verifiee','verifie_le','modifie_le','revision'):db.execute(f'ALTER TABLE prepa_paie_statut DROP COLUMN {colonne}')
    db.execute('ALTER TABLE absences DROP COLUMN demande_conge_id')
    db.commit()


def test_schema_neuf_et_idempotence(db):
    assert 'empreinte_verifiee' in {r[1] for r in db.execute('PRAGMA table_info(prepa_paie_statut)')}
    assert 'demande_conge_id' in {r[1] for r in db.execute('PRAGMA table_info(absences)')}
    for _ in range(2):MIGRATION.upgrade(db);db.commit()
    from database import ALL_MIGRATION_VERSIONS
    assert any(v[0]=='0068' for v in ALL_MIGRATION_VERSIONS)


def test_migration_preserve_historiques_et_ne_fabrique_pas_de_preuve(db,sample_users):
    uid=sample_users['salarie_id'];retirer_schema_68(db)
    for _ in range(2):db.execute("INSERT INTO absences(user_id,motif,date_debut,date_fin,jours_ouvres,saisi_par) VALUES (?,'Congé payé','2026-08-03','2026-08-03',1,?)",(uid,sample_users['directeur_id']))
    db.execute('UPDATE users SET cp_pris=2 WHERE id=?',(uid,))
    db.execute("INSERT INTO prepa_paie_statut(user_id,mois,annee,traite,updated_at) VALUES (?,8,2026,1,'2026-09-01 10:00:00')",(uid,))
    db.commit()
    avant={t:[tuple(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY rowid')] for t in ('users','validations','fiches_versions','fiches_evenements','heures_reelles')}
    MIGRATION.upgrade(db);db.commit()
    assert db.execute('SELECT COUNT(*) FROM absences').fetchone()[0]==2
    assert db.execute('SELECT COUNT(*) FROM rh_projections').fetchone()[0]==0
    assert {t:[tuple(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY rowid')] for t in avant}==avant
    row=dict(db.execute('SELECT * FROM prepa_paie_statut').fetchone())
    assert row['traite']==0 and row['empreinte_verifiee'] is None
    assert row['verifie_le']==row['updated_at']=='2026-09-01 10:00:00'
    assert row['modifie_le'] is None
    MIGRATION.upgrade(db);db.commit()
    assert dict(db.execute('SELECT * FROM prepa_paie_statut').fetchone())==row
    from absences_coherence import conflits_historiques
    assert len(conflits_historiques(db,uid))==1


def test_erreur_migration_annule_tout(db,monkeypatch):
    retirer_schema_68(db)
    def erreur(conn):raise RuntimeError('Panne synthétique')
    monkeypatch.setattr('prepa_paie_donnees.creer_schema',erreur)
    with pytest.raises(RuntimeError,match='Panne synthétique'):
        with db:MIGRATION.upgrade(db)
    assert 'demande_conge_id' not in {r[1] for r in db.execute('PRAGMA table_info(absences)')}
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='rh_projections'").fetchone()


def test_downgrade_explicite(db):
    with pytest.raises(RuntimeError,match='sauvegarde'):MIGRATION.downgrade(db)
