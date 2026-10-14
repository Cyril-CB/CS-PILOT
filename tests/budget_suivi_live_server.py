"""Recette lot 2 : données synthétiques dans un répertoire temporaire isolé."""
import os
from pathlib import Path
import signal
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with tempfile.TemporaryDirectory(prefix='budget-suivi-live-') as directory:
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
        conn.execute("INSERT INTO users (nom,prenom,login,password,profil,force_password_change) VALUES ('Recette','Direction','recette',?,'directeur',0)", (generate_password_hash('Recette-locale-2026!'),))
        conn.executemany('INSERT INTO plan_comptable_general (compte_num,libelle) VALUES (?,?)', [('606100','Énergie'),('706100','Produits')])
        for annee in (2027,2028):
            for code,value in [('606100',1200),('706100',2000)]:
                conn.execute("INSERT INTO budget_prev_saisies (type_budget,annee,secteur_id,compte_num,valeur_def) VALUES ('initial',?,1,?,?)",(annee,code,value))
        conn.commit()
        conn.close()
        with make_server('127.0.0.1',0,app,threaded=True) as server:
            print('RECETTE_URL=http://127.0.0.1:' + str(server.server_port),flush=True)
            server.serve_forever()
