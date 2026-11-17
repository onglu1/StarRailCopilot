"""Read-only run/decision audit. Never changes checkpoints or infers a win."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tasks.divergent_universe.star_policy import verified_star_rank


def analyze(state_dir, annotations):
    excluded = {r['id']: r['reason'] for r in annotations.get('excluded_runs', [])}
    runs, decisions = [], []
    for profile in ('wly', 'currency'):
        state = json.loads((state_dir / f'{profile}.json').read_text('utf-8'))
        by_id = {}
        for status, rows in (('settled', state['history']), ('unconfirmed', state.get('unconfirmed', [])),
                             ('active', [state['active']] if state.get('active') else [])):
            for run in rows:
                star = run.get('star', {})
                if not star or run['id'] in by_id:
                    continue
                inventory = star.get('equation_inventory', {})
                primary = next(iter(star.get('loadout', {}).get('core_equations', [])), None)
                proof = run.get('execution', {})
                row = dict(profile=profile, id=run['id'], status=status, candidate=star.get('candidate'),
                           threshold=star.get('threshold'), rank_title=star.get('rank_title'),
                           star_rank=star.get('star_rank'), verified_star_rank=verified_star_rank(star),
                           star_rank_evidence=star.get('star_rank_evidence'),
                           result=run.get('result'), node=run.get('node'),
                           started=run.get('started'), finished=run.get('finished'),
                           settlement_observed=run.get('settlement_observed', False),
                           settlement_title=run.get('settlement_title'),
                           exclusion=excluded.get(run['id']),
                           mixed_build=bool(proof.get('disk_changed') or len(proof.get('worker_builds', [])) != 1
                                            or proof.get('policy_corrected_during_run') or proof.get('development_inspection')),
                           policy_signature=star.get('policy_signature'), worker_builds=proof.get('worker_builds', []),
                           members=star.get('members'), primary=primary,
                           last_inventory_node=star.get('inventory_node'), last_path_counts=star.get('path_counts'),
                           last_equation_inventory=inventory,
                           primary_expansion_observed=bool(primary and inventory.get('expansion_evidence') == 'individual_card_marker'
                                                           and primary in inventory.get('visible_expanded_names', [])),
                           weighted_equipment=star.get('weighted_equipment', []),
                           workshops=star.get('workshops', {}), revivals=star.get('revivals', {}),
                           defeat_frame_history=run.get('defeat_frame_history', []))
                by_id[run['id']] = row
                runs.append(row)
        pending = None
        with (state_dir / f'{profile}.events.jsonl').open(encoding='utf-8') as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue  # A concurrent final partial line is not a new event.
                run = by_id.get(event.get('run_id'))
                if not run:
                    continue
                if event['event'] == 'star_choice_candidates':
                    pending = event
                elif event['event'] == 'star_choice' and pending:
                    if (event['run_id'], event.get('kind'), event.get('node')) == (pending['run_id'], pending.get('kind'), pending.get('node')):
                        decisions.append(dict(profile=profile, run_id=run['id'], candidate=run['candidate'],
                                              threshold=run['threshold'], rank_title=run['rank_title'],
                                              star_rank=run['star_rank'], verified_star_rank=run['verified_star_rank'],
                                              exclusion=run['exclusion'], node=event.get('node'),
                                              time=event['time'], chosen=event.get('title'), kind=event.get('kind'),
                                              candidates=pending.get('candidates'), context=pending.get('context'),
                                              policy=pending.get('policy')))
                    pending = None
    groups = defaultdict(list)
    for row in runs:
        if row['threshold'] == 5:
            groups[(row['profile'], row['candidate'])].append(row)
    summary = []
    for (profile, candidate), rows in groups.items():
        eligible = [r for r in rows if r['status'] == 'settled' and not r['exclusion'] and r['settlement_observed']]
        losses = [r for r in eligible if r['result'] == 'loss']
        summary.append(dict(profile=profile, candidate=candidate, observed_runs=len(rows),
                            outcomes=dict(Counter(r['result'] for r in eligible)),
                            excluded=sum(bool(r['exclusion']) for r in rows),
                            loss_nodes=dict(Counter(r['node'] for r in losses)),
                            inventory_missing=sum(not r['last_equation_inventory'] for r in losses),
                            inventory_stale=sum(r['last_inventory_node'] != r['node'] for r in losses),
                            primary_expansion_last_observed=sum(r['primary_expansion_observed'] for r in losses)))
    return dict(generated=datetime.now().isoformat(timespec='seconds'),
                caveats=['protocol5_summary replaces the old x5_summary label: its filter has always been threshold protocol 5, not verified star rank X5.',
                         'Protocol numbers never imply star-rank numbers; legacy records without rank proof stay unverified.',
                         'Historical cross-build outcomes are not a frozen-strategy success rate.',
                         'Missing or old inventory is unknown, not proof of an unexpanded final build.',
                         'Only candidate events followed by a matching confirmed choice are counted.',
                         'Manual-intervention annotations exclude statistical attribution without rewriting history.'],
                protocol5_summary=summary, runs=runs, confirmed_decisions=decisions)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--annotations', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.state_dir, json.loads(args.annotations.read_text('utf-8')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(protocol5_summary=report['protocol5_summary'],
                          compatibility_note=report['caveats'][0],
                          confirmed_decisions=len(report['confirmed_decisions'])), ensure_ascii=False))
