"""Atomic accounting shared by multiple SRC emulator workers."""
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import random
import uuid
from filelock import FileLock
from tasks.currency_wars.paths import STATE_DIR


class Campaign:
    def __init__(self, path=None, profile='currency'):
        self.path = Path(path) if path else STATE_DIR / 'currency_progress.json'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.profile = profile
        self.lock = FileLock(str(self.path) + '.lock', timeout=10)
        self.reload()

    def reload(self):
        self.data = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {
            'created': datetime.now().isoformat(timespec='seconds'),
            'settlements': [], 'active': {}, 'workers': {}, 'random_bag': [], 'seen_strategies': [],
        }
        if not isinstance(self.data.get('active'), dict):
            self.data['active'] = {}
        self.data.setdefault('workers', {})
        # Old acceptance counters must never limit normal scheduled runs.
        self.data.pop('target', None)
        self.data.pop('validation_complete', None)

    @property
    def completed(self):
        return len(self.data['settlements'])

    def _write(self):
        self.data['updated'] = datetime.now().isoformat(timespec='seconds')
        temporary = self.path.with_name(self.path.name + f'.{os.getpid()}.tmp')
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.path)

    def save(self):
        with self.lock:
            self._write()

    def begin(self, mode, strategy=None):
        with self.lock:
            self.reload()
            active = self.data['active'].get(self.profile)
            if active is None:
                active = {'id': uuid.uuid4().hex, 'profile': self.profile, 'mode': mode, 'strategy': strategy,
                          'started': datetime.now().isoformat(timespec='seconds')}
                self.data['active'][self.profile] = active
            self.data['phase'] = 'running'
            self.data['workers'][self.profile] = {'pid': os.getpid(), 'phase': 'running', 'updated': datetime.now().isoformat(timespec='seconds')}
            self._write()
            return dict(active)

    def heartbeat(self, phase, stage=None, error=None):
        with self.lock:
            self.reload()
            worker = self.data['workers'].setdefault(self.profile, {})
            worker.update(pid=os.getpid(), phase=phase, updated=datetime.now().isoformat(timespec='seconds'))
            if stage:
                worker['stage'] = stage
            if error:
                worker['error'] = str(error)
            self._write()

    def set_strategy(self, strategy, request=None):
        with self.lock:
            self.reload()
            active = self.data['active'].get(self.profile)
            if active is not None:
                if (active.get('strategy') != strategy
                        or request is not None and active.get('strategy_request', request) != request):
                    active.pop('strategy_applied', None)
                    active.pop('star_plan', None)
                active['strategy'] = strategy
                if request is not None:
                    active['strategy_request'] = deepcopy(request)
                    if request.get('source') != 'sequence':
                        active.pop('sequence', None)
                title = strategy.get('title') if isinstance(strategy, dict) else strategy
                if title and title not in self.data['seen_strategies']:
                    self.data['seen_strategies'].append(title)
                self._write()

    def mark_strategy_applied(self):
        with self.lock:
            self.reload()
            active = self.data['active'].get(self.profile)
            if active is not None:
                active['strategy_applied'] = True
                self._write()

    def ensure_star_plan(self, proposal):
        """A takeover restores the original cultivation plan for this run."""
        with self.lock:
            self.reload()
            active = self.data['active'].get(self.profile)
            if active is None:
                return deepcopy(proposal)
            saved = active.get('star_plan')
            if saved and saved.get('version') == proposal['version'] and set(saved['targets']) == set(proposal['targets']):
                return deepcopy(saved)
            active['star_plan'] = deepcopy(proposal)
            self._write()
            return deepcopy(proposal)

    def set_mode(self, mode):
        with self.lock:
            self.reload()
            active = self.data['active'].get(self.profile)
            if active is not None:
                active['mode'] = mode
                if active.get('pending_settlement'):
                    active['pending_settlement']['mode'] = mode
                self._write()

    def _normalize_settlement(self, record, active=None, run_id=None):
        record = deepcopy(record)
        record['id'] = run_id or (active['id'] if active else record.get('id', uuid.uuid4().hex))
        record['profile'] = self.profile
        if active and active['id'] == record['id']:
            record.setdefault('mode', active['mode'])
            if active.get('strategy_applied'):
                record['strategy_imported'] = True
            if active.get('star_plan'):
                record.setdefault('star_plan', deepcopy(active['star_plan']))
            if active.get('strategy_applied') and active.get('strategy_request', {}).get('source') == 'sequence':
                record.setdefault('sequence', deepcopy(active.get('sequence')))
        return record

    def stage_settlement(self, record):
        """Save the result before leaving settlement; it is not counted yet."""
        with self.lock:
            self.reload()
            active = self.data['active'].get(self.profile)
            if active is None:
                return None
            pending = dict(active.get('pending_settlement') or {})
            pending.update(record)
            pending = self._normalize_settlement(pending, active, run_id=active['id'])
            active['pending_settlement'] = pending
            self._write()
            return deepcopy(pending)

    def pending_settlement(self):
        with self.lock:
            self.reload()
            active = self.data['active'].get(self.profile)
            return deepcopy(active.get('pending_settlement')) if active else None

    def complete_pending_settlement(self):
        """Count the saved result once, after the caller confirms the home page."""
        with self.lock:
            self.reload()
            active = self.data['active'].get(self.profile)
            pending = active.get('pending_settlement') if active else None
            if pending is None:
                return None
            return self._settle_record(pending, run_id=pending['id'])

    def _settle_record(self, record, run_id=None):
        active = self.data['active'].get(self.profile)
        record = self._normalize_settlement(record, active, run_id)
        saved = next((item for item in self.data['settlements'] if item['id'] == record['id']), None)
        if saved is None:
            self.data['settlements'].append(record)
            saved = record
            step = record.get('sequence')
            sequence = self.data.get('sequences', {}).get(self.profile)
            if step and sequence and sequence == step:
                sequence['index'] = (sequence['index'] + 1) % len(sequence['codes'])
                if sequence['index'] == 0:
                    sequence['cycle'] += 1
        if active and active['id'] == record['id']:
            self.data['active'].pop(self.profile, None)
        self.data['phase'] = 'running' if self.data['active'] else 'idle'
        self.data['workers'][self.profile] = {'pid': os.getpid(), 'phase': 'between_games', 'updated': datetime.now().isoformat(timespec='seconds')}
        self._write()
        return deepcopy(saved)

    def settle(self, record, run_id=None):
        with self.lock:
            self.reload()
            return self._settle_record(record, run_id)

    def choose(self, candidates, remember=True):
        if not candidates:
            raise ValueError('No strategies available for random selection')
        with self.lock:
            self.reload()
            bag = [item for item in self.data['random_bag'] if item in candidates]
            if not bag:
                bag = list(dict.fromkeys(candidates))
                random.SystemRandom().shuffle(bag)
            chosen = bag.pop()
            self.data['random_bag'] = bag
            if remember and chosen not in self.data['seen_strategies']:
                self.data['seen_strategies'].append(chosen)
            self._write()
            return chosen

    def sequence_choice(self, codes):
        """Reserve this profile's current item; only settlement advances it."""
        if not codes:
            raise ValueError('顺序攻略列表不能为空')
        with self.lock:
            self.reload()
            active = self.data['active'].get(self.profile)
            if active is None:
                raise RuntimeError('选择顺序攻略前需要建立当前对局')
            sequences = self.data.setdefault('sequences', {})
            sequence = sequences.get(self.profile)
            if sequence is None or sequence['codes'] != codes:
                sequence = {'codes': list(codes), 'index': 0, 'cycle': 0}
                sequences[self.profile] = sequence
            step = active.get('sequence')
            if step is None or step['codes'] != codes:
                step = deepcopy(sequence)
                active['sequence'] = step
            self._write()
            return codes[step['index']], deepcopy(step)
