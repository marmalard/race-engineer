"""Deterministic WeekPlan -> markdown. The verdict sentences here are
exact-string pinned; no gating language, ever (v3 §1 hard rule)."""

from datetime import datetime

from core.briefing.render import fmt_lap
from core.weekplan.models import PracticeHalf, RaceHalf, SRCheck, WeekPlan


def headline(plan: WeekPlan) -> str:
    """One-sentence teaser for the Start card and the toast follow-up."""
    if plan.race is None:
        return (
            "Your week plan is ready — no race pick this week, but the "
            "practice half has a job for you."
        )
    return (
        f"Your week plan is ready — {plan.race.series_name} at "
        f"{plan.race.track_name}."
    )


def _slot_line(start_utc: str, fits: bool) -> str:
    local = datetime.fromisoformat(start_utc).astimezone()
    stamp = local.strftime("%a %H:%M")
    return f"- {stamp}" + (" — fits your usual window" if fits else "")


def _race_lines(race: RaceHalf, curve_filled: bool) -> list[str]:
    lines = ["## The race", ""]
    lines.append(
        f"**{race.series_name}** at **{race.track_name}** "
        f"({race.config_name}) in the **{race.car}**."
    )
    if curve_filled and race.implied_ir_lo is not None:
        lines.append(
            f"Your practice best ({fmt_lap(race.prep_best_lap_s)}) is "
            f"running like a {race.implied_ir_lo:,}–"
            f"{race.implied_ir_hi:,} iR driver in this field."
        )
    elif curve_filled:
        lines.append(
            "No practice best at this combo yet — run a few laps and "
            "the verdict fills in."
        )
    else:
        lines.append(
            "The field curve builds after Tuesday night — I'll fill "
            "this in."
        )
    if race.sof_median is not None:
        lines.append(
            f"Field so far: SoF around {race.sof_median:,}, "
            f"~{race.splits_median} split"
            f"{'s' if (race.splits_median or 0) != 1 else ''} per slot."
        )
    if race.race_time_limit is not None:
        lines.append(f"The race costs about {race.race_time_limit} minutes.")
    elif race.race_lap_limit is not None:
        lines.append(f"The race runs {race.race_lap_limit} laps.")
    if race.slots:
        lines.append("")
        lines.append("Next starts (your local time):")
        lines.extend(_slot_line(s.start_utc, s.fits_window)
                     for s in race.slots)
    return lines


def _sr_line(sr: SRCheck) -> str:
    if sr.comfortable:
        return (
            f"SR check: {sr.license_class} {sr.safety_rating:.2f} — "
            f"even a bad night keeps you above the line."
        )
    return (
        f"SR check: {sr.license_class} {sr.safety_rating:.2f} — this is "
        f"the low-stakes week to bank SR. Race anyway, pick the calm slot."
    )


def _practice_lines(practice: PracticeHalf) -> list[str]:
    lines = ["## The practice", ""]
    if practice.kind == "prescription":
        sentence = (
            f"Spend {practice.minutes} minutes in the {practice.combo} — "
            f"it {practice.skill_line}."
        )
        if practice.transfer_line:
            transfer = practice.transfer_line
            sentence += f" {transfer[0].upper()}{transfer[1:]}."
        lines.append(sentence)
    else:
        if practice.goal_label:
            lines.append(
                f"Spend {practice.minutes} minutes at {practice.combo} — "
                f"the last debrief puts the time at {practice.goal_label} "
                f"({practice.goal_fault}, "
                f"{practice.goal_time_lost_s:.1f}s)."
            )
        else:
            lines.append(
                f"Spend {practice.minutes} minutes at {practice.combo} — "
                f"bank laps, the diagnoses will follow."
            )
    if practice.ttp_line:
        lines.append("")
        lines.append(practice.ttp_line)
    return lines


def render_week_plan(plan: WeekPlan) -> str:
    lines: list[str] = [f"# Week Plan — week of {plan.week_start}", ""]
    if plan.race is not None:
        lines.extend(_race_lines(plan.race, plan.curve_filled))
        lines.append("")
    if plan.sr is not None:
        lines.append(_sr_line(plan.sr))
        lines.append("")
    if plan.practice is not None:
        lines.extend(_practice_lines(plan.practice))
        lines.append("")
    if plan.warnings:
        lines.append("")
        lines.extend(f"*{w}*" for w in plan.warnings)
    return "\n".join(lines).strip() + "\n"
