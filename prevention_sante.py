"""
Prévention santé au travail : détection de situations à partir des heures saisies.

Ce module est utilisé sur le dashboard des salariés pour afficher, si besoin,
des messages de prévention (avec possibilité d'accusé de réception).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, time


MIN_BREAK_MINUTES = 20
MIN_DAILY_REST_HOURS = 11
MAX_CONSECUTIVE_HOURS_WITHOUT_REAL_BREAK = 6


@dataclass(frozen=True)
class PreventionMessage:
    key: str
    text: str


def _get_feries_set(conn) -> set[str]:
    return {row["date"] for row in conn.execute("SELECT date FROM jours_feries").fetchall()}


def _get_type_periode_cached(conn, date_str: str, type_periode_cache: dict[str, str]) -> str:
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

    date_ref = datetime.strptime(ref["date_reference"], "%Y-%m-%d")
    date_actuelle = datetime.strptime(date_str, "%Y-%m-%d")
    semaines_ecoulees = (date_actuelle - date_ref).days // 7
    return "semaine_1" if (semaines_ecoulees % 2 == 0) else "semaine_2"


def _get_planning_cached(conn, user_id: int, date_str: str, planning_cache: dict, type_periode_cache: dict[str, str]):
    cache_key = (user_id, date_str)
    if cache_key in planning_cache:
        return planning_cache[cache_key]

    type_periode = _get_type_periode_cached(conn, date_str, type_periode_cache)
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

        return conn.execute(
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

    planning = _chercher_planning(type_periode)
    if not planning and type_periode == "vacances":
        planning = _chercher_planning("periode_scolaire")

    planning_cache[cache_key] = planning
    return planning


def _day_segments_from_row(row) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    if row["heure_debut_matin"] and row["heure_fin_matin"]:
        segments.append((row["heure_debut_matin"], row["heure_fin_matin"]))
    if row["heure_debut_aprem"] and row["heure_fin_aprem"]:
        segments.append((row["heure_debut_aprem"], row["heure_fin_aprem"]))
    return segments


def _day_segments_from_planning(planning, date_obj) -> list[tuple[str, str]]:
    if not planning:
        return []
    if date_obj.weekday() > 4:
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


def _compute_segments_metrics(date_obj, segments: list[tuple[str, str]]):
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


def _compute_day_metrics(conn, user_id: int, row, planning_cache: dict, type_periode_cache: dict[str, str]):
    date_obj = datetime.strptime(row["date"], "%Y-%m-%d").date()
    planning = _get_planning_cached(conn, user_id, row["date"], planning_cache, type_periode_cache)
    planned_segments = _day_segments_from_planning(planning, date_obj)
    actual_segments = planned_segments if row["declaration_conforme"] else _day_segments_from_row(row)

    planned_metrics = _compute_segments_metrics(date_obj, planned_segments)
    actual_metrics = _compute_segments_metrics(date_obj, actual_segments)

    theoretical_hours = planned_metrics["worked_hours"] if date_obj.weekday() < 5 else 0.0
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


def _recent_business_days(end_date, limit: int, feries_set: set[str]) -> list[str]:
    days: list[str] = []
    current = end_date
    while len(days) < limit:
        current_str = current.strftime("%Y-%m-%d")
        if current.weekday() < 5 and current_str not in feries_set:
            days.append(current_str)
        current -= timedelta(days=1)
    days.reverse()
    return days


def _get_last_completed_week_monday(reference_date):
    current_week_monday = reference_date - timedelta(days=reference_date.weekday())
    return current_week_monday - timedelta(days=7)


def _week_dates(week_monday, feries_set: set[str]) -> list[str]:
    dates = []
    for offset in range(5):
        date_obj = week_monday + timedelta(days=offset)
        date_str = date_obj.strftime("%Y-%m-%d")
        if date_str not in feries_set:
            dates.append(date_str)
    return dates


def _find_last_worked_day(day_metrics: dict[str, dict]) -> dict | None:
    if not day_metrics:
        return None
    for date_str in sorted(day_metrics.keys(), reverse=True):
        metrics = day_metrics[date_str]
        if metrics["actual_hours"] and metrics["actual_hours"] > 0:
            return metrics
    return None


def _load_dismissed_keys(conn, user_id: int, keys: list[str]) -> set[str]:
    if not keys:
        return set()
    placeholders = ",".join(["?"] * len(keys))
    rows = conn.execute(
        f"""
        SELECT message_key
        FROM prevention_dismissals
        WHERE user_id = ?
          AND message_key IN ({placeholders})
        """,
        (user_id, *keys),
    ).fetchall()
    return {row["message_key"] for row in rows}


def compute_prevention_messages(conn, user_id: int, today=None) -> list[PreventionMessage]:
    """Retourne une liste de messages de prévention à afficher sur le dashboard."""
    if today is None:
        today = datetime.now().date()

    feries_set = _get_feries_set(conn)
    lookback_start = (today - timedelta(days=120)).strftime("%Y-%m-%d")

    rows = conn.execute(
        """
        SELECT date, heure_debut_matin, heure_fin_matin, heure_debut_aprem, heure_fin_aprem, declaration_conforme
        FROM heures_reelles
        WHERE user_id = ? AND date >= ? AND date <= ?
        ORDER BY date
        """,
        (user_id, lookback_start, today.strftime("%Y-%m-%d")),
    ).fetchall()

    planning_cache: dict = {}
    type_periode_cache: dict[str, str] = {}
    day_metrics: dict[str, dict] = {}

    for row in rows:
        metrics = _compute_day_metrics(conn, user_id, row, planning_cache, type_periode_cache)
        day_metrics[metrics["date"]] = metrics

    last_day = _find_last_worked_day(day_metrics)
    if not last_day:
        return []

    messages: list[PreventionMessage] = []

    # --- Situations basées sur la dernière journée saisie ---
    date_ctx = last_day["date"]

    # Situation 1 / 2 : pauses après 6h consécutives
    if (
        last_day["actual_hours"] > MAX_CONSECUTIVE_HOURS_WITHOUT_REAL_BREAK
        and last_day["longest_consecutive_hours"] > MAX_CONSECUTIVE_HOURS_WITHOUT_REAL_BREAK
        and (last_day["break_minutes"] is None or last_day["break_minutes"] <= 0)
    ):
        messages.append(
            PreventionMessage(
                key=f"prev:s1_no_pause:{date_ctx}",
                text=(
                    "Ta fiche indique une journée de plus de 6h sans pause. Pense à vérifier ta saisie. "
                    "Une vraie coupure aide à récupérer et à éviter l’accumulation de fatigue. "
                    "La pause n'est pas seulement un droit, elle est obligatoire après 6 heures de travail."
                ),
            )
        )
    elif (
        last_day["longest_consecutive_hours"] > MAX_CONSECUTIVE_HOURS_WITHOUT_REAL_BREAK
        and last_day["break_minutes"] is not None
        and 0 < last_day["break_minutes"] < MIN_BREAK_MINUTES
    ):
        messages.append(
            PreventionMessage(
                key=f"prev:s2_pause_courte:{date_ctx}",
                text=(
                    "Ta pause semble courte par rapport à ta durée de travail. Si c’est une erreur, tu peux corriger ta fiche. "
                    "Si cela se répète, il peut être utile d’en parler avec ton/ta responsable pour trouver le temps de prendre une véritable pause. "
                    "La pause n'est pas seulement un droit, elle est obligatoire après 6 heures de travail et doit durer au minimum 20 minutes."
                ),
            )
        )

    # Situation 6 / 7 : journées longues
    if last_day["actual_hours"] >= 10:
        messages.append(
            PreventionMessage(
                key=f"prev:s7_10h_plus:{date_ctx}",
                text=(
                    "Ta fiche indique une journée très longue. Vérifie qu’il ne s’agit pas d’une erreur de saisie. "
                    "Si c’est exact, il est conseillé d’en parler avec ton responsable et de prendre une récupération."
                ),
            )
        )
    elif last_day["actual_hours"] >= 9:
        messages.append(
            PreventionMessage(
                key=f"prev:s6_9h:{date_ctx}",
                text="Ta semaine semble avoir été particulièrement chargée. Pense à surveiller ta récupération.",
            )
        )

    # Situation 8 : grande amplitude
    if last_day["start_at"] and last_day["end_at"]:
        if last_day["start_at"].time() < time(8, 30) and last_day["end_at"].time() > time(18, 30):
            messages.append(
                PreventionMessage(
                    key=f"prev:s8_amplitude:{date_ctx}",
                    text=(
                        "L’amplitude de ta journée paraît importante. Même avec des pauses, cela peut générer de la fatigue. "
                        "Pense à le signaler si cette organisation se répète."
                    ),
                )
            )

    # --- Situations basées sur une fenêtre récente ---
    reference_date = last_day["date_obj"]
    recent_10 = _recent_business_days(reference_date, 10, feries_set)
    recent_20 = _recent_business_days(reference_date, 20, feries_set)

    # Situation 3 : pauses souvent réduites (>=20 min) par rapport au planning
    reduced_count = 0
    for day in recent_10:
        metrics = day_metrics.get(day)
        if not metrics:
            continue
        if (
            metrics["pause_reduced"]
            and metrics["planned_break_minutes"] is not None
            and metrics["break_minutes"] is not None
            and metrics["break_minutes"] >= MIN_BREAK_MINUTES
        ):
            reduced_count += 1
    if reduced_count >= 3:
        messages.append(
            PreventionMessage(
                key=f"prev:s3_pause_reduite_10j:{date_ctx}",
                text=(
                    "Plusieurs journées récentes indiquent une pause réduite. "
                    "Ce n’est pas forcément grave ponctuellement, mais répété cela peut être un signal de charge de travail trop élevée."
                ),
            )
        )

    # Situation 9 : repos quotidien < 11h
    last_rest_issue = None
    previous = None
    for day in recent_20:
        metrics = day_metrics.get(day)
        if not metrics or not metrics["start_at"] or not metrics["end_at"]:
            continue
        if previous:
            rest_hours = (metrics["start_at"] - previous["end_at"]).total_seconds() / 3600
            if 0 < rest_hours < MIN_DAILY_REST_HOURS:
                last_rest_issue = day
        previous = metrics
    if last_rest_issue:
        messages.append(
            PreventionMessage(
                key=f"prev:s9_repos_11h:{last_rest_issue}",
                text=(
                    "Le temps entre ta fin de journée et ta reprise semble court. "
                    "Vérifie ta saisie. Si c’est bien le cas, il est important d’en parler pour préserver ton bien-être."
                ),
            )
        )

    # Situation 10 : 3 journées consécutives >= 9h
    last_streak_9h = None
    for idx in range(2, len(recent_20)):
        d1, d2, d3 = recent_20[idx - 2], recent_20[idx - 1], recent_20[idx]
        if (
            day_metrics.get(d1, {}).get("actual_hours", 0) >= 9
            and day_metrics.get(d2, {}).get("actual_hours", 0) >= 9
            and day_metrics.get(d3, {}).get("actual_hours", 0) >= 9
        ):
            last_streak_9h = d3
    if last_streak_9h:
        messages.append(
            PreventionMessage(
                key=f"prev:s10_3j_9h:{last_streak_9h}",
                text=(
                    "Tu as plusieurs journées chargées à la suite. "
                    "Pense à surveiller ton niveau de fatigue et à anticiper une récupération si besoin."
                ),
            )
        )

    # Situation 11 : aucune pause plusieurs jours de suite (>=3)
    last_streak_no_break = None
    for idx in range(2, len(recent_20)):
        d1, d2, d3 = recent_20[idx - 2], recent_20[idx - 1], recent_20[idx]
        ok = True
        for day in (d1, d2, d3):
            metrics = day_metrics.get(day)
            if not metrics:
                ok = False
                break
            no_break = metrics["break_minutes"] is None or metrics["break_minutes"] <= 0
            if not (metrics["actual_hours"] > 6 and no_break):
                ok = False
                break
        if ok:
            last_streak_no_break = d3
    if last_streak_no_break:
        messages.append(
            PreventionMessage(
                key=f"prev:s11_3j_sans_pause:{last_streak_no_break}",
                text=(
                    "Plusieurs journées indiquent peu ou pas de pause. "
                    "Si c’est exact, il est important de préserver une vraie coupure dans la journée."
                ),
            )
        )

    # Situations hebdomadaires : basées sur les semaines complètes terminées
    last_week_monday = _get_last_completed_week_monday(reference_date)
    week_dates = _week_dates(last_week_monday, feries_set)
    week_total = round(sum(day_metrics.get(day, {}).get("actual_hours", 0) for day in week_dates), 2)
    if week_total > 42:
        messages.append(
            PreventionMessage(
                key=f"prev:s5_42h_semaine:{last_week_monday.strftime('%Y-%m-%d')}",
                text="Ta semaine semble avoir été particulièrement chargée. Pense à surveiller ta récupération.",
            )
        )

    # Situation 4 : heures supplémentaires récurrentes sur 3 semaines
    overtime_3_weeks_ok = True
    for offset in range(3):
        week_monday = last_week_monday - timedelta(days=offset * 7)
        dates = _week_dates(week_monday, feries_set)
        weekly_theoretical = sum(day_metrics.get(day, {}).get("theoretical_hours", 0) for day in dates)
        weekly_overtime = sum(max(day_metrics.get(day, {}).get("delta", 0), 0) for day in dates)
        if weekly_theoretical <= 0 or weekly_overtime <= 0:
            overtime_3_weeks_ok = False
            break
    if overtime_3_weeks_ok:
        messages.append(
            PreventionMessage(
                key=f"prev:s4_hsup_3sem:{last_week_monday.strftime('%Y-%m-%d')}",
                text=(
                    "Tes fiches montrent des heures en plus plusieurs semaines de suite. "
                    "Si cette situation devient habituelle, un échange avec ton/ta responsable peut aider à voir si la charge "
                    "ou l’organisation du travail doivent être ajustées."
                ),
            )
        )

    # Situation 12 : charge qui augmente progressivement (3 semaines ou plus)
    weekly_totals = []
    for offset in range(3):
        week_monday = last_week_monday - timedelta(days=offset * 7)
        dates = _week_dates(week_monday, feries_set)
        weekly_totals.append(round(sum(day_metrics.get(day, {}).get("actual_hours", 0) for day in dates), 2))
    week3, week2, week1 = weekly_totals[0], weekly_totals[1], weekly_totals[2]
    if week1 > 0 and week2 > 0 and week3 > 0 and week1 < week2 < week3:
        messages.append(
            PreventionMessage(
                key=f"prev:s12_hausse_3sem:{last_week_monday.strftime('%Y-%m-%d')}",
                text=(
                    "Ta charge déclarée semble augmenter depuis plusieurs semaines. "
                    "Pense à surveiller ton équilibre et à demander un point si cela devient difficile."
                ),
            )
        )

    # Filtrer les messages déjà accusés réception.
    dismissed = _load_dismissed_keys(conn, user_id, [m.key for m in messages])
    return [m for m in messages if m.key not in dismissed]

