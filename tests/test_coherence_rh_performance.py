"""Mesure synthétique et vérification du périmètre des recalculs."""
from time import perf_counter
from prepa_paie_donnees import donnees_salarie,empreinte
from tests.test_coherence_rh import ajouter_absence


def test_recalcul_limite_au_salarie_concerne(admin_client,db,sample_users,monkeypatch):
    uid=sample_users['salarie_id']
    ids=[uid]
    for n in range(50):
        ids.append(db.execute("INSERT INTO users(nom,prenom,login,password,profil) VALUES (?,'Test',?,'hash-fictif-non-utilisable','salarie')",(f'Fictif {n}',f'fictif-perf-{n}')).lastrowid)
    db.commit()
    for cible in ids:
        for annee in (2025,2026):
            for mois in range(1,13):
                h=empreinte(donnees_salarie(db,cible,mois,annee))
                db.execute('''INSERT INTO prepa_paie_statut(user_id,mois,annee,traite,empreinte_verifiee,verifie_le)
                    VALUES (?,?,?,1,?,CURRENT_TIMESTAMP)''',(cible,mois,annee,h))
    db.commit()
    visites=[]
    def lire(conn,cible,mois,annee):
        visites.append((cible,mois,annee))
        return donnees_salarie(conn,cible,mois,annee)
    monkeypatch.setattr('prepa_paie_donnees.donnees_salarie',lire)
    debut=perf_counter()
    ajouter_absence(admin_client,uid,motif='Arrêt maladie')
    duree=perf_counter()-debut
    assert len(visites)==1 and {v[0] for v in visites}=={uid}
    assert db.execute('SELECT COUNT(*) FROM prepa_paie_statut WHERE traite=0').fetchone()[0]==1
    print(f'PERFORMANCE : 1224 dossiers, 1 empreinte du seul salarié/mois concerné, HTTP et commit {duree:.3f}s')
