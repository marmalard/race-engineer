"""Deterministic RaceNarrative -> markdown.

This is what renders when no AI key is configured, and the factual top
half of the export artifact. Never contains AI text.
"""

from __future__ import annotations

from core.race.models import RaceNarrative


def _fmt_lap_time(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return "-"
    minutes, rest = divmod(seconds, 60.0)
    return f"{int(minutes)}:{rest:06.3f}"


def render_narrative_markdown(
    narrative: RaceNarrative, include_header: bool = True
) -> str:
    """Render the full deterministic narrative as markdown.

    include_header=False drops the H1 + summary lines for embedding in
    the app page, which shows that data in its own header strip; the
    default keeps the standalone/export form unchanged.
    """
    h = narrative.header
    lines: list[str] = []

    if include_header:
        config = f" ({h.track_config})" if h.track_config else ""
        lines.append(f"# Race Debrief — {h.track_name}{config}")
        lines.append("")
        lines.append(
            f"**{h.driver_name}** · {h.car_name} · {h.series_name} · "
            f"{h.session_date} · SoF {h.sof} · {h.field_size} cars"
        )
        lines.append("")
        lines.append(
            f"**P{h.start_position} -> P{h.finish_position}** · "
            f"{h.incidents}x incidents · "
            f"iRating {h.irating_old} -> {h.irating_new} "
            f"({h.irating_new - h.irating_old:+d})"
        )
        lines.append("")

    if narrative.lap1 is not None:
        l1 = narrative.lap1
        lines.append("## Lap 1")
        net = l1.grid_position - l1.position_after_lap1
        verb = "gained" if net > 0 else ("lost" if net < 0 else "held")
        detail = f"{verb} {abs(net)}" if net else "held position"
        lines.append(
            f"Grid P{l1.grid_position} -> P{l1.position_after_lap1} "
            f"after lap 1 ({detail})."
        )
        for c in l1.place_changes:
            where = c.corner_name or f"{c.lap_dist_pct:.0%} around the lap"
            direction = "up to" if c.to_position < c.from_position else "down to"
            lines.append(
                f"- {where}: P{c.from_position} {direction} P{c.to_position}"
            )
        lines.append("")

    if narrative.incidents:
        lines.append("## Incidents")
        for e in narrative.incidents:
            where = e.corner_name or f"{e.lap_dist_pct:.0%} around the lap"
            cost = (
                f", ~{e.time_lost_estimate_s:.1f}s lost (estimate)"
                if e.time_lost_estimate_s > 0
                else ""
            )
            lines.append(
                f"- Lap {e.lap}, {where}: {e.delta_incidents}x "
                f"(P{e.position_before} -> P{e.position_after}{cost})"
            )
        lines.append("")

    lines.append("## Pace")
    if narrative.pace is not None:
        p = narrative.pace
        lines.append(
            f"Best {_fmt_lap_time(p.best_lap)} · "
            f"median clean {_fmt_lap_time(p.median_clean_lap)} · "
            f"{p.clean_lap_count} clean laps"
            + (
                f" · stdev {p.consistency_stdev:.3f}s"
                if p.consistency_stdev is not None
                else ""
            )
        )
        if p.pace_rank is not None:
            lines.append(
                f"Clean-lap pace ranked **P{p.pace_rank}** of "
                f"{p.ranked_drivers} ranked drivers"
                + (
                    f" ({p.unranked_drivers} unranked — too few clean laps)"
                    if p.unranked_drivers
                    else ""
                )
                + "."
            )
    else:
        lines.append("Pace analysis not available (no lap data from the API).")
    lines.append("")

    if narrative.stints:
        lines.append("## Stints")
        for s in narrative.stints:
            trend = ""
            if s.trend_s is not None:
                word = "fading" if s.trend_s > 0 else "improving"
                trend = f", {word} {abs(s.trend_s):.2f}s over the stint"
            lines.append(
                f"- Laps {s.start_lap}-{s.end_lap}: median "
                f"{_fmt_lap_time(s.median_clean_pace)}{trend}"
            )
        lines.append("")

    if narrative.cautions:
        lines.append("## Cautions")
        for c in narrative.cautions:
            span = (
                f"lap {c.start_lap}"
                if c.start_lap == c.end_lap
                else f"laps {c.start_lap}-{c.end_lap}"
            )
            lines.append(f"- Caution: {span}")
        lines.append("")

    if narrative.gaps:
        lines.append("## Key battles")
        for rival in narrative.gaps:
            if not rival.gaps:
                continue
            final = rival.gaps[-1].gap_s
            state = "ahead" if final > 0 else "behind"
            lines.append(
                f"- **{rival.display_name}** (P{rival.finish_position}): "
                f"finished {abs(final):.1f}s {state}"
            )
        lines.append("")

    lines.append("## iRating attribution")
    if narrative.attribution is not None:
        for line in narrative.attribution.summary_lines:
            lines.append(f"- {line}")
    else:
        lines.append("Attribution not available (no official results data).")

    return "\n".join(lines)


def render_export_markdown(
    narrative: RaceNarrative,
    debrief_text: str | None,
    chat_transcript: list[dict] | None = None,
) -> str:
    """The shareable artifact: narrative + AI debrief (+ optional chat)."""
    parts = [render_narrative_markdown(narrative)]
    if debrief_text:
        parts.append("\n---\n\n## Engineer's debrief\n")
        parts.append(debrief_text)
    if chat_transcript:
        parts.append("\n---\n\n## Follow-up\n")
        for msg in chat_transcript:
            speaker = "Driver" if msg["role"] == "user" else "Engineer"
            parts.append(f"**{speaker}:** {msg['content']}\n")
    return "\n".join(parts)
