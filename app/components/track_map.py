"""GPS-derived track map with loss regions colored by time lost.

Display-only component (no analysis logic): takes lat/lon/distance
arrays plus LossRegions and returns a Plotly figure. The official
SVG maps (track_assets) are for briefings; this GPS outline is for
debriefs, where loss spans must be projected onto track position.
"""

import numpy as np
import plotly.graph_objects as go

from core.telemetry.loss_regions import LossRegion

# Reds from deep red to amber, most time lost = darkest
_REGION_COLORS = ["#d62728", "#ff7f0e", "#ffbf00"]


def build_loss_map(
    lat: np.ndarray,
    lon: np.ndarray,
    distance: np.ndarray,
    regions: list[LossRegion],
    labels: list[str] | None = None,
) -> go.Figure:
    """Track outline (grey) with each loss region overlaid in color.

    Args:
        lat: Latitude array aligned to the distance grid.
        lon: Longitude array aligned to the distance grid.
        distance: Distance-from-start array in meters.
        regions: Loss regions to highlight (from find_loss_regions).
        labels: Optional corner/region names, one per region.

    Returns:
        Plotly Figure with a grey track outline and colored region traces.
        Aspect ratio is locked so the track shape is not distorted.
    """
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=lon, y=lat, mode="lines",
        line={"color": "#888", "width": 2},
        name="Track", hoverinfo="skip",
    ))

    for i, region in enumerate(regions):
        mask = (distance >= region.distance_start) & (
            distance <= region.distance_end
        )
        label = labels[i] if labels and i < len(labels) else f"Region {i + 1}"
        fig.add_trace(go.Scatter(
            x=lon[mask], y=lat[mask], mode="lines",
            line={"color": _REGION_COLORS[i % len(_REGION_COLORS)], "width": 6},
            name=f"{label} (+{region.time_lost:.1f}s)",
        ))

    fig.update_layout(
        xaxis={"visible": False},
        yaxis={"visible": False, "scaleanchor": "x"},
        showlegend=True,
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        height=420,
    )
    return fig
