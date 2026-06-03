"""
Helpers partagés pour les calculs de planning et de métriques journalières.
"""

from __future__ import annotations

from datetime import datetime, timedelta


MIN_BREAK_MINUTES = 20
BUSINESS_DAYS_PER_WEEK = 5
SATURDAY_WEEKDAY_INDEX = 5


def get_feries_set(conn) -> set[str]:
    return {row["date"] for row in conn.execute("SELECT date FROM jours_feries").fetchall()}


def get_type_periode_cached(conn, date_str: str, type_periode_cache: dict[str, str]) -> str:
    if date_str not in type_periode_cache:
        periode = conn.execute(
            """
            SELECT 1
            FROM periodes_vacances
            WHERE ? >= date_debut AND ? <= date_fin
            LIMIT 1
            """,
            (date_str, date_str),
        ).fetchone()
        type_periode_cache[date_str] = "vacances" if periode else "periode_scolaire"
    return type_periode_cache[date_str]


def _get_semaine_alternance(conn, user_id: int, date_str: str) -> str:
    ref = conn.execute(
        """
        SELECT date_reference
        FROM alternance_reference
        WHERE user_id = ? AND date_debut_validite <= ?
        ORDER BY date_debut_validite DESC
        LIMIT 1
        """,
        (user_id, date_str),
    ).fetchone()
    if not ref:
        return "fixe"

    still_alternating = conn.execute(
        """
        SELECT 1 FROM planning_theorique p
        WHERE p.user_id = ?
          AND p.type_alternance IN ('semaine_1', 'semaine_2')
          AND p.date_debut_validite <= ?
          AND NOT EXISTS (
              SELECT 1 FROM planning_theorique p2
              WHERE p2.user_id = p.user_id
                AND p2.type_periode = p.type_periode
                AND p2.type_alternance = 'fixe'
                AND p2.date_debut_validite > p.date_debut_validite
                AND p2.date_debut_validite <= ?
          )
        LIMIT 1
        """,
        (user_id, date_str, date_str),
    ).fetchone()
    if not still_alternating:
        return "fixe"

    date_ref = datetime.strptime(ref["date_reference"], "%Y-%m-%d")
    date_actuelle = datetime.strptime(date_str, "%Y-%m-%d")
    semaines_ecoulees = (date_actuelle - date_ref).days // 7
    return "semaine_1" if (semaines_ecoulees % 2 == 0) else "semaine_2"


def get_planning_cached(conn, user_id: int, date_str: str, planning_cache: dict, type_periode_cache: dict[str, str]):
    cache_key = (user_id, date_str)
    if cache_key in planning_cache:
        return planning_cache[cache_key]

    type_periode = get_type_periode_cached(conn, date_str, type_periode_cache)
    semaine_type = _get_semaine_alternance(conn, user_id, date_str)

    def _chercher_planning(type_periode_recherche: str):
        if semaine_type == "fixe":
            return conn.execute(
                """
                SELECT *
                FROM planning_theorique
                WHERE user_id = ?
                  AND type_periode = ?
                  AND (type_alternance IS NULL OR type_alternance = 'fixe')
                  AND date_debut_validite <= ?
                ORDER BY date_debut_validite DESC
                LIMIT 1
                """,
                (user_id, type_periode_recherche, date_str),
            ).fetchone()

        planning = conn.execute(
            """
            SELECT *
            FROM planning_theorique
            WHERE user_id = ?
              AND type_periode = ?
              AND type_alternance = ?
              AND date_debut_validite <= ?
            ORDER BY date_debut_validite DESC
            LIMIT 1
            """,
            (user_id, type_periode_recherche, semaine_type, date_str),
        ).fetchone()

        # Fallback : si aucun planning alterné pour ce type_periode, utiliser le planning fixe
        if not planning:
            planning = conn.execute(
                """
                SELECT *
                FROM planning_theorique
                WHERE user_id = ?
                  AND type_periode = ?
                  AND (type_alternance IS NULL OR type_alternance = 'fixe')
                  AND date_debut_validite <= ?
                ORDER BY date_debut_validite DESC
                LIMIT 1
                """,
                (user_id, type_periode_recherche, date_str),
            ).fetchone()

        return planning

    planning = _chercher_planning(type_periode)
    if not planning and type_periode == "vacances":
        planning = _chercher_planning("periode_scolaire")

    planning_cache[cache_key] = planning
    return planning


def day_segments_from_row(row) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    if row["heure_debut_matin"] and row["heure_fin_matin"]:
        segments.append((row["heure_debut_matin"], row["heure_fin_matin"]))
    if row["heure_debut_aprem"] and row["heure_fin_aprem"]:
        segments.append((row["heure_debut_aprem"], row["heure_fin_aprem"]))
    return segments


