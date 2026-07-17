"""Deterministic presentation of the driver profile.

Verdict one-liners (exact-string tested, like nudges), the page markdown,
and the compact prompt block injected into the race debrief. No AI here —
the AI only ever consumes this output as context.
"""

import json

from core.profile.models import (
    RACECRAFT_MIN_RACES,
    TECHNIQUE_MIN_SESSIONS,
    ComboReadiness,
    DriverProfile,
    IncidentTendency,
    PaceVsResultTendency,
    StartsTendency,
    TechniqueTendencies,
    TimeToPace,
    TrajectoryTendency,
)

PROMPT_BLOCK_MAX_CHARS = 2000
PROMPT_BLOCK_MAX_COMBOS = 5
NEUTRAL_BAND = 0.5          # |mean| below this = "roughly neutral"
FADE_BAND_S = 0.15          # |fade| below this = not worth mentioning
TREND_BAND_S = 0.05          # |technique trend| below this = not worth saying
TTP_TREND_BAND_LAPS = 1.0    # |time-to-pace trend| below this = flat

_FAULT_LABEL = {
    "lift": "Apex speed",
    "braking": "Brake point",
    "release": "Brake release",
    "exit_speed": "Corner exit speed",
    "throttle": "Throttle pickup",
}


def _signed(x: float) -> str:
    """-1.4 -> '-1.4', 1.2 -> '+1.2' (avoid f-string '+-' artifacts)."""
    return f"{x:+.1f}"


def _plural(n: int, word: str) -> str:
    """Return 'N word' or 'N words' depending on n."""
    return f"{n} {word}{'' if n == 1 else 's'}"


def verdict_starts(t: StartsTendency) -> str:
    m = t.mean_lap1_net or 0.0
    if m <= -NEUTRAL_BAND:
        head = "You lose ground at the start"
    elif m >= NEUTRAL_BAND:
        head = "You gain ground at the start"
    else:
        head = "Starts are roughly neutral"
    return (
        f"{head} — avg {_signed(m)} places on lap 1 across {t.sample} races "
        f"(lost ground in {t.races_lost_ground} of {t.sample})."
    )


def verdict_pace_vs_result(t: PaceVsResultTendency) -> str:
    left = t.mean_positions_left or 0.0
    act = round(t.mean_actual_position or 0)
    des = round(t.mean_deserved_position or 0)
    lost = t.mean_incident_time_lost_s or 0.0
    if left >= NEUTRAL_BAND:
        return (
            f"Your pace deserves ~P{des} but you finish ~P{act} — the gap "
            f"is incidents and decisions, not speed "
            f"(avg {lost:.1f}s/race lost to incidents)."
        )
    if left <= -NEUTRAL_BAND:
        return (
            f"You finish ~P{act} on ~P{des} pace — strong racecraft is "
            "earning you positions."
        )
    return f"You finish about where your pace deserves (~P{act})."


def verdict_incidents(t: IncidentTendency) -> str:
    line = f"{t.mean_incident_points:.1f} incident points/race"
    if t.lap1_share is not None:
        line += f", {t.lap1_share:.0%} of incidents on lap 1"
    line += "."
    if t.recurring_corners:
        repeats = ", ".join(f"{c} ({k}x)" for c, k in t.recurring_corners)
        line += f" Repeat trouble: {repeats}."
    return line


def verdict_trajectory(t: TrajectoryTendency) -> str:
    net = t.mean_race_net or 0.0
    if net >= NEUTRAL_BAND:
        head = f"You gain {_signed(net)} places over a race on average"
    elif net <= -NEUTRAL_BAND:
        # abs(): "You lose -1.8 places" would be a double negative.
        head = f"You lose {abs(net):.1f} places over a race on average"
    else:
        head = "You finish about where you start"
    fade = t.mean_stint_fade_s   # dual-pool: gate on None-ness, not enough_data
    if fade is not None and fade >= FADE_BAND_S:
        return f"{head}, but fade late ({_signed(fade)}s second-half pace)."
    if fade is not None and fade <= -FADE_BAND_S:
        return f"{head}, and get quicker late ({_signed(fade)}s second-half pace)."
    return f"{head}."


def verdict_readiness(c: ComboReadiness) -> str:
    line = (
        f"{c.track_name} / {c.car}: {_plural(c.sessions, 'session')}, "
        f"{_plural(c.valid_laps, 'clean lap')}."
    )
    extras = []
    if c.pb_trend_s is not None:
        direction = "down" if c.pb_trend_s >= 0 else "up"
        extras.append(f"Session best {direction} {abs(c.pb_trend_s):.1f}s over the run")
    if c.consistency_s is not None:
        extras.append(f"recent laps within ±{c.consistency_s:.1f}s")
    if extras:
        line = line + " " + "; ".join(extras) + "."
    return line


def verdict_technique(t: TechniqueTendencies) -> str:
    if not t.faults:
        return ""
    f = t.faults[0]
    line = (
        f"{_FAULT_LABEL.get(f.kind, f.kind)} is your recurring loss — "
        f"{_plural(f.occurrences, 'region')} across "
        f"{_plural(f.combos, 'combo')}, avg {f.mean_time_lost_s:.1f}s each"
    )
    trend = f.trend_time_lost_s
    if trend is not None and trend <= -TREND_BAND_S:
        line += f", shrinking ({trend:+.1f}s recent)"
    elif trend is not None and trend >= TREND_BAND_S:
        line += f", growing ({trend:+.1f}s recent)"
    line += "."
    if t.recurring_corners:
        repeats = ", ".join(f"{c} ({k}x)" for c, k in t.recurring_corners[:3])
        line += f" Repeat corners: {repeats}."
    return line


