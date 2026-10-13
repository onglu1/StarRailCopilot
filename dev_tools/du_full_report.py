"""Read observed DU events; include all outcomes and subtract only recorded combat."""
import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import statistics


def overlap(intervals, start, end):
    return sum(max(0.0, min(end, right) - max(start, left)) for left, right in intervals)


def analyze_run(rows):
    start = next((r for r in rows if r['event'] == 'run_started'), None)
    ending = next((r for r in reversed(rows) if r['event'] in
                   ('run_finished', 'run_unconfirmed', 'terminal_error', 'recovery_exhausted')), None)
    # A later real settlement supersedes an earlier temporary error event.
    if ending and ending['event'] in ('terminal_error', 'recovery_exhausted'):
        if any(r['time'] > ending['time'] and r['event'] == 'run_resumed' for r in rows):
            ending = None
    combat, combat_start = [], None
    observation_gaps = []
    previous_time = None
    entries = []
    for row in rows:
        if row['event'] == 'session_started' and combat_start is not None:
            # A killed worker may never emit combat_finished. Its replacement
            # must not turn the intervening outage into recorded battle time.
            # Only retain the old interval through its last observed event.
            cutoff = previous_time if previous_time is not None else combat_start
            combat.append((combat_start, cutoff))
            observation_gaps.append((cutoff, row['time']))
            combat_start = None
        if row['event'] == 'phase' and row.get('phase') == 'combat' and combat_start is None:
            combat_start = row['time']
        elif combat_start is not None and (
                row['event'] in ('restart_begin', 'run_finished', 'run_unconfirmed', 'terminal_error')
                or row.get('phase') in ('combat_finished', 'error')):
            combat.append((combat_start, row['time']))
            combat_start = None
        if row['event'] == 'phase' and row.get('phase') == 'node_entered' and row.get('node'):
            if not entries or row['node'] != entries[-1]['node']:
                entries.append(row)
        previous_time = row['time']
    stages = []
    for index, entry in enumerate(entries):
        next_entry = entries[index + 1] if index + 1 < len(entries) else ending
        if next_entry is None:
            continue  # An unfinished room is not a passing sample.
        begin, end = entry['time'], next_entry['time']
        fighting = overlap(combat, begin, end)
        unobserved = overlap(observation_gaps, begin, end)
        duration = end - begin
        stages.append(dict(node=entry['node'], station=entry['station'],
                           started=begin, ended=end, wall_s=round(duration, 3),
                           combat_s=round(fighting, 3), noncombat_s=round(duration - fighting, 3),
                           timing_complete=unobserved == 0,
                           unobserved_combat_gap_s=round(unobserved, 3),
                           over_60s=duration - fighting > 60,
                           ended_by=next_entry['event']))
    restarts, process_resumes = [], []
    for index, row in enumerate(rows):
        if row['event'] not in ('restart_begin', 'session_started'):
            continue
        if row['event'] == 'session_started' and not row.get('node'):
            continue
        following = rows[index + 1:]
        boundary = next((i for i, event in enumerate(following) if event['event'] in (
            'restart_begin', 'session_started', 'restart_failed', 'fault', 'terminal_error',
            'recovery_exhausted', 'run_unconfirmed')),
            len(following))
        following = following[:boundary]
        crossed = next((event for event in following if (
            event['event'] == 'run_finished' and event.get('settlement_observed')) or (
            event['event'] == 'phase' and event.get('phase') == 'node_entered'
            and event.get('node') and (row.get('node') is None or event['node'] > row['node']))), None)
        attempt = dict(time=row['time'], node=row.get('node'),
                       login_completed=any(e['event'] == 'restart_login_complete' for e in following),
                       same_run_progress_observed=crossed is not None,
                       recovered_at=crossed['time'] if crossed else None)
        if row['event'] == 'restart_begin':
            restarts.append(attempt)
        else:
            process_resumes.append(attempt)
    result = ending.get('result') if ending and ending['event'] == 'run_finished' else None
    total = max((r.get('node_total') or 0 for r in rows), default=0)
    covered = {r['node'] for r in entries}
    complete_coverage = bool(total and covered == set(range(1, total + 1)))
    return dict(id=rows[0]['run_id'], builds=sorted({row['build'] for row in rows}),
                started=start['time'] if start else None, start_observed=start is not None,
                finished=ending['time'] if ending else None,
                terminal=ending['event'] if ending else None, result=result,
                settlement_observed=bool(ending and ending.get('settlement_observed')),
                full_node_coverage=complete_coverage, expected_nodes=total,
                full_timing_coverage=complete_coverage and len(stages) == total
                                     and all(s['timing_complete'] for s in stages),
                nodes=stages, restarts=restarts, process_resumes=process_resumes,
                faults=[r for r in rows if r['event'] == 'fault'],
                sessions=len({r['session'] for r in rows}))


