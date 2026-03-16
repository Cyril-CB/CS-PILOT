"""
Fixtures pytest partagées pour tous les tests.

Architecture des fixtures :
- app            : Instance Flask configurée pour les tests (base SQLite en mémoire)
- db             : Connexion à la base de test, avec rollback automatique
- client         : Client HTTP Flask pour simuler des requêtes
- auth_client    : Client déjà authentifié en tant que salarié
- admin_client   : Client déjà authentifié en tant que directeur (admin)
- resp_client    : Client déjà authentifié en tant que responsable
- sample_users   : Jeu de données utilisateurs (salarié, responsable, directeur)
- sample_planning: Planning théorique pour les tests de calcul
"""
import os
import sys
import sqlite3
import tempfile

import pytest

# Ajouter le répertoire racine au path pour les imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Définir une SECRET_KEY pour les tests AVANT l'import de l'app
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')


@pytest.fixture(scope='function')
def app(tmp_path):
    """Crée une instance Flask avec une base SQLite temporaire par test."""
    # Créer un fichier temporaire pour la base de données
    db_path = str(tmp_path / 'test.db')

    # Patcher le chemin de la base AVANT d'importer l'app
    import database
    database.DATABASE = db_path

    from app import app as flask_app
    from extensions import limiter

    flask_app.config.update({
        'TESTING': True,
        'SECRET_KEY': 'test-secret-key-for-pytest',
        'WTF_CSRF_ENABLED': False,
        'RATELIMIT_ENABLED': False,
        'SERVER_NAME': 'localhost',
    })

    # Désactiver explicitement le rate limiter pour les tests
    limiter.enabled = False

    # Initialiser la base de données et appliquer toutes les migrations
    with flask_app.app_context():
        database.init_db()
        from migration_manager import appliquer_toutes_en_attente
        appliquer_toutes_en_attente(appliquee_par='pytest')

    yield flask_app

    # Nettoyage : supprimer la base temporaire
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def db(app):
    """Fournit une connexion à la base de test."""
    import database
    with app.app_context():
        conn = database.get_db()
        yield conn
        conn.close()


@pytest.fixture
def client(app):
    """Client HTTP Flask pour simuler des requêtes."""
    return app.test_client()


@pytest.fixture
def sample_users(app, db):
    """Crée un jeu de données utilisateurs pour les tests.

    Retourne un dict avec les IDs :
    - 'salarie_id'     : salarié de base
    - 'responsable_id' : responsable du même secteur
    - 'directeur_id'   : directeur (admin, créé par init_db)
    - 'comptable_id'   : comptable
    - 'secteur_id'     : ID du secteur de test
    """
    from werkzeug.security import generate_password_hash

    with app.app_context():
        cursor = db.cursor()

        # Créer un secteur
        cursor.execute(
            "INSERT INTO secteurs (nom, description) VALUES (?, ?)",
            ('Secteur Test', 'Secteur pour les tests automatisés')
        )
        secteur_id = cursor.lastrowid

        # Créer le compte directeur (plus de compte par défaut dans init_db)
        cursor.execute(
            "INSERT INTO users (nom, prenom, login, password, profil) VALUES (?, ?, ?, ?, ?)",
            ('Admin', 'Système', 'admin', generate_password_hash('Admin1234'), 'directeur')
        )
        directeur_id = cursor.lastrowid

        # Créer un responsable
        cursor.execute(
            "INSERT INTO users (nom, prenom, login, password, profil, secteur_id) VALUES (?, ?, ?, ?, ?, ?)",
            ('Dupont', 'Marie', 'resp_test', generate_password_hash('resp123'), 'responsable', secteur_id)
        )
        responsable_id = cursor.lastrowid

        # Créer un salarié
        cursor.execute(
            "INSERT INTO users (nom, prenom, login, password, profil, secteur_id, responsable_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ('Martin', 'Jean', 'salarie_test', generate_password_hash('sal123'), 'salarie', secteur_id, responsable_id)
        )
        salarie_id = cursor.lastrowid

        # Créer un comptable
        cursor.execute(
            "INSERT INTO users (nom, prenom, login, password, profil) VALUES (?, ?, ?, ?, ?)",
            ('Durand', 'Sophie', 'compta_test', generate_password_hash('compta123'), 'comptable')
        )
        comptable_id = cursor.lastrowid

        db.commit()

        return {
            'salarie_id': salarie_id,
            'responsable_id': responsable_id,
            'directeur_id': directeur_id,
            'comptable_id': comptable_id,
            'secteur_id': secteur_id,
        }


def _login(client, login, password):
    """Fonction utilitaire pour se connecter via le formulaire."""
    return client.post('/login', data={
        'login': login,
        'password': password,
    }, follow_redirects=True)


@pytest.fixture
def auth_client(client, sample_users):
    """Client authentifié en tant que salarié."""
    _login(client, 'salarie_test', 'sal123')
    return client


@pytest.fixture
def admin_client(client, sample_users):
    """Client authentifié en tant que directeur (admin)."""
    _login(client, 'admin', 'Admin1234')
    return client


@pytest.fixture
def resp_client(client, sample_users):
    """Client authentifié en tant que responsable."""
    _login(client, 'resp_test', 'resp123')
    return client


@pytest.fixture
def comptable_client(client, sample_users):
    """Client authentifie en tant que comptable."""
    _login(client, 'compta_test', 'compta123')
    return client


@pytest.fixture
def sample_planning(app, db, sample_users):
    """Crée un planning théorique standard (8h/jour, lun-ven) pour le salarié de test.

    Horaires : 08:30-12:00 / 13:30-17:00 = 7h/jour
    """
    with app.app_context():
        cursor = db.cursor()

        planning_data = {
            'user_id': sample_users['salarie_id'],
            'type_periode': 'periode_scolaire',
            'date_debut_validite': '2000-01-01',
            'type_alternance': 'fixe',
        }

        jours = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi']
        for jour in jours:
            planning_data[f'{jour}_matin_debut'] = '08:30'
            planning_data[f'{jour}_matin_fin'] = '12:00'
            planning_data[f'{jour}_aprem_debut'] = '13:30'
            planning_data[f'{jour}_aprem_fin'] = '17:00'

        planning_data['total_hebdo'] = 35.0

        columns = ', '.join(planning_data.keys())
        placeholders = ', '.join(['?'] * len(planning_data))
        cursor.execute(
            f"INSERT INTO planning_theorique ({columns}) VALUES ({placeholders})",
            list(planning_data.values())
        )
        planning_id = cursor.lastrowid
        db.commit()

        return {
            'planning_id': planning_id,
            **planning_data,
        }
