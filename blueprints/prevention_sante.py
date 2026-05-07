"""
Prévention santé au travail : détection de situations à partir des heures saisies.

Ce module est utilisé sur le dashboard des salariés pour afficher, si besoin,
des messages de prévention (avec possibilité d'accusé de réception).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, time

from blueprints.worktime_metrics import (
    MIN_BREAK_MINUTES,
    compute_day_metrics as _compute_day_metrics,
    get_feries_set as _get_feries_set,
    get_last_completed_week_monday as _get_last_completed_week_monday,
    recent_business_days as _recent_business_days,
)

MIN_DAILY_REST_HOURS = 11
MAX_CONSECUTIVE_HOURS_WITHOUT_REAL_BREAK = 6


@dataclass(frozen=True)
class PreventionMessage:
    key: str
    text: str

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
                    "Si cela se répète, il peut être utile d’en parler avec ton/ta responsable. "
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
                    "Ce n’est pas forcément grave ponctuellement, mais si cela se répète, cela peut être un signal de charge de travail trop élevée."
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

    # Filtrer les messages déjà accusés de réception.
    dismissed = _load_dismissed_keys(conn, user_id, [m.key for m in messages])
    return [m for m in messages if m.key not in dismissed]
