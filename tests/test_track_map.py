"""Tests for the GPS-derived track map figure builder."""

import numpy as np
import plotly.graph_objects as go

from app.components.track_map import build_loss_map
from core.telemetry.loss_regions import LossRegion


def _circle_lap(n: int = 360):
    theta = np.linspace(0, 2 * np.pi, n)
    lat = 50.0 + 0.01 * np.sin(theta)
    lon = 5.0 + 0.01 * np.cos(theta)
    distance = np.linspace(0, 7000, n)
    return lat, lon, distance


def test_returns_plotly_figure():
    lat, lon, distance = _circle_lap()
    fig = build_loss_map(lat, lon, distance, regions=[])
    assert isinstance(fig, go.Figure)


def test_loss_regions_get_their_own_traces():
    lat, lon, distance = _circle_lap()
    regions = [
        LossRegion(distance_start=1000.0, distance_end=1500.0, time_lost=0.4),
        LossRegion(distance_start=4000.0, distance_end=4300.0, time_lost=0.2),
    ]
    fig = build_loss_map(lat, lon, distance, regions=regions)
    # 1 base outline trace + 1 trace per region
    assert len(fig.data) == 3


def test_region_trace_labeled_with_time_lost():
    lat, lon, distance = _circle_lap()
    regions = [LossRegion(distance_start=1000.0, distance_end=1500.0,
                          time_lost=0.4)]
    fig = build_loss_map(lat, lon, distance, regions=regions,
                         labels=["Eau Rouge"])
    assert "Eau Rouge" in fig.data[1].name
    assert "0.4" in fig.data[1].name


def test_aspect_ratio_locked():
    lat, lon, distance = _circle_lap()
    fig = build_loss_map(lat, lon, distance, regions=[])
    assert fig.layout.yaxis.scaleanchor == "x"
