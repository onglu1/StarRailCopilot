"""Explicitly armed, one-shot faults for live DU recovery validation.

No device input is issued here. All recovery and settlement actions remain
owned by the production task. Disabled unless DU_RECOVERY_PROBE is set.
"""
import json
from pathlib import Path
import time


class RecoveryProbeError(RuntimeError):
    pass


def check_recovery_probe(task):
    path = task._recovery_probe_path
    if path is None or not path.exists():
        return
    # Each profile has its own request file, so workers never share a writer.
    request = json.loads(path.read_text(encoding='utf-8'))
    active = task.active
    if (request.get('profile') != task.config.config_name
            or request.get('run_id') != active['id']
            or request.get('node') != active.get('node')
            or time.time() >= request.get('expires_at', 0)
            or not 1 <= request.get('remaining', 0) <= 2):
        return
    if active.get('stop_requested') or active.get('settlement_observed'):
        return
    request['remaining'] -= 1
    request.setdefault('triggered_at', []).append(time.time())
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)
    task.progress.record('recovery_probe_injected', label=request.get('label'),
                         remaining=request['remaining'])
    raise RecoveryProbeError('Explicit live validation: simulated stuck room')


def probe_path(root, directory, profile):
    if not directory:
        return None
    allowed = (Path(root) / 'state' / 'divergent_universe' / 'validation').resolve()
    directory = Path(directory).resolve()
    if directory != allowed:
        raise ValueError('DU_RECOVERY_PROBE must be the package state/divergent_universe/validation directory')
    return directory / f'{profile}.json'
