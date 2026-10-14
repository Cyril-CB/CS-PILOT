"""Recette locale isolée : comptes synthétiques, aucun SMTP ou service externe."""
import os
from pathlib import Path
import signal
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


if __name__ == '__main__':
    def terminer(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminer)
    with tempfile.TemporaryDirectory(prefix='approvisionnement-live-') as directory:
        os.environ['CSPILOT_DATA_DIR'] = directory
        os.environ['SECRET_KEY'] = 'cle-synthetique-recette-approvisionnement'
        os.environ['APP_TIMEZONE'] = 'UTC'
        from database import init_db, get_db
        from app import app
        from entretien import initialiser_catalogue
        from werkzeug.security import generate_password_hash
        from werkzeug.serving import make_server

        init_db()
        conn = get_db()
        conn.execute("INSERT INTO secteurs(nom) VALUES ('Secteur synthétique')")
        for login, profil in [('direction', 'directeur'), ('demandeur', 'responsable'),
                              ('angle9', 'salarie'), ('four1', 'salarie'), ('four2', 'salarie'),
                              ('ent1', 'salarie'), ('ent2', 'salarie')]:
            conn.execute('INSERT INTO users(nom,prenom,login,password,profil,secteur_id) VALUES (?, ?, ?, ?, ?, 1)',
                         ('Recette', login, login, generate_password_hash('Recette-locale-2026!'), profil))
        conn.executemany('INSERT INTO sites(nom) VALUES (?)', [('Cyprian',), ('Les Brosses',)])
        conn.executemany('INSERT INTO sites_utilisateurs(site_id,user_id) VALUES (?, ?)', [(1, 2), (2, 3)])
        conn.executemany('INSERT INTO sites_responsables_modules(site_id,module,user_id) VALUES (?, ?, ?)',
                         [(1, 'fournitures', 4), (2, 'fournitures', 5), (1, 'entretien', 6), (2, 'entretien', 7)])
        conn.executemany('INSERT INTO entretien_lieux(site_id,nom,demandeur_id) VALUES (?, ?, ?)',
                         [(1, 'Gribouille', 2), (1, 'Angle 9', 3)])
        initialiser_catalogue(conn, 1)
        initialiser_catalogue(conn, 2)
        conn.executemany('INSERT INTO commandes_salaries(user_id,date_demande,description,site_id) VALUES (?, ?, ?, ?)',
                         [(2, '2026-10-14', 'Papier Cyprian synthétique', 1),
                          (3, '2026-10-14', 'Classeurs Brosses synthétiques', 2),
                          (2, '2026-10-13', 'Ancienne demande globale', None)])
        conn.commit()
        conn.close()
        with make_server('127.0.0.1', 0, app, threaded=True) as server:
            print('RECETTE_URL=http://127.0.0.1:' + str(server.server_port), flush=True)
            server.serve_forever()
