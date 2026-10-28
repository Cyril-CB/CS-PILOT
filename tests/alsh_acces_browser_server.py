"""Serveur éphémère ALSH : comptes fictifs, aucune donnée/configuration réelle."""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='cspilot-alsh-acces-browser-') as dossier:
        os.environ['CSPILOT_DATA_DIR'] = dossier
        os.environ['SECRET_KEY'] = 'verification-locale-alsh-uniquement'
        os.environ['APP_TIMEZONE'] = 'Europe/Paris'
        from database import init_db, get_db
        from app import app
        from werkzeug.security import generate_password_hash

        with app.app_context():
            init_db()
            conn = get_db()
            enfance = conn.execute("INSERT INTO secteurs(nom,type_secteur) VALUES('Enfance','accueil_loisirs')").lastrowid
            famille = conn.execute("INSERT INTO secteurs(nom,type_secteur) VALUES('Famille','famille')").lastrowid
            for login, profil, secteur in [
                ('directeur', 'directeur', None), ('comptable', 'comptable', None),
                ('resp_enfance', 'responsable', enfance), ('resp_famille', 'responsable', famille),
                ('salarie', 'salarie', enfance), ('prestataire', 'prestataire', enfance),
            ]:
                conn.execute('''INSERT INTO users(nom,prenom,login,password,profil,secteur_id)
                                VALUES(?, 'Test', ?, ?, ?, ?)''',
                             (login, login, generate_password_hash('Fictif-ALSH-2026!'), profil, secteur))
            tranche = conn.execute('SELECT id FROM alsh_tranches_age WHERE active=1 ORDER BY ordre,id').fetchone()[0]
            periode = conn.execute("SELECT id FROM alsh_periodes WHERE active=1 AND type='mercredi' ORDER BY ordre,id").fetchone()[0]
            conn.execute('INSERT INTO alsh_config_codes(annee,periode_id,tranche_age_id,code1) VALUES(2026,?,?,?)',
                         (periode, tranche, 'ALSH-FICTIF'))
            conn.execute('''INSERT INTO alsh_saisie_noe(annee,periode_id,tranche_age_id,heures_presence,nb_enfants)
                            VALUES(2026,?,?,120,12)''', (periode, tranche))
            conn.executemany('''INSERT INTO bilan_fec_donnees(compte_num,libelle,code_analytique,annee,mois,montant)
                                VALUES(?,?,?,2026,1,?)''', [
                ('601000', 'Charges ALSH fictives', 'ALSH-FICTIF', 240),
                ('741100', 'Subvention fictive', 'ALSH-FICTIF', 60),
                ('601000', 'Autres charges fictives', 'FAMILLE-FICTIF', 999),
            ])
            conn.commit()
            conn.close()
        app.run(host='127.0.0.1', port=5057, use_reloader=False)
