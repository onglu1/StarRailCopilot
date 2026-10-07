"""Per-profile checkpoints; only a confirmed settlement completes a run."""
from datetime import datetime
import json
import os
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[2]


class Progress:
    def __init__(self, profile):
        self.path = ROOT / 'state' / 'divergent_universe' / f'{profile}.json'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'history': [], 'active': None}

    def save(self, phase=None):
        self.data.update(pid=os.getpid(), updated=datetime.now().isoformat(timespec='seconds'))
        if phase:
            self.data['phase'] = phase
            if phase != 'error':
                self.data.pop('error', None)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.path)

    def begin(self, mode):
        if self.data['active'] is None:
            self.data['active'] = dict(id=uuid.uuid4().hex, mode=mode, battles=0, station='战斗',
                                       started=datetime.now().isoformat(timespec='seconds'), selections=0,
                                       pending_settlement=False)
        self.save('running')
        return self.data['active']

    def finish(self, result):
        active = self.data['active']
        if active:
            self.data['history'].append(dict(active, result=result, finished=datetime.now().isoformat(timespec='seconds')))
        self.data['active'] = None
        self.save('settled')
