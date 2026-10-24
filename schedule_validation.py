"""Shared, dependency-free validation for optimizer exports and dashboards."""
import math

TOLERANCE=1e-7


def validate_launch_rate(times, limit, tolerance=TOLERANCE):
    """Validate one slot's half-open rolling intervals [t, t + 1 hour)."""
    if limit<0 or int(limit)!=limit:
        raise ValueError('Maximum launches per hour must be a nonnegative integer')
    ordered=sorted(float(t) for t in times)
    if not all(math.isfinite(t) for t in ordered):
        raise ValueError('Launch times must be finite')
    if limit and any(b-a<1-tolerance for a,b in zip(ordered,ordered[limit:])):
        raise ValueError(f'Launch-rate violation: more than {limit} launches in a rolling hour')


def validate_schedule(rows, limit=0, horizon=None, durations=None, max_slots=None, event_windows=None, blackouts=()):
    lanes={}
    validate_launch_rate([],limit)
    for row in rows:
        start=float(row['start_hour']);end=float(row['end_hour']);slot=int(row['slot'])
        if not (math.isfinite(start) and math.isfinite(end)) or start<-TOLERANCE or end<start-TOLERANCE:
            raise ValueError('Invalid mission launch/completion times')
        if slot<1 or (max_slots is not None and slot>max_slots):raise ValueError('Invalid ship slot')
        if horizon is not None and end>horizon+TOLERANCE:raise ValueError('Mission completes beyond planning horizon')
        if durations is not None and abs(end-start-durations[row['ship']])>TOLERANCE:
            raise ValueError('Mission duration does not match ship data')
        if any(a-TOLERANCE<=start<b-TOLERANCE for a,b in blackouts):
            raise ValueError('Mission launches during a sleep/no-launch interval')
        if event_windows is not None:
            eligible=next((boost for a,b,boost in event_windows if a-TOLERANCE<=start<b-TOLERANCE),None)
            boost=str(row['event_bonus']).lower()=='true'
            if eligible is None or boost!=eligible:raise ValueError('Mission event eligibility does not match actual launch time')
        lanes.setdefault(slot,[]).append((start,end))
    for lane in lanes.values():
        lane.sort()
        validate_launch_rate([start for start,end in lane],limit)
        if any(start<previous_end-TOLERANCE for (_,previous_end),(start,_) in zip(lane,lane[1:])):
            raise ValueError('Schedule contains overlapping missions in one slot')
