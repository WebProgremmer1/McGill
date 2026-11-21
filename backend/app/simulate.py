"""Replay the bundled journeys in simulations/*.json through the stateless analyzer.

Run from the backend folder:  python -m app.simulate
No Google key or running server needed.
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import AnalyzeRequest, TrackPoint
from .risk import evaluate

SIM_DIR = Path(__file__).resolve().parent.parent / "simulations"


def analyze_file(path: Path):
    req = AnalyzeRequest.model_validate(json.loads(path.read_text()))
    track = [TrackPoint(latitude=r.latitude, longitude=r.longitude, timestamp=r.timestamp,
                        accuracy_m=r.accuracy_meters) for r in req.gps_history]
    route = req.expected_route
    return req, evaluate(track=track, route=route, start=route[0],
                         destination=req.destination or route[-1],
                         expected_arrival=req.expected_arrival, safe_zones=req.safe_zones,
            started_at=req.started_at, expected_duration_s=req.expected_duration_s,
                         now=req.now)


if __name__ == "__main__":
    for path in sorted(SIM_DIR.glob("*.json")):
        req, risk = analyze_file(path)
        why = "; ".join(r.description for r in risk.reasons) or "no concern signals"
        print(f"{req.journey_id or path.stem:<20} {risk.score:>3} {risk.level:<6} "
              f"data={risk.data_status:<22} arrived={risk.arrived!s:<5} {why}")
