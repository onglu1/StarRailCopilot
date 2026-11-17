"""Bounded recovery of one verified MuMu instance through native SRC methods."""
import math
import ntpath
import time
import uuid

from module.config.config import TaskEnd
from module.exception import RequestHumanTakeover


def restart_mumu_instance(device, config, deadline):
    """Restart a verified instance; deadline is an absolute Unix timestamp.

    The caller must persist its recovery allowance before calling. This helper
    neither changes progress nor creates a replacement Device.
    """
    if not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
        raise ValueError('Environment recovery requires a finite deadline')

    def check():
        if config.stop_event is not None and config.stop_event.is_set():
            raise TaskEnd
        if time.time() >= deadline:
            raise TimeoutError('Emulator recovery deadline reached')

    def instance_info():
        check()
        if config.EmulatorInfo_Emulator != 'MuMuPlayer12':
            raise ValueError('Environment recovery requires explicit MuMuPlayer12')
        instance = device.emulator_instance
        if instance is None or instance.type != 'MuMuPlayer12':
            raise ValueError('MuMuPlayer12 instance was not resolved')
        index = instance.MuMuPlayer12_id
        if type(index) is not int or not 0 <= index < 32:
            raise ValueError('Invalid MuMuPlayer12 instance index')
        serial = f'127.0.0.1:{16384 + 32 * index}'
        if not config.Emulator_Serial == device.serial == instance.serial == serial:
            raise ValueError('MuMuPlayer12 serial does not match its instance')
        if not instance.name or instance.name != config.EmulatorInfo_name:
            raise ValueError('MuMuPlayer12 instance name does not match config')
        path = ntpath.normcase(ntpath.normpath(instance.path))
        if not instance.path or not config.EmulatorInfo_path or path != ntpath.normcase(
                ntpath.normpath(config.EmulatorInfo_path)):
            raise ValueError('MuMuPlayer12 executable does not match config')
        return dict(type=instance.type, name=instance.name, path=path,
                    serial=serial, id=index)

    instance = instance_info()
    shared_recovery_blocked = False

    def guard():
        if instance_info() != instance:
            raise ValueError('Emulator recovery target changed')
        if shared_recovery_blocked:
            raise RequestHumanTakeover('Shared ADB recovery is disabled for instance recovery')

    original_wrapper = device._emulator_function_wrapper
    original_list = device.list_device
    original_shell = device.adb_shell
    last_boot_id = None

    def boot_id():
        nonlocal last_boot_id
        guard()
        value = original_shell(['cat', '/proc/sys/kernel/random/boot_id'],
                               timeout=min(10, deadline - time.time()))
        guard()
        if isinstance(value, bytes):
            value = value.decode('ascii')
        value = value.strip()
        parsed = uuid.UUID(value)
        if not parsed.int or str(parsed) != value.lower():
            raise ValueError('Invalid emulator boot_id')
        last_boot_id = str(parsed)
        return last_boot_id

    round_boot_id = None

    # Early MaaTouch init may still populate its cached builder. Finish that
    # work before invalidating resources or wrapping methods it could call.
    init_thread = getattr(device, '_maatouch_init_thread', None)
    while init_thread is not None and init_thread.is_alive():
        guard()
        init_thread.join(timeout=min(0.2, max(0, deadline - time.time())))
        guard()

    def guarded_wrapper(func):
        nonlocal round_boot_id
        guard()  # Outside the native wrapper's broad exception handler.
        if func.__name__ == '_emulator_stop':
            try:
                round_boot_id = boot_id()
            except (TaskEnd, TimeoutError):
                raise
            except Exception:
                round_boot_id = None
                # A failed launch can leave the target absent/offline. Only
                # that explicit observation permits its last confirmed boot
                # as baseline; an unreadable online target remains unproven.
                states = [item.status for item in device.list_device()
                          if item.serial == instance['serial']]
                if not states or all(state == 'offline' for state in states):
                    round_boot_id = last_boot_id
        guard()
        result = original_wrapper(func)
        guard()
        return result

    def guarded_list(*args, **kwargs):
        guard()  # Native startup calls this outside its shell exception block.
        result = original_list(*args, **kwargs)
        guard()
        return result

    def guarded_shell(cmd, *args, **kwargs):
        guard()
        if isinstance(cmd, (list, tuple)) and list(cmd) == ['echo', 'pong']:
            current = boot_id()
            if round_boot_id is None or current == round_boot_id:
                raise ConnectionError('Waiting for a new emulator boot')
        return original_shell(cmd, *args, **kwargs)

    def reconnect_target():
        # Native retry decorators can request reconnection indirectly. Never
        # call their generic reconnect path, which touches other devices.
        guard()
        device.adb_client.disconnect(instance['serial'])
        guard()
        device.adb_client.connect(instance['serial'])
        guard()

    def reject_shared_recovery(*args, **kwargs):
        nonlocal shared_recovery_blocked
        guard()
        shared_recovery_blocked = True
        # The native watch catches shell exceptions; guard keeps this fatal
        # when it reaches its next list/phase boundary.
        raise RequestHumanTakeover('Shared ADB recovery is disabled for instance recovery')

    replacements = dict(_emulator_function_wrapper=guarded_wrapper,
                        list_device=guarded_list, adb_shell=guarded_shell,
                        adb_reconnect=reconnect_target, adb_restart=reject_shared_recovery,
                        adb_start_server=reject_shared_recovery)
    missing = object()
    saved = {name: device.__dict__.get(name, missing) for name in replacements}
    try:
        for name, method in replacements.items():
            setattr(device, name, method)
        guard()
        before_boot_id = boot_id()
        round_boot_id = before_boot_id
        device.release_during_wait()
        guard()
        device.release_resource()
        guard()
        if not device.emulator_start():
            raise ConnectionError('Native emulator restart failed')
        after_boot_id = boot_id()
        if round_boot_id is None or after_boot_id in (before_boot_id, round_boot_id):
            raise ConnectionError('Native restart did not confirm a new emulator boot')
        device.release_resource()
        guard()
        device.stuck_record_clear()
        device.click_record_clear()
        guard()
        return dict(before_boot_id=before_boot_id, after_boot_id=after_boot_id,
                    instance=instance)
    finally:
        for name, method in saved.items():
            if method is missing:
                delattr(device, name)
            else:
                setattr(device, name, method)
