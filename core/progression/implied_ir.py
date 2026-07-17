"""PURE roll-up of per-combo implied-iR bands (spec §7).

ALWAYS a band, never a point — bands-not-false-precision is the locked
curve rule. This number informs, it never gates.
"""

from core.progression.models import ComboImplied, DriverImpliedIR


def aggregate_implied_ir(rows: list[ComboImplied]) -> DriverImpliedIR | None:
    """Weighted mean of band midpoints +/- the mean band half-width.

    Weight = the combo's representative-lap count (more practice = more
    signal). Zero total weight degrades to an unweighted mean.
    """
    if not rows:
        return None
    total_w = sum(r.weight for r in rows)
    if total_w > 0:
        mid = sum(((r.implied_lo + r.implied_hi) / 2) * r.weight for r in rows) / total_w
    else:
        mid = sum((r.implied_lo + r.implied_hi) / 2 for r in rows) / len(rows)
    half = sum((r.implied_hi - r.implied_lo) / 2 for r in rows) / len(rows)
    return DriverImpliedIR(
        lo=max(0, round(mid - half)),
        hi=round(mid + half),
        combo_count=len(rows),
    )
