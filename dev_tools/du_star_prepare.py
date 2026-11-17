"""Run the production star-entry preparer under the profile controller lock."""
import argparse
import json
import time
from pathlib import Path

from filelock import FileLock

from module.config.config import AzurLaneConfig
from module.logger import set_file_logger
from tasks.currency_wars.paths import STATE_DIR
from tasks.divergent_universe.divergent_universe import DivergentUniverse
from tasks.divergent_universe.progress import Progress
from tasks.divergent_universe.star import StarPreparation


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', required=True)
    parser.add_argument('--page', choices=('entry', 'guides', 'import', 'import-guide', 'settle-setup', 'team', 'scan-team', 'team-filter', 'set-team', 'verify-team','run-guide','workshop','progression','inventory','curios','traits-inspect','trailblazer-details','trailblazer-path','path-selector','set-memory-path'), default='entry')
    parser.add_argument('--candidate', choices=('phainon', 'followup', 'aglaea', 'dot'))
    parser.add_argument('--expected-run')
    parser.add_argument('--settle-reason',choices=('replace_unverified_star_setup','replace_star_candidate'),
                        default='replace_unverified_star_setup')
    args = parser.parse_args()
    config = AzurLaneConfig(args.profile, task='DivergentUniverse')
    set_file_logger(name=args.profile + '_star_prepare')
    with FileLock(str(STATE_DIR / f'{args.profile}.controller.lock'), timeout=0):
        if args.page == 'traits-inspect':
            from tasks.divergent_universe.star_traits import inspect_traits
            result = inspect_traits(config, Progress(args.profile), args.expected_run)
            print(json.dumps(result, ensure_ascii=False))
            raise SystemExit(0)
        main = DivergentUniverse(config=config, task='DivergentUniverse')
        main.progress = Progress(args.profile)
        main._initialize()
        # This bounded setup inspects entry settings only. A prior failed
        # exploration's expired retry deadline does not govern menu setup.
        # Its checkpoint/recovery/history are not cleared or completed here.
        main.op.deadline = time.monotonic() + (360 if args.page in ('settle-setup', 'set-team') else 180)
        preparation = StarPreparation(main)
        def selected_guide():
            if not args.candidate:
                raise ValueError('--candidate is required for guide import')
            path = Path(__file__).resolve().parents[1] / 'tasks/divergent_universe/star_guides.json'
            guide = next(g for g in json.loads(path.read_text('utf-8'))['guides'] if g['key'] == args.candidate)
            return guide
        def scan_team():
            from tasks.divergent_universe.star_team import StarTeam
            return StarTeam(preparation).inspect_candidates(selected_guide())
        def inspect_filter():
            from tasks.divergent_universe.star_team import StarTeam
            return StarTeam(preparation).inspect_filter()
        def set_team():
            from tasks.divergent_universe.star_team import StarTeam
            return StarTeam(preparation).set_team(selected_guide())
        def verify_team():
            from tasks.divergent_universe.star_team import StarTeam
            return StarTeam(preparation).verify_team(selected_guide())
        def trailblazer_details():
            from tasks.divergent_universe.star_team import StarTeam
            return StarTeam(preparation).inspect_trailblazer_details()
        def trailblazer_path():
            from tasks.divergent_universe.star_team import StarTeam
            return StarTeam(preparation).inspect_trailblazer_path()
        def path_selector():
            from tasks.divergent_universe.star_team import StarTeam
            return StarTeam(preparation).inspect_path_selector()
        def set_memory_path():
            from tasks.divergent_universe.star_team import StarTeam
            return StarTeam(preparation).change_to_remembrance()
        def workshop():
            from tasks.divergent_universe.star_workshop import StarWorkshop
            main.op.snapshot()
            return StarWorkshop(main).handle()
        def curios():
            from tasks.divergent_universe.star_inventory import StarInventory
            return StarInventory(main).inspect_curios()
        action = {'entry': preparation.open_entry, 'guides': preparation.open_guides,
                  'import': preparation.open_import, 'import-guide': lambda: preparation.import_guide(selected_guide()),
                  'team': preparation.open_team, 'scan-team': scan_team,
                  'team-filter': inspect_filter,
                  'set-team': set_team,
                  'verify-team': verify_team,
                  'run-guide':preparation.open_run_guide,'workshop':workshop,'progression':preparation.inspect_progression,'inventory':preparation.inspect_run_inventory,'curios':curios,
                  'trailblazer-details':trailblazer_details,
                  'trailblazer-path':trailblazer_path,
                  'path-selector':path_selector,
                  'set-memory-path':set_memory_path,
                  'settle-setup': lambda: preparation.settle_unverified_setup(args.expected_run,args.settle_reason)}[args.page]
        result = action()
        print(json.dumps(result, ensure_ascii=False))
