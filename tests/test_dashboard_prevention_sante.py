from datetime import datetime, timedelta


def _latest_business_day():
    day = datetime.now().date()
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.strftime("%Y-%m-%d")


def _insert_hours(db, user_id, date_str, morning_start, morning_end, afternoon_start, afternoon_end, declaration_conforme=0):
    db.execute(
        """
        INSERT INTO heures_reelles
            (user_id, date, heure_debut_matin, heure_fin_matin, heure_debut_aprem, heure_fin_aprem, type_saisie, declaration_conforme)
        VALUES (?, ?, ?, ?, ?, ?, 'heures_modifiees', ?)
        """,
        (user_id, date_str, morning_start, morning_end, afternoon_start, afternoon_end, declaration_conforme),
    )


class TestDashboardPreventionSante:
    def test_affiche_message_sans_pause_apres_6h(self, auth_client, app, db, sample_users, sample_planning):
        date_str = _latest_business_day()
        with app.app_context():
            _insert_hours(db, sample_users["salarie_id"], date_str, "08:00", "15:00", None, None)
            db.commit()

        response = auth_client.get("/dashboard")
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert "Prévention santé au travail." in html
        assert "Ta fiche indique une journée de plus de 6h sans pause." in html
        assert "J’ai pris connaissance du conseil" in html

        dismissed_key = f"prev:s1_no_pause:{date_str}"
        response_dismiss = auth_client.post(
            "/dashboard/prevention_dismiss",
            data={"keys": [dismissed_key]},
            follow_redirects=True,
        )
        html_after = response_dismiss.get_data(as_text=True)

        assert response_dismiss.status_code == 200
        assert "Ta fiche indique une journée de plus de 6h sans pause." not in html_after
        assert "Prévention santé au travail." not in html_after

    def test_affiche_message_pause_inferieure_20_minutes(self, auth_client, app, db, sample_users, sample_planning):
        date_str = _latest_business_day()
        with app.app_context():
            db.execute("DELETE FROM heures_reelles WHERE user_id = ?", (sample_users["salarie_id"],))
            _insert_hours(db, sample_users["salarie_id"], date_str, "08:00", "12:00", "12:10", "14:30")
            db.commit()

        response = auth_client.get("/dashboard")
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert "Prévention santé au travail." in html
        assert "Ta pause semble courte par rapport à ta durée de travail." in html

