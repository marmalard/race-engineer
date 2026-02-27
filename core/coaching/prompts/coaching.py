"""Prompt templates for lap coaching synthesis."""

import json

from core.coaching.analyzer import CoachingAnalysis


COACHING_SYSTEM_PROMPT = """\
You are an experienced iRacing coach reviewing a driver's telemetry data. \
You deliver focused, actionable coaching based on structured analysis data. \
You prioritize the 2-3 corners where the most time is available and give \
specific, concrete advice.

Your tone is encouraging but direct. You speak like a real race engineer: \
specific corner names, specific techniques, specific reference points.

IMPORTANT: The corner numbers in the data (corner_number) are sequential \
detection IDs, NOT the official track turn numbers. Each corner includes \
lap_position_percent and distance_from_start fields. Do NOT guess corner \
names — track name knowledge is unreliable and wrong names are worse than \
no names. Instead, describe each corner by its lap position, e.g. \
"the corner at 17% of the lap (1115m from start)". If the data includes a \
"corner_name" field, use that name.

When referencing speeds, convert m/s to km/h or mph as appropriate. \
When referencing distances, use meters. Format your response with markdown \
headers and bullet points for readability."""

COACHING_USER_TEMPLATE = """\
Analyze this session data and provide coaching feedback:

{analysis_json}

Focus on:
1. The top 2-3 corners where the driver is leaving the most time
2. Whether each issue is consistency (they sometimes nail it) or technique \
(they're consistently slow)
3. One specific, actionable thing to try for each priority corner

Keep it under 500 words. Be direct and specific."""


def build_coaching_prompt(analysis: CoachingAnalysis) -> str:
    """Build the user message for a coaching request.

    Serializes the key analysis data into JSON for Claude to interpret.
    Only includes the most relevant data — not raw telemetry arrays.
    """
    # Build a lookup from corner_number to segment data for position info
    corner_segments = {
        c.corner_number: c for c in analysis.segmentation.corners
    }
    track_length = analysis.segmentation.track_length

    priority_data = []
    for pc in analysis.priority_corners:
        seg = corner_segments.get(pc.corner_number)
        entry = {
            "corner_number": pc.corner_number,
            "time_lost_seconds": round(pc.time_lost, 3),
            "issue_type": pc.issue_type,
            "braking_point_delta_meters": round(pc.braking_delta, 1),
            "apex_speed_delta_ms": round(pc.apex_speed_delta, 2),
            "exit_speed_delta_ms": round(pc.exit_speed_delta, 2),
            "throttle_application_delta_meters": round(pc.throttle_delta, 1),
        }
        if seg and track_length > 0:
            entry["distance_from_start_meters"] = round(seg.apex_distance, 0)
            entry["lap_position_percent"] = round(
                seg.apex_distance / track_length * 100, 1
            )
            entry["apex_speed_kmh"] = round(seg.apex_speed * 3.6, 1)
            entry["entry_speed_kmh"] = round(seg.entry_speed * 3.6, 1)
        priority_data.append(entry)

    consistency_data = []
    for ca in analysis.consistency:
        seg = corner_segments.get(ca.corner_number)
        entry = {
            "corner_number": ca.corner_number,
            "mean_time": round(ca.mean_time, 3),
            "std_time": round(ca.std_time, 3),
            "best_time": round(ca.best_time, 3),
            "worst_time": round(ca.worst_time, 3),
            "cv": round(ca.coefficient_of_variation, 3),
            "is_consistency_issue": ca.is_consistency_issue,
            "is_technique_issue": ca.is_technique_issue,
        }
        if seg and track_length > 0:
            entry["lap_position_percent"] = round(
                seg.apex_distance / track_length * 100, 1
            )
        consistency_data.append(entry)

    analysis_payload = {
        "session": {
            "track": analysis.track_name,
            "car": analysis.car_name,
            "total_laps": analysis.lap_count,
            "valid_laps": analysis.valid_lap_count,
            "best_lap_time_seconds": round(analysis.best_lap_time, 3),
            "theoretical_best_seconds": round(analysis.theoretical_best_time, 3),
            "gap_to_theoretical_seconds": round(analysis.gap_to_theoretical, 3),
            "track_length_meters": round(track_length, 0),
        },
        "comparison": {
            "reference_lap": analysis.lap_comparison.reference_lap,
            "comparison_lap": analysis.lap_comparison.comparison_lap,
            "reference_time": round(analysis.lap_comparison.reference_time, 3),
            "comparison_time": round(analysis.lap_comparison.comparison_time, 3),
            "total_delta": round(analysis.lap_comparison.total_time_delta, 3),
        },
        "priority_corners": priority_data,
        "all_corner_consistency": consistency_data,
    }

    analysis_json = json.dumps(analysis_payload, indent=2)
    return COACHING_USER_TEMPLATE.format(analysis_json=analysis_json)
