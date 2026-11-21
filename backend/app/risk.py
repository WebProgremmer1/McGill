"""The explainable risk engine.

The score is RECOMPUTED from the journey's current conditions every time
(it is never added up across GPS updates). Each rule is independent, adds a
fixed number of points, and explains itself in plain language.

Before any rule runs, GPS readings are filtered for reliability:
  * readings less accurate than `max_accuracy_m` are discarded;
  * readings that imply walking faster than `max_speed_mps` (after allowing for
    both readings' stated GPS error) are discarded as jumps; if several jumps in a
    row land in the same new area, the new area is trusted (the old anchor was wrong);
  * readings with a timestamp equal to the previous reliable one are duplicates;
  * a gap longer than `max_gap_s` between reliable readings breaks the evidence
    chain, so movement rules (off route, stopped, loops) only use the latest
    unbroken stretch of reliable readings.

Off route is scored by DIRECTION: someone taking another street towards the
destination is far less worrying than someone stopped or walking away. Heading
towards it scores by how many minutes the detour adds; sideways, away and
stopped score progressively more.

Loops only count within a recent window and stop counting once she makes clear
progress towards the destination again ("back on track").

All thresholds live in `RiskConfig`; pass your own to override them.

These are experimental navigation heuristics, NOT medical indicators.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from typing import Literal, Sequence

from .geo import distance_to_route_m, haversine_m, route_length_m
from .models import (
    Coordinates, Journey, Place, RiskAssessment, RiskReason, SafeZone, TrackPoint,
)


@dataclass(frozen=True)
class RiskConfig:
    # ---- GPS reliability
    max_accuracy_m: float = 50.0        # worse than this = discarded
    max_speed_mps: float = 4.0          # faster than this between readings = jump
    max_gap_s: float = 120.0            # longer silence breaks the evidence chain
    jump_reset_readings: int = 3        # this many jumps in a row -> trust the new spot

    # ---- off route
    off_route_m: float = 100.0          # distance (minus GPS accuracy) that counts as off
    off_route_updates: int = 3          # consecutive reliable updates needed

    # ---- direction of travel (last couple of minutes)
    heading_window_s: float = 120.0     # how far back to look
    heading_min_span_s: float = 30.0    # need at least this much time to judge
    heading_min_move_m: float = 20.0    # moved less than this = stopped
    toward_ratio: float = 0.5           # >= half of the distance walked brought her closer = toward
    away_ratio: float = 0.3             # >= 30% of it took her farther away = away

    # ---- detour estimate (heading towards the destination off route)
    walking_speed_mps: float = 1.3      # used when the route has no duration
    detour_factor: float = 1.3          # streets vs straight line for the remaining distance
    detour_step_min: float = 5.0        # +points for every this many extra minutes

    # ---- stationary
    stationary_radius_m: float = 25.0
    stationary_min_s: float = 5 * 60    # "more than five minutes"

    # ---- repeated revisits
    revisit_radius_m: float = 30.0      # points this close count as the same place
    revisit_threshold: int = 3          # revisits needed to be "repeated"
    revisit_window_s: float = 15 * 60   # only loops in the last 15 minutes count
    min_progress_m: float = 30.0        # closer than this to the destination = progress
    progress_window_s: float = 5 * 60   # "progress" = last 5 min vs the 5 min before

    # ---- arrival / late
    arrival_radius_m: float = 50.0
    late_grace_s: float = 10 * 60

    # ---- points per rule
    points_safe_zone: int = 15
    points_off_route: int = 25                  # off route, walking sideways / unknown
    points_off_route_toward_min: int = 5        # off route but heading to the destination...
    points_off_route_toward_step: int = 5       # ...+5 per `detour_step_min` extra minutes...
    points_off_route_toward_max: int = 20       # ...up to this
    points_off_route_away: int = 30             # off route and walking away
    points_off_route_stopped: int = 30          # off route and not moving
    points_stationary: int = 15
    points_revisits: int = 25
    points_late: int = 20

    # ---- levels
    medium_min: int = 30
    high_min: int = 60

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if value <= 0:
                raise ValueError(f"RiskConfig.{f.name} must be positive (got {value!r})")
        if self.medium_min >= self.high_min:
            raise ValueError("RiskConfig.medium_min must be below high_min")
        if not (self.points_off_route_toward_min <= self.points_off_route_toward_max
                <= self.points_off_route <= min(self.points_off_route_away,
                                                self.points_off_route_stopped)):
            raise ValueError("Off-route points must grow: toward <= sideways <= away/stopped")


DEFAULT_CONFIG = RiskConfig()


def level_for(score: int, cfg: RiskConfig = DEFAULT_CONFIG) -> str:
    if score >= cfg.high_min:
        return "high"
    if score >= cfg.medium_min:
        return "medium"
    return "low"


def _dist(a: Coordinates, b: Coordinates) -> float:
    return haversine_m(a.latitude, a.longitude, b.latitude, b.longitude)


def _acc(p: TrackPoint) -> float:
    return p.accuracy_m or 0.0


# ------------------------------------------------------------------ GPS filtering
@dataclass
class FilteredTrack:
    reliable: list[TrackPoint]      # every reading that passed the checks
    segment: list[TrackPoint]       # latest unbroken stretch of reliable readings
    discarded: int


def filter_track(track: Sequence[TrackPoint], cfg: RiskConfig = DEFAULT_CONFIG) -> FilteredTrack:
    """Split a time-ordered track into reliable readings and discards."""
    reliable: list[TrackPoint] = []
    segment: list[TrackPoint] = []
    discarded = 0
    jumps_in_a_row = 0
    for p in track:
        if p.accuracy_m is not None and p.accuracy_m > cfg.max_accuracy_m:
            discarded += 1
            continue
        if reliable:
            prev = reliable[-1]
            dt = (p.timestamp - prev.timestamp).total_seconds()
            if dt <= 0:
                discarded += 1
                continue
            allowed = cfg.max_speed_mps * dt + _acc(prev) + _acc(p)
            if _dist(prev, p) > allowed:
                jumps_in_a_row += 1
                if jumps_in_a_row < cfg.jump_reset_readings:
                    discarded += 1
                    continue
                # Several "jumps" in a row: the old anchor was probably the bad
                # reading (or the phone was off). Trust the new spot, new chain.
                segment = []
            elif dt > cfg.max_gap_s:
                segment = []
        jumps_in_a_row = 0
        reliable.append(p)
        segment.append(p)
    return FilteredTrack(reliable, segment, discarded)


# ------------------------------------------------------------------ context
Heading = Literal["toward", "sideways", "away", "stopped"]


@dataclass
class Context:
    """Everything the rules need, independent of the stored Journey model."""
    start: Coordinates
    destination: Place | Coordinates
    route: Sequence[Coordinates]
    expected_arrival: datetime | None
    safe_zones: Sequence[SafeZone]
    now: datetime
    gps: FilteredTrack
    cfg: RiskConfig
    started_at: datetime | None = None
    expected_duration_s: float | None = None
    heading: Heading | None = None
    progress_m: float | None = None
    making_progress: bool | None = None

    @property
    def last(self) -> TrackPoint | None:
        return self.gps.segment[-1] if self.gps.segment else None

    @property
    def fresh(self) -> bool:
        last = self.last
        return last is not None and (self.now - last.timestamp).total_seconds() <= self.cfg.max_gap_s

    @property
    def at_destination(self) -> bool:
        last = self.last
        return self.fresh and last is not None and _dist(last, self.destination) <= self.cfg.arrival_radius_m


# ------------------------------------------------------------------ movement summaries
def _seconds(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds()


def compute_heading(c: Context) -> Heading | None:
    """Which way has she been going over the last `heading_window_s`?

    Compare the straight-line distance she covered with how much closer to the
    destination it brought her: mostly closer = toward, mostly farther = away,
    barely moved = stopped, anything else = sideways. None = not enough data."""
    seg = c.gps.segment
    if len(seg) < 2:
        return None
    last = seg[-1]
    window = [p for p in seg if _seconds(p.timestamp, last.timestamp) <= c.cfg.heading_window_s]
    first = window[0]
    if _seconds(first.timestamp, last.timestamp) < c.cfg.heading_min_span_s:
        return None
    moved = _dist(first, last)
    if moved < c.cfg.heading_min_move_m:
        return "stopped"
    ratio = (_dist(first, c.destination) - _dist(last, c.destination)) / moved
    if ratio >= c.cfg.toward_ratio:
        return "toward"
    if ratio <= -c.cfg.away_ratio:
        return "away"
    return "sideways"


def compute_progress(c: Context) -> tuple[float | None, bool | None]:
    """Is she making real progress towards the destination again?

    Over the last `progress_window_s`: progress_m = how much closer she got.
    It only counts as progress when it is
      * at least `min_progress_m` closer,
      * a fairly direct path (closer by >= `toward_ratio` of the distance walked;
        going round a block covers a lot of ground for little gain), and
      * closer than anywhere she was earlier in the last `revisit_window_s`
        (coming back round to the same corner of a loop is not progress).
    Returns (progress_m, making_progress); (None, None) = too early to tell."""
    seg = c.gps.segment
    if len(seg) < 2:
        return None, None
    cfg, now = c.cfg, seg[-1].timestamp
    older = [i for i, p in enumerate(seg) if _seconds(p.timestamp, now) >= cfg.progress_window_s]
    if not older:
        return None, None
    window = seg[older[-1]:]
    last = window[-1]
    progress = _dist(window[0], c.destination) - _dist(last, c.destination)
    walked = sum(_dist(a, b) for a, b in zip(window, window[1:]))
    earlier = [p for p in seg[:older[-1] + 1]
               if _seconds(p.timestamp, now) <= cfg.revisit_window_s]
    new_best = all(_dist(last, c.destination) < _dist(p, c.destination) for p in earlier)
    making = (progress >= cfg.min_progress_m and walked > 0
              and progress / walked >= cfg.toward_ratio and new_best)
    return progress, making


def estimate_detour_minutes(c: Context) -> float | None:
    """How many minutes longer than planned the whole trip is now likely to take:
    time walked so far + estimated time still needed - the route's planned time."""
    last = c.last
    if last is None or c.started_at is None or not c.route:
        return None
    planned_s = c.expected_duration_s
    length = route_length_m(c.route)
    if not planned_s:
        planned_s = length / c.cfg.walking_speed_mps
    pace = (length / planned_s) if length > 0 and planned_s > 0 else c.cfg.walking_speed_mps
    remaining_s = _dist(last, c.destination) * c.cfg.detour_factor / pace
    elapsed_s = _seconds(c.started_at, c.now)
    return max(0.0, (elapsed_s + remaining_s - planned_s) / 60)


