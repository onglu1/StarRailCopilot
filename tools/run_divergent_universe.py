"""Development entry for the production WebUI task, with session overrides."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument('--config', required=True)
parser.add_argument('--runs', type=int)
parser.add_argument('--mode', choices=['first_station', 'full'])
parser.add_argument('--recovery-retries', type=int)
parser.add_argument('--evidence', action='store_true')
parser.add_argument('--calculation', choices=['standard', 'periodic'])
parser.add_argument('--prepare-only', action='store_true', help='Configure the entry page without starting a run')
parser.add_argument('--difficulty-mode', choices=['current', 'specified', 'highest'])
parser.add_argument('--difficulty', type=int)
parser.add_argument('--pollution-mode', choices=['current', 'specified', 'highest'])
parser.add_argument('--pollution', type=int)
args = parser.parse_args()

from module.config.config import AzurLaneConfig
from module.device.device import Device
from module.logger import set_file_logger
from tasks.divergent_universe.divergent_universe import DivergentUniverse

set_file_logger(args.config)
config = AzurLaneConfig(args.config, task='DivergentUniverse')
overrides = {}
for argument, field in [('runs', 'Runs'), ('mode', 'Mode'), ('recovery_retries', 'RecoveryRetries'),
                        ('calculation', 'Calculation'), ('difficulty_mode', 'DifficultyMode'),
                        ('difficulty', 'Difficulty'), ('pollution_mode', 'PollutionMode'), ('pollution', 'Pollution')]:
    value = getattr(args, argument)
    if value is not None:
        overrides['DivergentUniverse_' + field] = value
if args.evidence:
    overrides['DivergentUniverse_SaveEvidence'] = True
config.override(**overrides)
task = DivergentUniverse(config=config, device=Device(config))
if args.prepare_only:
    task.prepare_entry()
else:
    task.run()
