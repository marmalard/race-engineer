"""Two-tier glossary (consumer-UX design-language rule 2).

Tier 1 = iRacing's own vocabulary: used plainly in copy, tooltip only
(spelling out the sim's own words reads as patronizing to members).
Tier 2 = OUR coinages + telemetry domain: plain-language first use per
screen PLUS tooltip — nobody knows what we mean by these until told.

Single source of truth: pages pass help=help_text("SoF") at a term's
first widget/metric per page; the Guide renders the whole dict via
glossary_markdown() (exact-string tested).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Term:
    tier: int  # 1 = platform vocabulary, 2 = product/analysis vocabulary
    help: str


TERMS: dict[str, Term] = {
    # --- Tier 1: iRacing's own vocabulary --------------------------------
    "iRating": Term(1, (
        "iRacing's skill rating — it moves after every official race "
        "based on who you finished ahead of and behind."
    )),
    "SR": Term(1, (
        "Safety Rating — iRacing's incident-based licence metric. "
        "Clean races raise it, contact and off-tracks lower it."
    )),
    "SoF": Term(1, (
        "Strength of Field — the average iRating of the drivers in your "
        "split. Higher SoF = tougher race and bigger rating swings."
    )),
    "split": Term(1, (
        "When enough drivers register, iRacing divides them into splits "
        "by iRating — you only race the drivers in your split."
    )),
    # --- Tier 2: our coinages + telemetry domain --------------------------
    "IBT": Term(2, (
        "iRacing's telemetry file (.ibt). Press Alt+L in the car to "
        "record; files land in Documents\\iRacing\\telemetry."
    )),
    "reference lap": Term(2, (
        "The lap you're compared against — your fastest clean lap for "
        "the combo, or a Garage 61 import when one exists."
    )),
    "clean lap": Term(2, (
        "A racing lap with no incident, no pit visit, and not under "
        "caution — the laps that count when we talk about pace."
    )),
    "representative lap": Term(2, (
        "A clean lap within 110% of your best for the combo — so "
        "out-laps and crawl laps don't pollute your numbers."
    )),
    "pace-deserved position": Term(2, (
        "Where your clean-lap pace alone should have finished you. The "
        "gap between that and your actual finish is what the debrief "
        "digs into."
    )),
    "implied iRating": Term(2, (
        "The iRating whose typical pace matches your lap time at this "
        "track — your speed translated onto the ladder."
    )),
    "practice PB": Term(2, (
        "Your fastest clean, complete practice lap for a combo — "
        "promoted automatically by the telemetry watcher."
    )),
    "prep ledger": Term(2, (
        "What you've actually done at this week's combo: sessions, "
        "clean laps, and how your session best is trending."
    )),
    "Garage 61": Term(2, (
        "A community telemetry service many sim racers run — its lap "
        "exports can serve as reference laps here."
    )),
}


def help_text(name: str) -> str:
    """Tooltip text for a term.

    Raises KeyError on unknown names — a typo in a page should fail a
    test, not ship an empty tooltip.
    """
    return TERMS[name].help


def glossary_markdown() -> str:
    """The Guide's glossary section, generated from TERMS."""
    tier1 = [n for n, t in TERMS.items() if t.tier == 1]
    tier2 = [n for n, t in TERMS.items() if t.tier == 2]
    lines = ["**iRacing's words** (the sim's own vocabulary):", ""]
    lines += [f"- **{n}** — {TERMS[n].help}" for n in tier1]
    lines += ["", "**Our words** (what Race Engineer means by them):", ""]
    lines += [f"- **{n}** — {TERMS[n].help}" for n in tier2]
    return "\n".join(lines)
