"""Compatibility for old shutdown frames recorded at a dormant actor clock."""

import json
from copy import deepcopy

from .errors import TrainingRunError


def lifecycle_clock(kind, full_times, run, virtual_time_ms, source_sequence):
    if kind == "STATE" and len(full_times) == 1:
        return next(iter(full_times)), int(run["source_sequence"])
    return virtual_time_ms, source_sequence


def legacy_shutdown_peer(connection, event):
    if event["category"] != "SYSTEM" or event["event_type"] != "SHUTDOWN":
        return None
    projection = json.loads(event["projection_json"])
    times = set()
    for track in projection["tracks"]:
        if track["subscription_tier"] != "FULL":
            continue
        at_time = (track.get("cursor") or {}).get("virtual_time_ms")
        if at_time is None:
            anchor = connection.execute(
                "SELECT a.virtual_time_ms FROM replay_review_event_anchor l "
                "JOIN replay_review_actor_anchor a ON a.run_id=l.run_id AND a.anchor_id=l.anchor_id "
                "WHERE l.run_id=? AND l.timeline_sequence=? AND l.track_id=?",
                (event["run_id"], event["timeline_sequence"], track["track_id"]),
            ).fetchone()
            if anchor is not None:
                at_time = anchor[0]
        if at_time is not None:
            times.add(at_time)
    if len(times) != 1 or next(iter(times)) <= event["virtual_time_ms"]:
        return None
    # Recover frozen rules and time only from the same uninterrupted shutdown
    # group, identical account and view. Never consult newer mutable policies.
    peers = connection.execute(
        "SELECT p.* FROM replay_review_timeline_event p WHERE p.run_id=? "
        "AND p.category='SYSTEM' AND p.event_type='SHUTDOWN' AND p.virtual_time_ms=? "
        "AND p.viewer_revision=? AND NOT EXISTS("
        "SELECT 1 FROM replay_review_timeline_event middle WHERE middle.run_id=p.run_id "
        "AND middle.timeline_sequence BETWEEN MIN(p.timeline_sequence,?) AND MAX(p.timeline_sequence,?) "
        "AND (middle.category<>'SYSTEM' OR middle.event_type<>'SHUTDOWN')) "
        "ORDER BY ABS(p.timeline_sequence-?)",
        (event["run_id"], next(iter(times)), event["viewer_revision"],
         event["timeline_sequence"], event["timeline_sequence"], event["timeline_sequence"]),
    ).fetchall()

    def account_frame(value):
        tracks = deepcopy(value["tracks"])
        for track in tracks:
            # A flat actor's last trade mark can replace its public mark on
            # shutdown without any financial change. Held legs stay strict.
            position = track["position"]
            legs = [position] if position.get("position_mode") != "HEDGE" else [position["long"], position["short"]]
            for leg in legs:
                if leg.get("quantity") == "0":
                    leg.pop("mark_price", None)
        return value["account"], tracks, value["domain"]["equity"], value["viewer_state"]

    baseline = account_frame(projection)
    peer = next((p for p in peers if account_frame(json.loads(p["projection_json"])) == baseline), None)
    if peer is None:
        raise TrainingRunError("REVIEW_LIFECYCLE_SNAPSHOT_UNAVAILABLE",
                               "legacy shutdown lacks an aligned account snapshot; select an earlier review marker",
                               status_code=409)
    return peer


def event_clock(connection, event, *, strict=False):
    try:
        peer = legacy_shutdown_peer(connection, event)
    except TrainingRunError:
        if strict:
            raise
        return event
    return peer if peer is not None else event
