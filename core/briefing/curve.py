"""PURE pace-vs-iRating curve math. No I/O, no API types.

Input points are (irating, best_lap_s) per driver per subsession.
Medians are made monotone (running min as iR rises) before implied-iR
interpolation so one slow bin cannot invert the mapping.
"""

from statistics import median

from core.briefing.models import CurveBin, CurvePlacement, PaceCurve

BIN_WIDTH = 250  # iRating per bin
MIN_BIN_N = 5  # bins thinner than this merge into their lower neighbor


def build_curve(
    points: list[tuple[int, float]],
    subsessions_used: int,
    capped: bool,
) -> PaceCurve:
    """Bin (iR, lap) points into BIN_WIDTH bins with >= MIN_BIN_N each."""
    clean = [(ir, lap) for ir, lap in points if ir > 0 and lap > 0]
    raw_bins: dict[int, list[float]] = {}
    for ir, lap in clean:
        raw_bins.setdefault(ir // BIN_WIDTH, []).append(lap)

    merged: list[tuple[int, int, list[float]]] = []  # (lo_key, hi_key, laps)
    for key in sorted(raw_bins):
        laps = raw_bins[key]
        if merged and len(merged[-1][2]) < MIN_BIN_N:
            lo, _, prev = merged[-1]
            merged[-1] = (lo, key, prev + laps)
        else:
            merged.append((key, key, laps))
    # A trailing sparse bin merges backward into its lower neighbor.
    if len(merged) >= 2 and len(merged[-1][2]) < MIN_BIN_N:
        lo, _, prev = merged[-2]
        _, hi, last = merged[-1]
        merged[-2] = (lo, hi, prev + last)
        merged.pop()

    bins = [
        CurveBin(
            ir_lo=lo * BIN_WIDTH,
            ir_hi=(hi + 1) * BIN_WIDTH - 1,
            median_lap_s=median(laps),
            n=len(laps),
        )
        for lo, hi, laps in merged
        if len(laps) >= MIN_BIN_N or len(merged) == 1
    ]
    return PaceCurve(
        bins=bins, points=clean, subsessions_used=subsessions_used, capped=capped
    )


def _monotone_medians(bins: list[CurveBin]) -> list[tuple[int, float]]:
    """(ir_center, median) with running-min medians as iR rises."""
    out: list[tuple[int, float]] = []
    lowest = float("inf")
    for b in bins:
        lowest = min(lowest, b.median_lap_s)
        out.append((b.ir_center, lowest))
    return out


def smoothed_medians(
    curve: PaceCurve, window: int = 1
) -> list[tuple[int, float]]:
    """n-weighted moving average of bin medians (+/- window bins), for
    DISPLAY only. Sparse high-iR bins make the raw median line jumpy
    (founder smoke-test feedback 2026-07-15); weighting by bin population
    lets thin bins lean on their heavy neighbors. Placement math (the
    verdict) stays on the raw monotone medians - cosmetic smoothing must
    never move the verdict."""
    bins = curve.bins
    out: list[tuple[int, float]] = []
    for i, b in enumerate(bins):
        lo = max(0, i - window)
        hi = min(len(bins), i + window + 1)
        weight = sum(x.n for x in bins[lo:hi])
        value = sum(x.median_lap_s * x.n for x in bins[lo:hi]) / weight
        out.append((b.ir_center, value))
    return out


def place_on_curve(
    curve: PaceCurve, lap_s: float, user_ir: int | None
) -> CurvePlacement:
    """Interpolate lap_s onto the monotone median curve -> implied-iR band."""
    if not curve.bins or lap_s <= 0:
        return CurvePlacement(
            lap_s=lap_s,
            implied_ir_lo=None,
            implied_ir_hi=None,
            delta_to_own_band_s=None,
        )
    pts = _monotone_medians(curve.bins)
    half = BIN_WIDTH // 2

    if lap_s <= pts[-1][1]:  # faster than the fastest bin median
        implied = pts[-1][0]
        implied_hi = implied + half
    elif lap_s >= pts[0][1]:  # slower than the slowest bin median
        implied = pts[0][0]
        implied_hi = implied + half
    else:
        implied = pts[0][0]
        for (ir_a, lap_a), (ir_b, lap_b) in zip(pts, pts[1:]):
            if lap_b <= lap_s <= lap_a:
                span = lap_a - lap_b
                frac = 0.0 if span <= 0 else (lap_a - lap_s) / span
                implied = int(ir_a + frac * (ir_b - ir_a))
                break
        implied_hi = implied + half

    delta = None
    if user_ir is not None:
        own = min(curve.bins, key=lambda b: abs(b.ir_center - user_ir))
        delta = lap_s - own.median_lap_s
    return CurvePlacement(
        lap_s=lap_s,
        implied_ir_lo=max(0, implied - half),
        implied_ir_hi=implied_hi,
        delta_to_own_band_s=delta,
    )
