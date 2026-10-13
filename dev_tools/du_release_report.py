"""Audit the first five fresh full runs per profile after a fixed release boundary."""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import statistics

from dev_tools.du_full_report import build_report


def release_report(root, since, build, count=5):
    raw = build_report(root, ('wly', 'currency'), since)
    selected = {}
    for profile, data in raw['profiles'].items():
        # Select by launch order, including unfinished/failed attempts. Never
        # choose the first five successes or slide past an unfavourable run.
        selected[profile] = sorted((r for r in data['runs'] if r['start_observed']),
                                   key=lambda r: r['started'])[:count]
    runs = [r for values in selected.values() for r in values]
    terminal = [r for r in runs if r['terminal']]
    wins = sum(r['terminal'] == 'run_finished' and r['result'] == 'win'
               and r['settlement_observed'] and r['full_node_coverage'] for r in terminal)
    complete = all(len(values) == count and all(r['terminal'] for r in values) for values in selected.values())
    stable = all(r['builds'] == [build] and r['sessions'] == 1 for r in runs)
    rooms = [room for r in terminal for room in r['nodes']]
    timings = [room['noncombat_s'] for room in rooms]
    timing_complete = bool(rooms) and all(room['timing_complete'] for room in rooms)
    # A full win must cover all 13 rooms; an interrupted run still contributes
    # every observed room up to its actual outcome rather than being omitted.
    timing_complete = timing_complete and all(r['result'] != 'win' or r['full_timing_coverage'] for r in terminal)
    ordered = sorted(timings)
    p50 = statistics.median(timings) if timings else None
    p90 = ordered[math.ceil(len(ordered) * .9) - 1] if ordered else None
    probes = []
    ids = {r['id'] for r in runs}
    for profile in selected:
        for line in (root / f'state/divergent_universe/{profile}.events.jsonl').read_text('utf-8').splitlines():
            row = json.loads(line)
            if row.get('run_id') in ids and row['event'] == 'recovery_probe_injected':
                probes.append(row)
    natural = not probes
    speed = timing_complete and p50 <= 60 and p90 <= 120
    passed = complete and stable and natural and wins >= count * 2 - 1 and speed
    return dict(since=since.isoformat(), build=build, runs_per_profile=count,
                selection='first fresh launches after boundary; no exclusions for faults, adventure skips or slow rooms',
                completed=len(terminal), wins=wins, nonwins=len(terminal) - wins,
                complete=complete, same_version_without_worker_reload=stable,
                no_controlled_faults=natural, room_timings_complete=timing_complete,
                observed_rooms=len(rooms), noncombat_p50_s=p50, noncombat_p90_s=p90,
                speed_passed=speed, continuous_run_gate_passed=passed, profiles=selected)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--since', type=datetime.fromisoformat, required=True)
    parser.add_argument('--build', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = release_report(args.root, args.since, args.build)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'profiles'}, ensure_ascii=False, indent=2))
