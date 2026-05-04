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

    def test_exclut_jour_ferie(self, app, db):
        """Exclut un jour férié de la semaine."""
        with app.app_context():
            from utils import calculer_jours_ouvres
            # Ajouter un jour férié le mercredi 2025-01-08
            db.execute('''
                INSERT INTO jours_feries (annee, date, libelle)
                VALUES (2025, '2025-01-08', 'Jour férié test')
            ''')
            db.commit()

            # Du lundi 2025-01-06 au vendredi 2025-01-10 = 5 jours - 1 férié = 4 jours
            assert calculer_jours_ouvres('2025-01-06', '2025-01-10') == 4

    def test_exclut_plusieurs_jours_feries(self, app, db):
        """Exclut plusieurs jours fériés."""
        with app.app_context():
            from utils import calculer_jours_ouvres
            # Ajouter deux jours fériés
            db.execute('''
                INSERT INTO jours_feries (annee, date, libelle)
                VALUES (2025, '2025-01-07', 'Férié 1'), (2025, '2025-01-09', 'Férié 2')
            ''')
            db.commit()

            # Du lundi 2025-01-06 au vendredi 2025-01-10 = 5 jours - 2 fériés = 3 jours
            assert calculer_jours_ouvres('2025-01-06', '2025-01-10') == 3

    def test_ferie_weekend_non_compte(self, app, db):
        """Un jour férié tombant un weekend ne change pas le décompte."""
        with app.app_context():
            from utils import calculer_jours_ouvres
            # Ajouter un jour férié le samedi 2025-01-11
            db.execute('''
                INSERT INTO jours_feries (annee, date, libelle)
                VALUES (2025, '2025-01-11', 'Férié weekend')
            ''')
            db.commit()

            # Du lundi 2025-01-06 au dimanche 2025-01-12 = 5 jours (le férié du samedi ne change rien)
            assert calculer_jours_ouvres('2025-01-06', '2025-01-12') == 5

    def test_semaine_avec_ferie_debut(self, app, db):
        """Un jour férié en début de période."""
        with app.app_context():
            from utils import calculer_jours_ouvres
            # Jour férié le lundi 2025-01-06
            db.execute('''
                INSERT INTO jours_feries (annee, date, libelle)
                VALUES (2025, '2025-01-06', 'Férié début')
            ''')
            db.commit()

            # Du lundi 2025-01-06 (férié) au vendredi 2025-01-10 = 4 jours
            assert calculer_jours_ouvres('2025-01-06', '2025-01-10') == 4

    def test_semaine_avec_ferie_fin(self, app, db):
        """Un jour férié en fin de période."""
        with app.app_context():
            from utils import calculer_jours_ouvres
            # Jour férié le vendredi 2025-01-10
            db.execute('''
                INSERT INTO jours_feries (annee, date, libelle)
                VALUES (2025, '2025-01-10', 'Férié fin')
            ''')
            db.commit()

            # Du lundi 2025-01-06 au vendredi 2025-01-10 (férié) = 4 jours
            assert calculer_jours_ouvres('2025-01-06', '2025-01-10') == 4


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


class TestGetPlanningValideADate:
    """Tests de fallback du planning théorique."""

    def test_vacances_utilise_planning_scolaire_si_aucun_planning_vacances(self, app, db, sample_users, sample_planning):
        with app.app_context():
            from utils import get_planning_valide_a_date

            db.execute('''
                INSERT INTO periodes_vacances (nom, date_debut, date_fin, created_by)
                VALUES (?, ?, ?, ?)
            ''', ('Vacances test', '2025-02-10', '2025-02-14', sample_users['directeur_id']))
            db.commit()

            planning = get_planning_valide_a_date(sample_users['salarie_id'], 'vacances', '2025-02-12')

            assert planning is not None
            assert planning['type_periode'] == 'periode_scolaire'
            assert planning['lundi_matin_debut'] == sample_planning['lundi_matin_debut']

    def test_vacances_utilise_la_bonne_semaine_alternee_si_aucun_planning_vacances(self, app, db, sample_users):
        with app.app_context():
            from utils import get_planning_valide_a_date

            db.execute('DELETE FROM planning_theorique WHERE user_id = ?', (sample_users['salarie_id'],))
            db.execute('DELETE FROM alternance_reference WHERE user_id = ?', (sample_users['salarie_id'],))

            db.execute('''
                INSERT INTO planning_theorique (
                    user_id, type_periode, date_debut_validite, type_alternance,
                    lundi_matin_debut, lundi_matin_fin, lundi_aprem_debut, lundi_aprem_fin,
                    mardi_matin_debut, mardi_matin_fin, mardi_aprem_debut, mardi_aprem_fin,
                    mercredi_matin_debut, mercredi_matin_fin, mercredi_aprem_debut, mercredi_aprem_fin,
                    jeudi_matin_debut, jeudi_matin_fin, jeudi_aprem_debut, jeudi_aprem_fin,
                    vendredi_matin_debut, vendredi_matin_fin, vendredi_aprem_debut, vendredi_aprem_fin,
                    total_hebdo
                ) VALUES (
                    ?, 'periode_scolaire', '2025-01-01', 'semaine_1',
                    '08:00', '12:00', '13:00', '16:00',
                    '08:00', '12:00', '13:00', '16:00',
                    '08:00', '12:00', '13:00', '16:00',
                    '08:00', '12:00', '13:00', '16:00',
                    '08:00', '12:00', '13:00', '16:00',
                    35.0
                )
            ''', (sample_users['salarie_id'],))

            db.execute('''
                INSERT INTO planning_theorique (
                    user_id, type_periode, date_debut_validite, type_alternance,
                    lundi_matin_debut, lundi_matin_fin, lundi_aprem_debut, lundi_aprem_fin,
                    mardi_matin_debut, mardi_matin_fin, mardi_aprem_debut, mardi_aprem_fin,
                    mercredi_matin_debut, mercredi_matin_fin, mercredi_aprem_debut, mercredi_aprem_fin,
                    jeudi_matin_debut, jeudi_matin_fin, jeudi_aprem_debut, jeudi_aprem_fin,
                    vendredi_matin_debut, vendredi_matin_fin, vendredi_aprem_debut, vendredi_aprem_fin,
                    total_hebdo
                ) VALUES (
                    ?, 'periode_scolaire', '2025-01-01', 'semaine_2',
                    '09:00', '12:00', '13:30', '17:30',
                    '09:00', '12:00', '13:30', '17:30',
                    '09:00', '12:00', '13:30', '17:30',
                    '09:00', '12:00', '13:30', '17:30',
                    '09:00', '12:00', '13:30', '17:30',
                    35.0
                )
            ''', (sample_users['salarie_id'],))

            db.execute('''
                INSERT INTO alternance_reference (user_id, date_reference, date_debut_validite)
                VALUES (?, ?, ?)
            ''', (sample_users['salarie_id'], '2025-01-06', '2025-01-01'))

            db.execute('''
                INSERT INTO periodes_vacances (nom, date_debut, date_fin, created_by)
                VALUES (?, ?, ?, ?)
            ''', ('Vacances alternées', '2025-01-13', '2025-01-17', sample_users['directeur_id']))
            db.commit()

            planning = get_planning_valide_a_date(sample_users['salarie_id'], 'vacances', '2025-01-13')

            assert planning is not None
            assert planning['type_periode'] == 'periode_scolaire'
            assert planning['type_alternance'] == 'semaine_2'
            assert planning['lundi_matin_debut'] == '09:00'


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