# ------------------------------------------------------------------ rules
def has_arrived(c: Context) -> bool:
    return any(_dist(p, c.destination) <= c.cfg.arrival_radius_m for p in c.gps.reliable)


def _inside(z: SafeZone, p: Coordinates) -> bool:
    return _dist(z, p) <= z.radius_m


def check_safe_zone(c: Context) -> RiskReason | None:
    """Safe zones are small circles around places (e.g. Home, the destination).
    Leaving the zone you START in is expected, so zones containing the start never
    score. A remaining zone scores only if she ARRIVED inside it earlier in the
    journey and the latest reliable position is now outside every such zone."""
    applicable = [z for z in c.safe_zones if not _inside(z, c.start)]
    pts = c.gps.reliable
    if not applicable or len(pts) < 2 or not c.fresh:
        return None
    last = pts[-1]
    if any(_inside(z, last) for z in applicable):
        return None
    if not any(_inside(z, p) for z in applicable for p in pts[:-1]):
        return None
    names = ", ".join(z.name for z in applicable)
    return RiskReason(
        code="left_safe_zone",
        points=c.cfg.points_safe_zone,
        description=f"Arrived at a safe zone ({names}) and then moved outside it.",
    )


def check_off_route(c: Context) -> RiskReason | None:
    n = c.cfg.off_route_updates
    tail = c.gps.segment[-n:]
    if len(tail) < n or not c.route:
        return None
    # Subtract the stated GPS error so a fuzzy reading near the limit doesn't count.
    margins = [distance_to_route_m(p.latitude, p.longitude, c.route) - _acc(p) for p in tail]
    if min(margins) <= c.cfg.off_route_m:
        return None
    cfg = c.cfg
    dist = distance_to_route_m(tail[-1].latitude, tail[-1].longitude, c.route)
    where = f"{dist:.0f} m from the planned route"
    dest = getattr(c.destination, "name", "the destination")
    if c.heading == "toward":
        extra = estimate_detour_minutes(c) or 0.0
        points = min(cfg.points_off_route_toward_max,
                     cfg.points_off_route_toward_min
                     + cfg.points_off_route_toward_step * int(extra // cfg.detour_step_min))
        text = (f"Taking a different way ({where}) but heading towards {dest}; "
                f"about {extra:.0f} min longer than planned.")
    elif c.heading == "away":
        points, text = cfg.points_off_route_away, f"Off the route ({where}) and walking away from {dest}."
    elif c.heading == "stopped":
        points, text = cfg.points_off_route_stopped, f"Off the route ({where}) and not moving."
    else:
        points, text = cfg.points_off_route, f"Off the route ({where}) and not getting closer to {dest}."
    return RiskReason(code="off_route", points=points, description=text)


def check_stationary(c: Context) -> RiskReason | None:
    seg = c.gps.segment
    if len(seg) < 2:
        return None
    last = seg[-1]
    first = last
    for p in reversed(seg[:-1]):
        if _dist(p, last) > c.cfg.stationary_radius_m:
            break
        first = p
    seconds = (last.timestamp - first.timestamp).total_seconds()
    if seconds > c.cfg.stationary_min_s:
        return RiskReason(
            code="stationary",
            points=c.cfg.points_stationary,
            description=(f"Hasn't moved more than {c.cfg.stationary_radius_m:.0f} m "
                         f"for {seconds / 60:.1f} minutes."),
        )
    return None


def find_revisits(track: Sequence[Coordinates], radius_m: float = DEFAULT_CONFIG.revisit_radius_m) -> list[int]:
    """Indices in `track` where the walker came back to a place already visited.

    Idea: remember 'anchor' places (a new anchor is created whenever a GPS point is
    more than `radius_m` from every existing anchor). Each time the walker's current
    anchor changes to one visited before, that is one revisit. Staying put never
    counts. Simply retracing your steps (stepping back to the anchor you were at just
    before the current one, e.g. a single turn-around) is treated as backtracking, not
    a loop; circling a block or pacing back and forth repeatedly still counts."""
    anchors: list[Coordinates] = []
    path: list[int] = []  # anchors in the order walked (backtracking pops)
    current: int | None = None
    revisits: list[int] = []
    for idx, p in enumerate(track):
        best, best_d = None, radius_m
        for i, a in enumerate(anchors):
            d = _dist(p, a)
            if d <= best_d:
                best, best_d = i, d
        if best is None:
            anchors.append(p)
            current = len(anchors) - 1
            path.append(current)
            continue
        if best != current:
            if len(path) >= 2 and path[-2] == best:
                path.pop()  # stepped back along the way we came
            else:
                revisits.append(idx)
                path.append(best)
            current = best
    return revisits


def count_revisits(track: Sequence[Coordinates], radius_m: float = DEFAULT_CONFIG.revisit_radius_m) -> int:
    return len(find_revisits(track, radius_m))


def check_revisits(c: Context) -> RiskReason | None:
    # Only recent movement counts: a loop from half an hour ago is history.
    now = c.gps.segment[-1].timestamp if c.gps.segment else c.now
    seg = [p for p in c.gps.segment if _seconds(p.timestamp, now) <= c.cfg.revisit_window_s]
    hits = find_revisits(seg, c.cfg.revisit_radius_m)
    k = c.cfg.revisit_threshold
    if len(hits) < k:
        return None
    # Back on track: clearly closer in the last few minutes than in the ones before.
    if c.making_progress:
        return None
    # Or: closer now than she ever got before the repeating started.
    window_start = hits[-k]
    before = min(_dist(p, c.destination) for p in seg[:window_start])
    since = min(_dist(p, c.destination) for p in seg[window_start:])
    if before - since >= c.cfg.min_progress_m:
        return None
    return RiskReason(
        code="repeated_revisits",
        points=c.cfg.points_revisits,
        description=(f"Has returned to previously visited locations {len(hits)} times "
                     f"without getting closer to the destination."),
    )


def check_late(c: Context) -> RiskReason | None:
    """Can stay active even when GPS is stale: lateness doesn't need a fresh fix."""
    if c.expected_arrival is None or has_arrived(c):
        return None
    late_by = c.now - c.expected_arrival
    if late_by > timedelta(seconds=c.cfg.late_grace_s):
        return RiskReason(
            code="late_arrival",
            points=c.cfg.points_late,
            description=f"{late_by.total_seconds() / 60:.0f} minutes past expected arrival and not at destination.",
        )
    return None


# ------------------------------------------------------------------ main
def evaluate(
    *,
    track: Sequence[TrackPoint],
    route: Sequence[Coordinates],
    start: Coordinates,
    destination: Place | Coordinates,
    expected_arrival: datetime | None = None,
    safe_zones: Sequence[SafeZone] = (),
    help_requested: bool = False,
    now: datetime | None = None,
    started_at: datetime | None = None,
    expected_duration_s: float | None = None,
    cfg: RiskConfig = DEFAULT_CONFIG,
) -> RiskAssessment:
    """Pure risk evaluation of a time-ordered track. `now` defaults to the newest
    GPS timestamp so recorded journeys replay deterministically."""
    gps = filter_track(track, cfg)
    if now is None:
        now = track[-1].timestamp if track else datetime.now(timezone.utc)
    c = Context(start=start, destination=destination, route=route,
                expected_arrival=expected_arrival, safe_zones=safe_zones,
                now=now, gps=gps, cfg=cfg,
                started_at=started_at or (track[0].timestamp if track else None),
                expected_duration_s=expected_duration_s)
    if c.fresh:
        c.heading = compute_heading(c)
        c.progress_m, c.making_progress = compute_progress(c)
    off_route_now = None

    candidates = [check_late(c)]
    if c.fresh and not c.at_destination:
        # Movement rules need a current, unbroken chain of reliable readings.
        off_route_now = check_off_route(c)
        candidates = [check_safe_zone(c), off_route_now, check_stationary(c),
                      check_revisits(c)] + candidates
    reasons = [r for r in candidates if r is not None]
    detour = estimate_detour_minutes(c) if off_route_now and c.heading == "toward" else None

    score = min(100, sum(r.points for r in reasons))
    level = level_for(score, cfg)
    if help_requested:
        action = "immediate_caregiver_alert"
    else:
        action = {"low": "continue_monitoring", "medium": "contextual_check_in",
                  "high": "caregiver_alert"}[level]
    last = gps.reliable[-1] if gps.reliable else None
    return RiskAssessment(
        score=score,
        level=level,  # type: ignore[arg-type]
        reasons=reasons,
        recommended_action=action,  # type: ignore[arg-type]
        help_requested=help_requested,
        evaluated_at=now,
        data_status="ok" if c.fresh else "insufficient_or_stale",
        arrived=c.at_destination,
        distance_from_route_m=(round(distance_to_route_m(last.latitude, last.longitude, route), 1)
                               if last is not None and route else None),
        accepted_readings=len(gps.reliable),
        discarded_readings=gps.discarded,
        heading=c.heading,
        detour_extra_min=round(detour, 1) if detour is not None else None,
        making_progress=c.making_progress,
        progress_m=round(c.progress_m, 1) if c.progress_m is not None else None,
    )


def assess(j: Journey, cfg: RiskConfig = DEFAULT_CONFIG) -> RiskAssessment:
    return evaluate(
        track=j.track, route=j.route, start=j.start, destination=j.destination,
        expected_arrival=j.expected_arrival, safe_zones=j.safe_zones,
        help_requested=j.help_requested, now=j.reference_time(),
        started_at=j.started_at, expected_duration_s=j.route_duration_s, cfg=cfg,
    )