def verdict_time_to_pace(t: TimeToPace) -> str:
    if t.median_laps is None:
        return ""
    line = (
        f"You need ~{t.median_laps:.0f} laps to reach pace "
        f"({_plural(t.sample_sessions, 'session')}) — races give "
        "you zero warm-up."
    )
    trend = t.trend_laps
    if trend is not None and trend <= -TTP_TREND_BAND_LAPS:
        line += f" Reaching pace sooner lately ({trend:+.0f} laps)."
    elif trend is not None and trend >= TTP_TREND_BAND_LAPS:
        line += f" Taking longer lately ({trend:+.0f} laps)."
    return line


def _tendency_payloads(p: DriverProfile) -> dict:
    r = p.racecraft
    out: dict[str, dict] = {}
    if r.starts.enough_data:
        out["starts"] = {"verdict": verdict_starts(r.starts),
                         "mean_lap1_net": r.starts.mean_lap1_net,
                         "sample": r.starts.sample}
    if r.pace_vs_result.enough_data:
        out["pace_vs_result"] = {
            "verdict": verdict_pace_vs_result(r.pace_vs_result),
            "mean_positions_left": r.pace_vs_result.mean_positions_left,
            "sample": r.pace_vs_result.sample}
    if r.incidents.enough_data:
        out["incidents"] = {"verdict": verdict_incidents(r.incidents),
                            "lap1_share": r.incidents.lap1_share,
                            "recurring": r.incidents.recurring_corners,
                            "sample": r.incidents.sample}
    if r.trajectory.enough_data:
        out["trajectory"] = {"verdict": verdict_trajectory(r.trajectory),
                             "mean_race_net": r.trajectory.mean_race_net,
                             "sample": r.trajectory.sample}
    if p.technique.enough_data:
        out["technique"] = {"verdict": verdict_technique(p.technique),
                            "dominant": p.technique.dominant,
                            "sessions": p.technique.sessions_diagnosed}
    if p.time_to_pace.enough_data:
        out["time_to_pace"] = {"verdict": verdict_time_to_pace(p.time_to_pace),
                               "median_laps": p.time_to_pace.median_laps,
                               "sample": p.time_to_pace.sample_sessions}
    return out


def profile_prompt_block(p: DriverProfile) -> str:
    """Compact grounded context for the debrief prompt; "" when nothing
    crosses threshold. Hard-capped: drops readiness combos first, then
    trailing tendencies."""
    tendencies = _tendency_payloads(p)
    ready = [c for c in p.readiness if c.enough_data][:PROMPT_BLOCK_MAX_COMBOS]
    if not tendencies and not ready:
        return ""

    def _assemble(tend: dict, combos: list[ComboReadiness]) -> str:
        payload = {
            "races": p.races_captured,
            "tendencies": tend,
            "readiness": [verdict_readiness(c) for c in combos],
        }
        return (
            f"--- DRIVER PROFILE (tendencies across {p.races_captured} "
            "prior races; computed deterministically) ---\n"
            + json.dumps(payload)
            + "\n--- END DRIVER PROFILE ---"
        )

    block = _assemble(tendencies, ready)
    while len(block) > PROMPT_BLOCK_MAX_CHARS and ready:
        ready = ready[:-1]
        block = _assemble(tendencies, ready)
    keys = list(tendencies)
    while len(block) > PROMPT_BLOCK_MAX_CHARS and keys:
        keys = keys[:-1]
        block = _assemble({k: tendencies[k] for k in keys}, ready)
    return block if (keys or ready) else ""


def profile_markdown(p: DriverProfile) -> str:
    """Page body / export text. Sub-threshold items show progress."""
    lines = [
        f"**{p.races_captured}** races captured · "
        f"**{p.combos_tracked}** combos tracked",
        "",
        "## Racecraft",
    ]
    r = p.racecraft
    for label, t, verdict in [
        ("Pace vs result", r.pace_vs_result, verdict_pace_vs_result),
        ("Starts", r.starts, verdict_starts),
        ("Incidents", r.incidents, verdict_incidents),
        ("Race trajectory", r.trajectory, verdict_trajectory),
    ]:
        if t.enough_data:
            lines.append(f"- **{label}** — {verdict(t)}")
        else:
            lines.append(
                f"- **{label}** — collecting data "
                f"({t.sample} of {RACECRAFT_MIN_RACES} races captured)."
            )
    lines += ["", "## Technique"]
    if p.technique.enough_data:
        lines.append(f"- **Technique** — {verdict_technique(p.technique)}")
    else:
        lines.append(
            f"- **Technique** — collecting data ({p.technique.sessions_diagnosed} of "
            f"{TECHNIQUE_MIN_SESSIONS} diagnosed sessions)."
        )
    if p.time_to_pace.enough_data:
        lines.append(f"- **Warm-up** — {verdict_time_to_pace(p.time_to_pace)}")
    else:
        lines.append(
            f"- **Warm-up** — collecting data "
            f"({_plural(p.time_to_pace.sample_sessions, 'session')})."
        )
    lines += ["", "## Practice readiness"]
    if not p.readiness:
        lines.append("_No practice history yet — sessions accrue "
                     "automatically via the telemetry watcher._")
    for c in p.readiness:
        if c.enough_data:
            lines.append(f"- {verdict_readiness(c)}")
        else:
            lines.append(
                f"- {c.track_name} / {c.car} — collecting data "
                f"({_plural(c.sessions, 'session')}, {_plural(c.valid_laps, 'clean lap')})."
            )
    return "\n".join(lines)
