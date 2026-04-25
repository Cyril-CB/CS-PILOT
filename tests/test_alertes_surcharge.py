from datetime import datetime, timedelta


def _recent_business_days(limit):
    days = []
    current = datetime.now().date() - timedelta(days=1)
    while len(days) < limit:
        if current.weekday() < 5:
            days.append(current.strftime('%Y-%m-%d'))
        current -= timedelta(days=1)
    days.reverse()
    return days


def _first_weekdays_of_previous_month(limit):
    today = datetime.now().date()
    first_day_current_month = today.replace(day=1)
    last_day_previous_month = first_day_current_month - timedelta(days=1)
    current = last_day_previous_month.replace(day=1)

    days = []
    while len(days) < limit:
        if current.weekday() < 5:
            days.append(current.strftime('%Y-%m-%d'))
        current += timedelta(days=1)
    return days


def _insert_hours(db, user_id, date_str, morning_start, morning_end, afternoon_start, afternoon_end, declaration_conforme=0):
    db.execute(
        '''
        INSERT INTO heures_reelles
            (user_id, date, heure_debut_matin, heure_fin_matin, heure_debut_aprem, heure_fin_aprem, type_saisie, declaration_conforme)
        VALUES (?, ?, ?, ?, ?, ?, 'heures_modifiees', ?)
        ''',
        (user_id, date_str, morning_start, morning_end, afternoon_start, afternoon_end, declaration_conforme)
    )


def _insert_alternating_planning(db, user_id, date_reference):
    db.execute('DELETE FROM planning_theorique WHERE user_id = ?', (user_id,))
    db.execute('DELETE FROM alternance_reference WHERE user_id = ?', (user_id,))

    for type_alternance in ('semaine_1', 'semaine_2'):
        db.execute(
            '''
            INSERT INTO planning_theorique (
                user_id, type_periode, date_debut_validite, type_alternance,
                lundi_matin_debut, lundi_matin_fin, lundi_aprem_debut, lundi_aprem_fin,
                mardi_matin_debut, mardi_matin_fin, mardi_aprem_debut, mardi_aprem_fin,
                mercredi_matin_debut, mercredi_matin_fin, mercredi_aprem_debut, mercredi_aprem_fin,
                jeudi_matin_debut, jeudi_matin_fin, jeudi_aprem_debut, jeudi_aprem_fin,
                vendredi_matin_debut, vendredi_matin_fin, vendredi_aprem_debut, vendredi_aprem_fin,
                total_hebdo
            ) VALUES (
                ?, 'periode_scolaire', '2000-01-01', ?,
                '08:30', '12:00', '13:30', '17:00',
                '08:30', '12:00', '13:30', '17:00',
                '08:30', '12:00', '13:30', '17:00',
                '08:30', '12:00', '13:30', '17:00',
                '08:30', '12:00', '13:30', '17:00',
                35.0
            )
            ''',
            (user_id, type_alternance)
        )

    db.execute(
        '''
        INSERT INTO alternance_reference (user_id, date_reference, date_debut_validite)
        VALUES (?, ?, '2000-01-01')
        ''',
        (user_id, date_reference)
    )


class TestAlertesSurchargeAcces:
    def test_directeur_et_comptable_accedent_a_la_page(self, admin_client, comptable_client):
        response_admin = admin_client.get('/alertes_surcharge')
        response_comptable = comptable_client.get('/alertes_surcharge')

        assert response_admin.status_code == 200
        assert response_comptable.status_code == 200
        assert 'Alertes surcharge' in response_admin.get_data(as_text=True)

    def test_salarie_et_responsable_sont_refuses(self, auth_client, resp_client):
        response_salarie = auth_client.get('/alertes_surcharge', follow_redirects=True)
        response_responsable = resp_client.get('/alertes_surcharge', follow_redirects=True)

        assert response_salarie.status_code == 200
        assert response_responsable.status_code == 200
        assert 'accès non autorisé' in response_salarie.get_data(as_text=True).lower()
        assert 'accès non autorisé' in response_responsable.get_data(as_text=True).lower()


class TestAlertesSurchargeCalcul:
    def test_affiche_salarie_avec_score_et_sparkline(self, admin_client, app, db, sample_users, sample_planning):
        with app.app_context():
            db.execute(
                'UPDATE users SET solde_initial = ? WHERE id = ?',
                (9, sample_users['salarie_id'])
            )

            for date_str in _recent_business_days(5):
                _insert_hours(
                    db,
                    sample_users['salarie_id'],
                    date_str,
                    '07:30',
                    '12:00',
                    '12:10',
                    '18:30',
                )

            for date_str in _first_weekdays_of_previous_month(3):
                _insert_hours(
                    db,
                    sample_users['salarie_id'],
                    date_str,
                    '08:30',
                    '12:00',
                    '13:30',
                    '19:00',
                )

            db.commit()

        response = admin_client.get('/alertes_surcharge')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'Jean Martin' in html
        assert 'Orange' in html
        assert '70/100' in html
        assert 'Solde du dernier mois écoulé : +6.0h' in html
        assert 'surcharge-sparkline' in html
        assert 'Vue mensuelle' in html

    def test_n_affiche_pas_les_profils_sans_score(self, admin_client, sample_users, sample_planning):
        response = admin_client.get('/alertes_surcharge')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'Jean Martin' not in html
        assert 'Aucune alerte de surcharge détectée' in html

    def test_ne_signale_pas_un_planning_alterné_quand_les_heures_matchent(self, admin_client, app, db, sample_users, sample_planning):
        target_date = _recent_business_days(1)[0]

        with app.app_context():
            _insert_alternating_planning(db, sample_users['salarie_id'], target_date)
            _insert_hours(
                db,
                sample_users['salarie_id'],
                target_date,
                '08:30',
                '12:00',
                '13:30',
                '17:00',
            )
            db.commit()

        response = admin_client.get('/alertes_surcharge')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'Jean Martin' not in html
        assert 'Aucune alerte de surcharge détectée' in html
