"""
Tests pour le module utils.py :
- calculer_heures : calcul de durée entre deux horaires
- calculer_jours_ouvres : calcul de jours ouvrés
- get_heures_theoriques_jour : extraction des heures depuis un planning
- login_required : protection des routes
- encrypt_value / decrypt_value : chiffrement/déchiffrement
- NOMS_MOIS : constante
"""
from datetime import datetime


class TestCalculerHeures:
    """Tests de la fonction calculer_heures."""

    def test_matin_standard(self, app):
        """08:30 à 12:00 = 3.5 heures."""
        with app.app_context():
            from utils import calculer_heures
            assert calculer_heures('08:30', '12:00') == 3.5

    def test_aprem_standard(self, app):
        """13:30 à 17:00 = 3.5 heures."""
        with app.app_context():
            from utils import calculer_heures
            assert calculer_heures('13:30', '17:00') == 3.5

    def test_horaire_vide(self, app):
        """Si début ou fin est None/vide, retourne 0."""
        with app.app_context():
            from utils import calculer_heures
            assert calculer_heures(None, '12:00') == 0
            assert calculer_heures('08:00', None) == 0
            assert calculer_heures('', '') == 0
            assert calculer_heures(None, None) == 0

    def test_meme_horaire(self, app):
        """Même heure de début et fin = 0."""
        with app.app_context():
            from utils import calculer_heures
            assert calculer_heures('09:00', '09:00') == 0

    def test_journee_complete(self, app):
        """08:00 à 18:00 = 10 heures."""
        with app.app_context():
            from utils import calculer_heures
            assert calculer_heures('08:00', '18:00') == 10.0

    def test_quart_heure(self, app):
        """09:00 à 09:15 = 0.25 heures."""
        with app.app_context():
            from utils import calculer_heures
            assert calculer_heures('09:00', '09:15') == 0.25


class TestCalculerJoursOuvres:
    """Tests de la fonction calculer_jours_ouvres."""

    def test_semaine_complete(self, app):
        """Du lundi au vendredi = 5 jours ouvrés."""
        with app.app_context():
            from utils import calculer_jours_ouvres
            # 2025-01-06 = lundi, 2025-01-10 = vendredi
            assert calculer_jours_ouvres('2025-01-06', '2025-01-10') == 5

    def test_inclut_pas_weekend(self, app):
        """Du lundi au dimanche = 5 jours ouvrés (exclut sam/dim)."""
        with app.app_context():
            from utils import calculer_jours_ouvres
            assert calculer_jours_ouvres('2025-01-06', '2025-01-12') == 5

    def test_deux_semaines(self, app):
        """Deux semaines complètes = 10 jours ouvrés."""
        with app.app_context():
            from utils import calculer_jours_ouvres
            assert calculer_jours_ouvres('2025-01-06', '2025-01-17') == 10

    def test_un_seul_jour_ouvre(self, app):
        """Un seul jour ouvré."""
        with app.app_context():
            from utils import calculer_jours_ouvres
            assert calculer_jours_ouvres('2025-01-06', '2025-01-06') == 1

    def test_date_fin_avant_debut(self, app):
        """Date fin avant date début = 0 jours."""
        with app.app_context():
            from utils import calculer_jours_ouvres
            assert calculer_jours_ouvres('2025-01-10', '2025-01-06') == 0

    def test_weekend_seul(self, app):
        """Samedi au dimanche = 0 jours ouvrés."""
        with app.app_context():
            from utils import calculer_jours_ouvres
            # 2025-01-11 = samedi, 2025-01-12 = dimanche
            assert calculer_jours_ouvres('2025-01-11', '2025-01-12') == 0


class TestGetHeuresTheoriquesJour:
    """Tests de la fonction get_heures_theoriques_jour."""

    def test_jour_avec_planning(self, app, sample_planning):
        """Avec un planning standard, chaque jour = 7h (3.5 matin + 3.5 aprem)."""
        with app.app_context():
            from utils import get_heures_theoriques_jour
            from database import get_db
            conn = get_db()
            planning = conn.execute(
                "SELECT * FROM planning_theorique WHERE id = ?",
                (sample_planning['planning_id'],)
            ).fetchone()
            conn.close()

            # Lundi (0) à Vendredi (4) : 7h chacun
            for jour in range(5):
                assert get_heures_theoriques_jour(planning, jour) == 7.0

    def test_jour_invalide(self, app):
        """Jour hors intervalle 0-4 retourne 0."""
        with app.app_context():
            from utils import get_heures_theoriques_jour
            assert get_heures_theoriques_jour(None, 0) == 0
            assert get_heures_theoriques_jour({}, -1) == 0
            assert get_heures_theoriques_jour({}, 5) == 0


class TestEncryption:
    """Tests du chiffrement/déchiffrement."""

    def test_encrypt_decrypt_roundtrip(self, app):
        """Chiffrer puis déchiffrer doit restituer la valeur originale."""
        with app.app_context():
            from utils import encrypt_value, decrypt_value
            original = 'ma-cle-api-secrete-12345'
            encrypted = encrypt_value(original)
            decrypted = decrypt_value(encrypted)
            assert decrypted == original
            assert encrypted != original  # Doit être différent du texte clair

    def test_encrypt_produit_valeurs_differentes(self, app):
        """Deux chiffrements de la même valeur produisent des résultats différents (Fernet)."""
        with app.app_context():
            from utils import encrypt_value
            val = 'test_value'
            enc1 = encrypt_value(val)
            enc2 = encrypt_value(val)
            # Fernet utilise un nonce, donc les chiffrés diffèrent
            assert enc1 != enc2


class TestNomsMois:
    """Test de la constante NOMS_MOIS."""

    def test_12_mois_plus_vide(self, app):
        with app.app_context():
            from utils import NOMS_MOIS
            assert len(NOMS_MOIS) == 13  # Index 0 vide + 12 mois
            assert NOMS_MOIS[0] == ''
            assert NOMS_MOIS[1] == 'Janvier'
            assert NOMS_MOIS[12] == 'Décembre'
