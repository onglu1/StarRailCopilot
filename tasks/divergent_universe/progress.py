"""Per-profile checkpoints; only a confirmed settlement completes a run."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]


class Progress:
    def __init__(self, profile):
        self.path = ROOT / 'state' / 'divergent_universe' / f'{profile}.json'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'history': [], 'active': None}
        self.events_path = self.path.with_suffix('.events.jsonl')
        self.session_id = uuid.uuid4().hex
        # Capture the loaded worker's source once; later disk deployments must
        # not relabel events produced by an older, still-running worker.
        self.build = self.disk_build()
        self._event_key = None
        self.record('session_started')

    def disk_build(self):
        """Hash only changed source inputs; inspect metadata at checkpoint boundaries."""
        source = Path(__file__).parent
        inputs = []
        for name in ('progress.py', 'divergent_universe.py', 'operator.py', 'selection.py', 'entry.py', 'events.py',
                     'star.py','star_team.py','star_policy.py','star_guides.json','star_catalog.json','star_workshop.py','star_inventory.py','star_shop.py', 'star_revival.py', 'star_effects.py', 'star_combat.py',
                     'preparation_recovery.py', 'environment_recovery.py'):
            inputs.append((name, source / name))
        # Connection initialization is part of restart reliability too.
        # Attribute its fixes to the loaded worker, not an older cohort.
        for relative in ('module/device/connection.py', 'module/logger/error.py', 'dev_tools/du_recovery_probe.py',
                         'tasks/rogue/route/exit.py'):
            inputs.append((relative, source.parent.parent / relative))
        for template in sorted((source / 'templates').glob('*.png')):
            inputs.append(('templates/' + template.name, template))
        stamps = tuple((name, path.stat().st_mtime_ns, path.stat().st_size) for name, path in inputs)
        if stamps != getattr(self, '_disk_stamps', None):
            build = hashlib.sha256()
            for name, path in inputs:
                data = path.read_bytes()
                build.update(name.encode())
                build.update(data if path.suffix == '.png' else data.replace(b'\r\n', b'\n'))
            self._disk_stamps, self._disk_build = stamps, build.hexdigest()
        return self._disk_build

    def observe_execution(self, created=False):
        active = self.data.get('active') or {}
        if active.get('mode') != 'star':
            return
        proof = active.setdefault('execution', dict(tracked_from_start=created, worker_builds=[], disk_changed=False))
        if self.build not in proof['worker_builds']:
            proof['worker_builds'].append(self.build)
        try:
            current = self.disk_build()
        except OSError as error:
            # Source auditing must not restart a healthy game when an editor
            # briefly replaces/locks a file. Retain the sample as unverified.
            proof['disk_changed'] = True
            detail = f'{type(error).__name__}: {error}'
            if proof.get('source_check_error') != detail:
                proof['source_check_error'] = detail
                self.record('star_runtime_source_check_failed', error=detail)
            return
        if current != self.build:
            # A later lazy import can load a different file than startup.
            # Keep the outcome, but do not call this a frozen-version sample.
            proof['disk_changed'] = True
            seen = proof.setdefault('changed_disk_builds', [])
            if current not in seen:
                seen.append(current)
                self.record('star_runtime_source_changed', startup_build=self.build, disk_build=current)

    def record(self, event, **details):
        """Append observed transitions; telemetry never completes a run."""
        active = self.data.get('active') or {}
        row = dict(event=event, time=time.time(), monotonic=time.monotonic(),
                   session=self.session_id, pid=os.getpid(), build=self.build,
                   run_id=active.get('id'), mode=active.get('mode'),
                   calculation=active.get('calculation'), node=active.get('node'),
                   node_total=active.get('node_total'), station=active.get('station'),
                   battles=active.get('battles', 0), selections=active.get('selections', 0))
        row.update(details)
        with self.events_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')

    def save(self, phase=None):
        self.observe_execution()
        self.data.update(pid=os.getpid(), updated=datetime.now().isoformat(timespec='seconds'))
        if phase:
            self.data['phase'] = phase
            if phase != 'error':
                self.data.pop('error', None)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
        # A Windows reader without FILE_SHARE_DELETE can briefly prevent
        # atomic replacement. Retry this I/O, not the game. Keep the complete
        # temporary checkpoint and the same bounded atomic publication.
        retries = 0
        publish_started = time.monotonic()
        while True:
            try:
                temporary.replace(self.path)
                break
            except PermissionError as error:
                if (os.name != 'nt' or getattr(error, 'winerror', None) not in (5, 32)
                        or time.monotonic() - publish_started >= 2):
                    raise
                retries += 1
                # Cooperatively yield to the reader; no fixed gameplay delay.
                import ctypes
                ctypes.windll.kernel32.SwitchToThread()
        if retries:
            self.record('checkpoint_publish_retried', attempts=retries,
                        seconds=time.monotonic() - publish_started)
        active = self.data.get('active') or {}
        key = (active.get('id'), self.data.get('phase'), active.get('node'), active.get('station'),
               active.get('battles'), active.get('selections'))
        if active and key != self._event_key:
            self.record('phase', phase=self.data.get('phase'), error=self.data.get('error'),
                        node_done=active.get('node_done', False),
                        settlement_observed=active.get('settlement_observed', False))
            self._event_key = key

    def begin(self, mode, calculation='periodic'):
        created = self.data['active'] is None
        if self.data['active'] is None:
            self.data['active'] = dict(id=uuid.uuid4().hex, mode=mode, calculation=calculation, battles=0, station='战斗',
                                       started=datetime.now().isoformat(timespec='seconds'), selections=0,
                                       pending_settlement=False)
        else:
            self.data['active'].setdefault('calculation', 'periodic')
        self.observe_execution(created=created)
        self.save('running')
        self.record('run_started' if created else 'run_resumed')
        return self.data['active']

    def finish(self, result):
        active = self.data['active']
        if active:
            if not active.get('settlement_observed'):
                raise RuntimeError('未观察到真实结算，不能完成当前探索记录')
            self.observe_execution()
            self.data['history'].append(dict(active, result=result, finished=datetime.now().isoformat(timespec='seconds')))
            self.record('run_finished', result=result, settlement_observed=True,
                        settlement_confirmed=active.get('settlement_confirmed', False))
        self.data['active'] = None
        self.data.pop('recovery', None)
        self.save('settled')

    def supersede(self, reason):
        """Keep an obsolete checkpoint without inventing a game settlement."""
        active = self.data.get('active')
        if active:
            self.record('run_unconfirmed', reason=reason)
            self.data.setdefault('unconfirmed', []).append(dict(
                active, reason=reason, observed=datetime.now().isoformat(timespec='seconds')))
        self.data['active'] = None
        self.save('checkpoint_superseded')
