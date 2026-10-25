"""Serveur local éphémère : uniquement des comptes et données synthétiques.

Lancer depuis la racine : python tests/messages_direction_browser_server.py.
Aucune base existante ni configuration du centre n'est utilisée.
"""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='cspilot-direction-browser-') as dossier:
        os.environ['CSPILOT_DATA_DIR'] = dossier
        os.environ['SECRET_KEY'] = 'verification-locale-synthetique-uniquement'
        os.environ['APP_TIMEZONE'] = 'UTC'
        from database import init_db, get_db
        from app import app
        from werkzeug.security import generate_password_hash

        with app.app_context():
            init_db()
            conn = get_db()
            for profil in ('directeur', 'comptable', 'salarie', 'responsable', 'prestataire'):
                conn.execute('''
                    INSERT INTO users (nom, prenom, login, password, profil)
                    VALUES (?, 'Test', ?, ?, ?)
                ''', (profil.title(), profil,
                      generate_password_hash('Fictif-2026!'), profil))
            conn.execute("INSERT INTO cse_messages (titre,contenu,date_validite) VALUES ('CSE distinct','Message CSE synthétique','2999-12-31')")
            conn.commit()
            conn.close()
        # CSRF et contrôles de sécurité applicatifs restent activés.
        app.run(host='127.0.0.1', port=5056, use_reloader=False)
