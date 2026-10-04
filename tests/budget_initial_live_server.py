"""Serveur de recette jetable : aucune base/configuration existante utilisée.

Lancé par budget_initial_live_checks.cjs, uniquement sur loopback.
CSRF, sessions et limitation de débit conservent leur configuration réelle.
"""
import os
from pathlib import Path
import sys
import tempfile
import signal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


if __name__ == '__main__':
    def terminer(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminer)
    with tempfile.TemporaryDirectory(prefix='budget-initial-live-') as directory:
        os.environ['CSPILOT_DATA_DIR'] = directory
        os.environ['SECRET_KEY'] = 'recette-synthetique-locale-uniquement'
        os.environ['APP_TIMEZONE'] = 'UTC'
        from database import init_db, get_db
        from app import app
        from werkzeug.security import generate_password_hash
        from werkzeug.serving import make_server

        init_db()
        conn = get_db()
        conn.execute("INSERT INTO secteurs (nom) VALUES ('Pilote synthétique')")
        conn.execute("INSERT INTO users (nom,prenom,login,password,profil,force_password_change) VALUES ('Recette','Direction','recette',?,'directeur',0)",
                     (generate_password_hash('Recette-locale-2026!'),))
        conn.execute("INSERT INTO budget_prev_saisies (type_budget,annee,secteur_id,compte_num,valeur_temp,valeur_def,commentaire) VALUES ('actualise',2026,1,'606100',55.55,55.55,'Actualisé synthétique préservé')")
        conn.commit()
        conn.close()
        with make_server('127.0.0.1', 0, app, threaded=True) as server:
            print('RECETTE_URL=http://127.0.0.1:' + str(server.server_port), flush=True)
            server.serve_forever()
