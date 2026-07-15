"""PURE deterministic BriefingData -> markdown. Owns ALL verdict wording
(profile/render.py precedent: exact strings live here and are pinned by
exact-string tests). HARD RULE (v3 addendum section 1): the verdict never
gates - no wording may tell the driver not to race."""

from core.briefing.models import BriefingData, CurvePlacement

ON_CURVE_BAND_S = 0.15  # |delta| under this = "on the pace"

INVITE_LINE = (
    "Run a practice session at this combo and I'll place you on this "
    "week's curve."
)


def _fmt_lap(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m}:{seconds - 60 * m:06.3f}"


def verdict_line(placement: CurvePlacement | None, user_ir: int | None) -> str:
    """The curve verdict - race-positive in both directions, never a gate."""
    if placement is None or placement.implied_ir_lo is None:
        return INVITE_LINE
    band = (
        f"{placement.implied_ir_lo:,}-{placement.implied_ir_hi:,} iR"
    )
    if user_ir is None or placement.delta_to_own_band_s is None:
        return (
            f"Your {_fmt_lap(placement.lap_s)} runs like a {band} driver "
            "in this series this week."
        )
    delta = placement.delta_to_own_band_s
    if delta <= -ON_CURVE_BAND_S:
        return (
            f"Your {_fmt_lap(placement.lap_s)} runs like a {band} driver "
            "in this series this week - your pace is worth more iRating "
            "than you have. Racing is how you collect it."
        )
    if delta >= ON_CURVE_BAND_S:
        return (
            f"The median at your rating runs {delta:.1f}s quicker this "
            "week - mid-pack is a strong result here, and practice has "
            "a clear target."
        )
    return (
        "You're right on the pace for your rating - a clean race "
        "converts it to a solid finish."
    )


def render_briefing(data: BriefingData) -> str:
    """Assemble the week-plan-ordered deterministic briefing."""
    fmt = data.fmt
    lines: list[str] = [f"# Race Briefing - {data.series_name}", ""]
    for w in data.warnings:
        lines += [f"> {w}", ""]

    track = fmt.track_name + (f" ({fmt.config_name})" if fmt.config_name else "")
    lines += [f"## This week: {track}", ""]
    cost = (
        f"{fmt.race_time_limit} minutes"
        if fmt.race_time_limit
        else f"{fmt.race_lap_limit} laps" if fmt.race_lap_limit else "length n/a"
    )
    start = "standing start" if fmt.standing_start else "rolling start"
    fuel = (
        f", fuel capped at {fmt.max_pct_fuel_fill:.0f}%"
        if fmt.max_pct_fuel_fill and fmt.max_pct_fuel_fill < 100
        else ""
    )
    lines += [f"This race costs you **{cost}** - {start}{fuel}.", ""]

    lines += ["## Where you stand", ""]
    lines += [verdict_line(data.placement, data.user_irating), ""]
    if data.field_stats is not None:
        s = data.field_stats
        lines += [
            f"Field this week: SoF ~{s.sof_median:,} "
            f"(typ. {s.sof_p25:,}-{s.sof_p75:,}), "
            f"~{s.field_size_median} cars per split, "
            f"{s.splits_median} split(s) per slot.",
            "",
        ]
    if data.curve is not None and data.curve.capped:
        lines += [
            f"(Curve built from the most recent "
            f"{data.curve.subsessions_used} races this week.)",
            "",
        ]
    if data.placement is not None and data.prep is not None:
        lines += [
            "*Field laps are race laps; yours is a practice best - "
            "clean air flatters slightly.*",
            "",
        ]

    if data.prep is not None:
        p = data.prep
        lines += ["## Your preparation", ""]
        trend = (
            f", session best down {p.trend_s:.1f}s since your first visit"
            if p.trend_s is not None and p.trend_s > 0
            else ""
        )
        best = f" - best {_fmt_lap(p.best_lap_s)}" if p.best_lap_s else ""
        lines += [
            f"{p.sessions} practice sessions, {p.representative_laps} "
            f"representative laps in the {p.car}{best}{trend}.",
            "",
        ]

    if data.slots:
        lines += ["## When to run it", ""]
        for slot in data.slots:
            tag = " - fits your usual window" if slot.fits_window else ""
            lines += [f"- {slot.start_utc}{tag}"]
        lines += [""]
    return "\n".join(lines)