def day_segments_from_planning(planning, date_obj) -> list[tuple[str, str]]:
    if not planning or date_obj.weekday() >= BUSINESS_DAYS_PER_WEEK:
        return []

    jour_nom = ["lundi", "mardi", "mercredi", "jeudi", "vendredi"][date_obj.weekday()]
    segments: list[tuple[str, str]] = []
    matin_debut = planning[f"{jour_nom}_matin_debut"]
    matin_fin = planning[f"{jour_nom}_matin_fin"]
    aprem_debut = planning[f"{jour_nom}_aprem_debut"]
    aprem_fin = planning[f"{jour_nom}_aprem_fin"]

    if matin_debut and matin_fin:
        segments.append((matin_debut, matin_fin))
    if aprem_debut and aprem_fin:
        segments.append((aprem_debut, aprem_fin))
    return segments


def compute_segments_metrics(date_obj, segments: list[tuple[str, str]]):
    metrics = {
        "worked_hours": 0.0,
        "start_at": None,
        "end_at": None,
        "break_minutes": None,
        "longest_consecutive_hours": 0.0,
    }
    if not segments:
        return metrics

    dt_segments: list[tuple[datetime, datetime]] = []
    for start_str, end_str in segments:
        start_dt = datetime.combine(date_obj, datetime.strptime(start_str, "%H:%M").time())
        end_dt = datetime.combine(date_obj, datetime.strptime(end_str, "%H:%M").time())
        if end_dt < start_dt:
            end_dt += timedelta(days=1)
        dt_segments.append((start_dt, end_dt))

    metrics["worked_hours"] = round(sum((end - start).total_seconds() for start, end in dt_segments) / 3600, 2)
    metrics["start_at"] = dt_segments[0][0]
    metrics["end_at"] = dt_segments[-1][1]

    if len(dt_segments) >= 2:
        break_seconds = (dt_segments[1][0] - dt_segments[0][1]).total_seconds()
        metrics["break_minutes"] = round(max(0, break_seconds) / 60, 2)

    longest_seconds = (dt_segments[0][1] - dt_segments[0][0]).total_seconds()
    current_seconds = longest_seconds
    for index in range(1, len(dt_segments)):
        gap_seconds = (dt_segments[index][0] - dt_segments[index - 1][1]).total_seconds()
        segment_seconds = (dt_segments[index][1] - dt_segments[index][0]).total_seconds()
        if gap_seconds < MIN_BREAK_MINUTES * 60:
            current_seconds += max(gap_seconds, 0) + segment_seconds
        else:
            longest_seconds = max(longest_seconds, current_seconds)
            current_seconds = segment_seconds
    longest_seconds = max(longest_seconds, current_seconds)
    metrics["longest_consecutive_hours"] = round(longest_seconds / 3600, 2)

    return metrics


def compute_day_metrics(conn, user_id: int, row, planning_cache: dict, type_periode_cache: dict[str, str]):
    date_obj = datetime.strptime(row["date"], "%Y-%m-%d").date()
    planning = get_planning_cached(conn, user_id, row["date"], planning_cache, type_periode_cache)
    planned_segments = day_segments_from_planning(planning, date_obj)
    actual_segments = planned_segments if row["declaration_conforme"] else day_segments_from_row(row)

    planned_metrics = compute_segments_metrics(date_obj, planned_segments)
    actual_metrics = compute_segments_metrics(date_obj, actual_segments)

    theoretical_hours = planned_metrics["worked_hours"] if date_obj.weekday() < BUSINESS_DAYS_PER_WEEK else 0.0
    actual_hours = theoretical_hours if row["declaration_conforme"] else actual_metrics["worked_hours"]

    pause_reduced = (
        planned_metrics["break_minutes"] is not None
        and actual_metrics["break_minutes"] is not None
        and actual_metrics["break_minutes"] < planned_metrics["break_minutes"]
    )

    return {
        "date": row["date"],
        "date_obj": date_obj,
        "theoretical_hours": theoretical_hours,
        "actual_hours": actual_hours,
        "delta": round(actual_hours - theoretical_hours, 2),
        "start_at": actual_metrics["start_at"],
        "end_at": actual_metrics["end_at"],
        "break_minutes": actual_metrics["break_minutes"],
        "planned_break_minutes": planned_metrics["break_minutes"],
        "pause_reduced": pause_reduced,
        "longest_consecutive_hours": actual_metrics["longest_consecutive_hours"],
    }


def recent_business_days(end_date, limit: int, feries_set: set[str]) -> list[str]:
    days: list[str] = []
    current = end_date
    while len(days) < limit:
        current_str = current.strftime("%Y-%m-%d")
        if current.weekday() < BUSINESS_DAYS_PER_WEEK and current_str not in feries_set:
            days.append(current_str)
        current -= timedelta(days=1)
    days.reverse()
    return days


def get_last_completed_week_monday(reference_date):
    current_week_monday = reference_date - timedelta(days=reference_date.weekday())
    return current_week_monday - timedelta(days=7)
