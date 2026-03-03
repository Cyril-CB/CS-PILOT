"""
Fixtures pytest partagées pour tous les tests.

Architecture des fixtures :
- app            : Instance Flask configurée pour les tests (base PostgreSQL de test)
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

import pytest

# Ajouter le répertoire racine au path pour les imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Définir une SECRET_KEY pour les tests AVANT l'import de l'app
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')

# URL de base de données pour les tests
_TEST_DB_URL = os.environ.get(
    'TEST_DATABASE_URL',
    os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/cspilot_test')
)


def _pg_available():
    """Vérifie si PostgreSQL est disponible."""
    try:
        import psycopg2
        conn = psycopg2.connect(_TEST_DB_URL, connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


requires_pg = pytest.mark.skipif(
    not _pg_available(),
    reason="PostgreSQL non disponible - définir TEST_DATABASE_URL"
)


@pytest.fixture(scope='function')
def app():
    """Crée une instance Flask pointant sur la base PostgreSQL de test."""
    if not _pg_available():
        pytest.skip("PostgreSQL non disponible")

    os.environ['DATABASE_URL'] = _TEST_DB_URL

    from app import app as flask_app
    from extensions import limiter

    flask_app.config.update({
        'TESTING': True,
        'SECRET_KEY': 'test-secret-key-for-pytest',
        'WTF_CSRF_ENABLED': False,
        'RATELIMIT_ENABLED': False,
        'SERVER_NAME': 'localhost',
        'SQLALCHEMY_DATABASE_URI': _TEST_DB_URL,
    })

    limiter.enabled = False

    with flask_app.app_context():
        import database
        database.init_db()
        from migration_manager import appliquer_toutes_en_attente
        appliquer_toutes_en_attente(appliquee_par='pytest')

    yield flask_app


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
    - 'secteur_id'     : ID du secteur de test
    """
    from werkzeug.security import generate_password_hash

    with app.app_context():
        cursor = db.cursor()

        # Créer un secteur
        cursor.execute(
            "INSERT INTO secteurs (nom, description) VALUES (%s, %s) RETURNING id",
            ('Secteur Test', 'Secteur pour les tests automatisés')
        )
        secteur_id = cursor.lastrowid

        # Créer le compte directeur
        cursor.execute(
            "INSERT INTO users (nom, prenom, login, password, profil) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            ('Admin', 'Système', 'admin', generate_password_hash('Admin1234'), 'directeur')
        )
        directeur_id = cursor.lastrowid

        # Créer un responsable
        cursor.execute(
            "INSERT INTO users (nom, prenom, login, password, profil, secteur_id) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            ('Dupont', 'Marie', 'resp_test', generate_password_hash('resp123'), 'responsable', secteur_id)
        )
        responsable_id = cursor.lastrowid

        # Créer un salarié
        cursor.execute(
            "INSERT INTO users (nom, prenom, login, password, profil, secteur_id, responsable_id) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            ('Martin', 'Jean', 'salarie_test', generate_password_hash('sal123'), 'salarie', secteur_id, responsable_id)
        )
        salarie_id = cursor.lastrowid

        db.commit()

        return {
            'salarie_id': salarie_id,
            'responsable_id': responsable_id,
            'directeur_id': directeur_id,
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
        placeholders = ', '.join(['%s'] * len(planning_data))
        cursor.execute(
            f"INSERT INTO planning_theorique ({columns}) VALUES ({placeholders}) RETURNING id",
            list(planning_data.values())
        )
        planning_id = cursor.lastrowid
        db.commit()

        return {
            'planning_id': planning_id,
            **planning_data,
        }
