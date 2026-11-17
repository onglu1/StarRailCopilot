"""One recorded environment recovery for a failed, not-yet-started campaign."""
import copy
import json
import time

from module.config.config import TaskEnd
from module.exception import RequestHumanTakeover


MARKER = 'star_preparation_environment_retry'
LOGIN_TIMEOUT = '差分宇宙登录等待超时，准备按恢复次数重试'
WINDOW_SECONDS = 600


def qualifying_login_failure(data, events, now, retries):
    recovery = data.get('recovery') or {}
    if (retries <= 0 or data.get('active') is not None or data.get('phase') != 'error'
            or data.get('error') != LOGIN_TIMEOUT or data.get(MARKER)
            or recovery.get('run_id') is not None or recovery.get('node') is not None
            or recovery.get('action') != 'resume' or recovery.get('attempts', 0) < 2
            or (recovery['attempts'] < retries and now < recovery.get('deadline', 0))):
        return None
    old_pid = data.get('pid')
    if type(old_pid) is not int or old_pid <= 0:
        return None
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        if event.get('event') != 'recovery_exhausted' or event.get('pid') != old_pid:
            continue
        if (event.get('run_id') is not None or event.get('node') is not None
                or event.get('action') != 'resume' or not event.get('session')
                or event.get('attempts') != recovery['attempts']):
            return None
        session = [row for row in events[:index] if row.get('pid') == old_pid
                   and row.get('session') == event['session']]
        fault = next((row for row in reversed(session) if row.get('event') == 'fault'), None)
        login = next((row for row in reversed(session)
                      if row.get('event') in ('login_begin', 'restart_begin')), None)
        if (fault and login and fault.get('error') == LOGIN_TIMEOUT
                and fault.get('run_id') is None and fault.get('node') is None
                and login.get('time', float('inf')) <= fault.get('time', 0) <= event.get('time', 0)
                and not any(row.get('phase') == 'stopped' for row in events[index + 1:])):
            return dict(exhausted=event, fault=fault, login=login)
        return None
    return None


def _event_tail(path):
    with path.open('rb') as stream:
        stream.seek(0, 2)
        start = max(0, stream.tell() - 512 * 1024)
        stream.seek(start)
        lines = stream.read().decode('utf-8', errors='replace').splitlines()
    rows = []
    for line in lines[1:] if start else lines:
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except ValueError:
            continue
    return rows


def preparation_environment_deadline(data):
    marker = data.get(MARKER) or {}
    if data.get('active') is None and marker.get('status') == 'emulator_restarted':
        # Expired is still a deadline, never a reason to grant a fresh window.
        return marker['deadline']
    return None


def retry_preparation_environment(main):
    """Called under the existing controller lock, before normal initialization."""
    if main.config.DivergentUniverse_Mode != 'star' or getattr(main, 'active', None):
        return False
    stop = main.config.stop_event
    if stop is not None and stop.is_set():
        raise TaskEnd
    data = main.progress.data
    if (data.get('active') is not None or data.get('phase') != 'error'
            or data.get('error') != LOGIN_TIMEOUT or data.get(MARKER)):
        return False
    try:
        proof = qualifying_login_failure(data, _event_tail(main.progress.events_path),
                                         time.time(), main.config.DivergentUniverse_RecoveryRetries)
    except OSError:
        return False
    if proof is None:
        return False
    marker = dict(status='attempted', started=time.time(), deadline=time.time() + WINDOW_SECONDS,
                  previous_recovery=copy.deepcopy(data['recovery']), previous_error=data['error'],
                  previous_pid=data.get('pid'), proof=proof, build=main.progress.build,
                  target_serial=main.config.Emulator_Serial,
                  target_name=main.config.EmulatorInfo_name)
    data[MARKER] = marker
    main.progress.save('recovering_environment')
    main.progress.record('preparation_environment_recovery_requested', **copy.deepcopy(marker))
    try:
        from tasks.divergent_universe.environment_recovery import restart_mumu_instance
        observed = restart_mumu_instance(main.device, main.config, marker['deadline'])
    except TaskEnd:
        marker['status'] = 'stopped'
        main.progress.save('stopped')
        raise
    except Exception as error:
        marker.update(status='failed', error=str(error))
        data['error'] = str(error)
        main.progress.save('error')
        main.progress.record('preparation_environment_recovery_failed', error=str(error))
        raise RequestHumanTakeover('模拟器恢复未成功，已保留记录并停止重复重启') from error
    marker.update(status='emulator_restarted', observed=observed)
    main.progress.save('reconnecting')
    main.progress.record('preparation_environment_restarted', **observed)
    return True


def finish_preparation_environment(main):
    data = main.progress.data
    marker = data.get(MARKER) or {}
    active = data.get('active') or {}
    if marker.get('status') == 'emulator_restarted' and active.get('id') and active.get('star'):
        marker.update(status='entry_verified', run_id=active['id'], completed=time.time())
        main.progress.save()
        main.progress.record('preparation_environment_entry_verified', restored_run_id=active['id'])
