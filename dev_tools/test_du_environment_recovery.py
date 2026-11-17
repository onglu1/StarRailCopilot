"""Single-instance native recovery with fake devices and no game I/O."""
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

from module.config.config import TaskEnd
from module.exception import RequestHumanTakeover
from tasks.divergent_universe import environment_recovery as recovery


OLD_BOOT = '11111111-1111-4111-8111-111111111111'
NEW_BOOT = '22222222-2222-4222-8222-222222222222'
THIRD_BOOT = '33333333-3333-4333-8333-333333333333'


class FakeDevice:
    def __init__(self):
        self.serial = '127.0.0.1:16384'
        self.emulator_instance = SimpleNamespace(
            serial=self.serial, type='MuMuPlayer12', name='MuMuPlayer-12.0-0',
            path='C:/MuMu/nx_main/MuMuNxMain.exe', MuMuPlayer12_id=0)
        self.config = SimpleNamespace(
            EmulatorInfo_Emulator='MuMuPlayer12', Emulator_Serial=self.serial,
            EmulatorInfo_name=self.emulator_instance.name,
            EmulatorInfo_path=self.emulator_instance.path, stop_event=threading.Event())
        self.boot = OLD_BOOT
        self.target_status = 'device'
        self.actions = []
        self.after_stop = lambda: None
        self.watch_step = lambda: None
        self.next_boot = NEW_BOOT
        self.native_result = True
        self.on_shell = lambda cmd: None
        self.on_list = lambda: None
        self.adb_client = SimpleNamespace(
            disconnect=lambda serial: self.actions.append(('disconnect', serial)),
            connect=lambda serial: self.actions.append(('connect', serial)))

    def adb_shell(self, cmd, **kwargs):
        self.on_shell(cmd)
        if cmd == ['cat', '/proc/sys/kernel/random/boot_id']:
            if self.target_status != 'device':
                raise ConnectionError('Target is offline')
            return self.boot
        self.actions.append('pong')
        return 'pong'

    def list_device(self):
        self.on_list()
        devices = [SimpleNamespace(serial='127.0.0.1:16416', status='device')]
        if self.target_status is not None:
            devices.append(SimpleNamespace(serial=self.serial, status=self.target_status))
        return devices

    def adb_reconnect(self):
        self.actions.append('generic_reconnect')

    def adb_restart(self):
        self.actions.append('shared_restart')

    def adb_start_server(self):
        self.actions.append('shared_start_server')

    def release_during_wait(self):
        self.actions.append('release_ipc')

    def release_resource(self):
        self.actions.append('release_control')

    def stuck_record_clear(self):
        self.actions.append('clear_stuck')

    def click_record_clear(self):
        self.actions.append('clear_click')

    def _emulator_stop(self, instance):
        self.actions.append('stop')
        self.after_stop()

    def _emulator_start(self, instance):
        self.actions.append('start')
        self.boot = self.next_boot

    def _emulator_function_wrapper(self, func):
        try:
            func(self.emulator_instance)
            return True
        except Exception:
            return False

    def emulator_start(self):
        if not self._emulator_function_wrapper(self._emulator_stop):
            return False
        if not self._emulator_function_wrapper(self._emulator_start):
            return False
        # Model the native watch: list outside catch; shell inside catch.
        for _ in range(3):
            self.list_device()
            try:
                self.adb_shell(['echo', 'pong'])
            except Exception:
                self.watch_step()
                continue
            return self.native_result
        return False


class EnvironmentRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.device = FakeDevice()
        self.now = 1000
        self.clock = patch.object(recovery.time, 'time', lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.original = {name: getattr(self.device, name) for name in
                         ('_emulator_function_wrapper', 'list_device', 'adb_shell',
                          'adb_reconnect', 'adb_restart', 'adb_start_server')}

    def restart(self):
        return recovery.restart_mumu_instance(self.device, self.device.config, 1060)

    def assert_restored(self):
        for name, method in self.original.items():
            self.assertEqual(getattr(self.device, name), method)
            self.assertNotIn(name, self.device.__dict__)

    def test_success_releases_resources_and_restores_methods(self):
        result = self.restart()
        self.assertEqual(result['before_boot_id'], OLD_BOOT)
        self.assertEqual(result['after_boot_id'], NEW_BOOT)
        self.assertEqual(result['instance']['id'], 0)
        self.assertEqual(self.device.actions, ['release_ipc', 'release_control',
                        'stop', 'start', 'pong', 'release_control',
                        'clear_stuck', 'clear_click'])
        self.assert_restored()

    def test_early_maatouch_finishes_before_release_and_honors_stop(self):
        for stop in (False, True):
            with self.subTest(stop=stop):
                self.device = FakeDevice()
                self.original = {name: getattr(self.device, name) for name in self.original}
                thread = SimpleNamespace(alive=True)
                thread.is_alive = lambda: thread.alive
                def join(timeout):
                    self.assertGreater(timeout, 0)
                    self.assertLessEqual(timeout, 0.2)
                    self.assertEqual(self.device.actions, [])
                    self.device.actions.append('thread_finished')
                    thread.alive = False
                    if stop:
                        self.device.config.stop_event.set()
                thread.join = join
                self.device._maatouch_init_thread = thread
                if stop:
                    with self.assertRaises(TaskEnd):
                        self.restart()
                    self.assertEqual(self.device.actions, ['thread_finished'])
                else:
                    self.restart()
                    self.assertFalse(thread.alive)
                    self.assertEqual(self.device.actions[:3],
                                     ['thread_finished', 'release_ipc', 'release_control'])
                self.assert_restored()

    def test_wrong_target_has_no_device_actions(self):
        cases = [('type', 'MuMuPlayerX'), ('serial', '127.0.0.1:16416'),
                 ('name', 'MuMuPlayer-12.0-1'), ('path', 'C:/Other/MuMuNxMain.exe'),
                 ('MuMuPlayer12_id', 1), ('MuMuPlayer12_id', None)]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.device = FakeDevice()
                setattr(self.device.emulator_instance, field, value)
                with self.assertRaises(ValueError):
                    self.restart()
                self.assertEqual(self.device.actions, [])

    def test_explicit_config_and_boot_uuid_required_before_actions(self):
        self.device.config.EmulatorInfo_Emulator = 'auto'
        with self.assertRaises(ValueError):
            self.restart()
        self.assertEqual(self.device.actions, [])
        self.device.config.EmulatorInfo_Emulator = 'MuMuPlayer12'
        self.device.boot = 'not-a-boot-id'
        with self.assertRaises(ValueError):
            self.restart()
        self.assertEqual(self.device.actions, [])

    def test_stop_between_phases_is_not_swallowed(self):
        self.device.after_stop = self.device.config.stop_event.set
        with self.assertRaises(TaskEnd):
            self.restart()
        self.assertNotIn('start', self.device.actions)
        self.assert_restored()

    def test_deadline_between_phases_is_not_swallowed(self):
        self.device.after_stop = lambda: setattr(self, 'now', 1060)
        with self.assertRaises(TimeoutError):
            self.restart()
        self.assertNotIn('start', self.device.actions)
        self.assert_restored()

    def test_unchanged_boot_never_reaches_native_pong_or_success(self):
        self.device.next_boot = OLD_BOOT
        with self.assertRaises(ConnectionError):
            self.restart()
        self.assertNotIn('pong', self.device.actions)
        self.assertNotIn('clear_stuck', self.device.actions)
        self.assert_restored()

    def test_watch_waits_for_changed_boot(self):
        self.device.next_boot = OLD_BOOT
        self.device.watch_step = lambda: setattr(self.device, 'boot', NEW_BOOT)
        self.assertEqual(self.restart()['after_boot_id'], NEW_BOOT)
        self.assertEqual(self.device.actions.count('pong'), 1)
        self.assert_restored()

    def test_deadline_and_stop_escape_native_watch_catch(self):
        for exception, action in ((TimeoutError, lambda: setattr(self, 'now', 1060)),
                                  (TaskEnd, self.device.config.stop_event.set)):
            with self.subTest(exception=exception):
                self.now = 1000
                self.device.next_boot = OLD_BOOT
                self.device.watch_step = action
                with self.assertRaises(exception):
                    self.restart()
                self.assert_restored()

    def test_native_false_is_failure_even_after_new_boot(self):
        self.device.native_result = False
        with self.assertRaises(ConnectionError):
            self.restart()
        self.assertNotIn('clear_stuck', self.device.actions)
        self.assert_restored()

    def test_indirect_reconnect_only_touches_verified_target(self):
        for source in ('first_boot', 'watch_list'):
            with self.subTest(source=source):
                self.device = FakeDevice()
                self.original = {name: getattr(self.device, name) for name in self.original}
                if source == 'first_boot':
                    def shell_retry(cmd):
                        self.device.on_shell = lambda cmd: None
                        self.device.adb_reconnect()
                    self.device.on_shell = shell_retry
                else:
                    self.device.on_list = lambda: self.device.adb_reconnect()
                self.restart()
                transport = [action for action in self.device.actions if isinstance(action, tuple)]
                self.assertEqual(transport, [('disconnect', '127.0.0.1:16384'),
                                             ('connect', '127.0.0.1:16384')])
                self.assertNotIn('generic_reconnect', self.device.actions)
                self.assert_restored()

    def test_indirect_shared_recovery_fails_and_restores_methods(self):
        for name in ('adb_restart', 'adb_start_server'):
            for source in ('first_boot', 'watch_shell'):
                with self.subTest(name=name, source=source):
                    self.device = FakeDevice()
                    self.original = {key: getattr(self.device, key) for key in self.original}
                    def shell_retry(cmd):
                        if source == 'first_boot' or cmd == ['echo', 'pong']:
                            getattr(self.device, name)()
                    self.device.on_shell = shell_retry
                    with self.assertRaises(RequestHumanTakeover):
                        self.restart()
                    self.assertNotIn('shared_restart', self.device.actions)
                    self.assertNotIn('shared_start_server', self.device.actions)
                    self.assertNotIn('clear_stuck', self.device.actions)
                    if source == 'first_boot':
                        self.assertEqual(self.device.actions, [])
                    self.assert_restored()

    def test_native_claim_of_success_cannot_skip_boot_verification(self):
        self.device.emulator_start = lambda: True
        with self.assertRaises(ConnectionError):
            self.restart()
        self.assert_restored()

    def test_second_native_round_uses_its_own_boot_baseline(self):
        def two_rounds():
            for _ in range(2):
                self.device._emulator_function_wrapper(self.device._emulator_stop)
                self.device._emulator_function_wrapper(self.device._emulator_start)
            self.device.list_device()
            self.device.adb_shell(['echo', 'pong'])
            return True
        self.device.emulator_start = two_rounds
        with self.assertRaises(ConnectionError):
            self.restart()
        self.assertNotIn('pong', self.device.actions)
        self.assert_restored()

    def test_second_round_can_restart_explicitly_absent_or_offline_target(self):
        for status in (None, 'offline'):
            with self.subTest(status=status):
                self.device = FakeDevice()
                self.original = {name: getattr(self.device, name) for name in self.original}
                native_start = self.device.emulator_start
                launches = 0
                def launch(instance):
                    nonlocal launches
                    launches += 1
                    self.device.actions.append('start')
                    self.device.target_status = status if launches == 1 else 'device'
                    if launches == 2:
                        self.device.boot = NEW_BOOT
                self.device._emulator_start = launch
                def two_rounds():
                    self.assertFalse(native_start())
                    return native_start()
                self.device.emulator_start = two_rounds
                self.assertEqual(self.restart()['after_boot_id'], NEW_BOOT)
                self.assertEqual(self.device.actions.count('start'), 2)
                self.assertEqual(self.device.actions.count('pong'), 1)
                self.assert_restored()

    def test_online_target_with_unreadable_boot_cannot_reuse_previous_baseline(self):
        for invalid_uuid in (False, True):
            with self.subTest(invalid_uuid=invalid_uuid):
                self.device = FakeDevice()
                self.original = {name: getattr(self.device, name) for name in self.original}
                reads = 0
                def read_failure(cmd):
                    nonlocal reads
                    if cmd != ['cat', '/proc/sys/kernel/random/boot_id']:
                        return
                    reads += 1
                    if reads == 2:
                        if invalid_uuid:
                            self.device.boot = 'invalid-uuid'
                        else:
                            raise ConnectionError('Online target read failed')
                self.device.on_shell = read_failure
                with self.assertRaises(ConnectionError):
                    self.restart()
                self.assertNotIn('pong', self.device.actions)
                self.assertNotIn('clear_stuck', self.device.actions)
                self.assert_restored()

    def test_existing_instance_override_is_restored_exactly(self):
        override = lambda: [self.device.serial]
        self.device.list_device = override
        self.restart()
        self.assertIs(self.device.__dict__['list_device'], override)

    def test_target_change_before_start_is_rejected(self):
        self.device.after_stop = lambda: setattr(self.device, 'serial', '127.0.0.1:16416')
        with self.assertRaises(ValueError):
            self.restart()
        self.assertNotIn('start', self.device.actions)
        self.assert_restored()


if __name__ == '__main__':
    unittest.main()