def build_report(root, profiles, since):
    report = {'since': since.isoformat(),
              'metric': 'observed node entry to next node or run end, less recorded native combat; recovery time retained; noncombat is an upper bound where timing_complete is false',
              'profiles': {}}
    for profile in profiles:
        path = root / 'state/divergent_universe' / f'{profile}.events.jsonl'
        groups, invalid = defaultdict(list), 0
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    invalid += 1
                    continue
                if row.get('mode') == 'full' and row.get('run_id') and row['time'] >= since.timestamp():
                    groups[row['run_id']].append(row)
        runs = [analyze_run(sorted(rows, key=lambda row: row['time'])) for rows in groups.values()]
        eligible = [r for r in runs if r['start_observed'] and r['terminal']]
        failures = [r for r in eligible if r['result'] != 'win' or not r['settlement_observed']]
        rooms = [s for r in runs for s in r['nodes']]
        times = [s['noncombat_s'] for s in rooms]
        restarts = [e for r in runs for e in r['restarts']]
        resumes = [e for r in runs for e in r['process_resumes']]
        builds = sorted({build for r in runs for build in r['builds']})
        cohorts = []
        for build in builds:
            attempts = [r for r in eligible if r['builds'] == [build]]
            failed = sum(r['result'] != 'win' or not r['settlement_observed'] for r in attempts)
            cohorts.append(dict(build=build, completed_attempts=len(attempts), failures=failed,
                                failure_rate=failed / len(attempts) if attempts else None,
                                full_coverage_wins=sum(r['result'] == 'win' and r['full_node_coverage']
                                                       for r in attempts)))
        report['profiles'][profile] = dict(
            completed_attempts=len(eligible), failures=len(failures),
            failure_rate=len(failures) / len(eligible) if eligible else None,
            full_coverage_wins=sum(r['result'] == 'win' and r['full_node_coverage'] for r in eligible),
            unfinished=sum(r['terminal'] is None for r in runs),
            partial_runs=sum(not r['start_observed'] for r in runs), invalid_event_lines=invalid,
            observed_rooms=len(rooms), rooms_over_60s=sum(s['over_60s'] for s in rooms),
            incomplete_room_timings=sum(not s['timing_complete'] for s in rooms),
            noncombat_p50_s=statistics.median(times) if times else None,
            noncombat_max_s=max(times) if times else None,
            restart_count=len(restarts), restart_progress_count=sum(r['same_run_progress_observed'] for r in restarts),
            process_resume_count=len(resumes),
            process_resume_progress_count=sum(r['same_run_progress_observed'] for r in resumes),
            mixed_build_runs=sum(len(r['builds']) > 1 for r in runs), build_cohorts=cohorts,
            runs=runs)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--profiles', nargs='+', default=['wly', 'currency'])
    parser.add_argument('--since', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.root, args.profiles, datetime.fromisoformat(args.since))
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for profile, result in report['profiles'].items():
        print(profile, json.dumps({k: v for k, v in result.items() if k != 'runs'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
