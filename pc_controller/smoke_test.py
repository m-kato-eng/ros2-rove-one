"""PC -> SSH -> ROS -> virtual motors -> PC feedback acceptance tests."""
import queue
import time

from transport import Connection


def main():
    connection = Connection(log_name='pc-smoke-events.jsonl', dry_run=True)
    events = []

    def pump():
        while True:
            try:
                events.append(connection.events.get_nowait())
            except queue.Empty:
                break

    def wait_for(predicate, vector=(0.0, 0.0), heartbeat=True, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pump()
            if connection.ready and heartbeat:
                connection.drive(*vector)
            if predicate():
                return
            if connection.process is not None and connection.process.poll() is not None:
                raise AssertionError('SSH exited: ' + str(events[-6:]))
            time.sleep(0.07)
        raise AssertionError('Timed out: ' + str(events[-6:]))

    def state(predicate, vector=(0.0, 0.0), heartbeat=True, timeout=8):
        marker = time.monotonic()
        wait_for(lambda: connection.status_at > marker and predicate(connection.status),
                 vector, heartbeat, timeout)
        assert connection.status['dry_run'] is True
        return connection.status

    def request(op, value, expected=True):
        connection.drive()
        identifier = connection.request(op, value)
        wait_for(lambda: any(e.get('type') == 'response' and e.get('id') == identifier for e in events))
        response = next(e for e in events if e.get('type') == 'response' and e.get('id') == identifier)
        assert response['ok'] is expected, response

    def zero(status):
        return all(value == 0 for value in status['duties'].values())

    try:
        connection.connect()
        wait_for(lambda: connection.ready, timeout=30)
        state(lambda s: not s['enabled'] and zero(s))
        print('PASS PC SSH startup: GPIO-free and disabled', flush=True)
        request('enable', True)
        state(lambda s: s['enabled'] and all(v > 0 for v in s['duties'].values()), (0.1, 0))
        print('PASS PC forward -> ROS -> four virtual motors -> feedback', flush=True)
        state(lambda s: s['enabled'] and all(v < 0 for v in s['duties'].values()), (-0.1, 0))
        print('PASS PC reverse', flush=True)
        state(lambda s: s['duties']['left_front'] < 0 < s['duties']['right_front'], (0, 0.6))
        print('PASS PC turn', flush=True)
        state(lambda s: s['enabled'] and zero(s))
        print('PASS PC release to zero', flush=True)
        for motor in ('left_front', 'left_rear', 'right_front', 'right_rear'):
            for speed in (0.1, -0.1):
                deadline = time.monotonic() + 0.7
                while time.monotonic() < deadline:
                    connection.wheel(motor, speed)
                    if (connection.status and connection.status['enabled'] and
                            all((value * speed > 0) if name == motor else value == 0
                                for name, value in connection.status['duties'].items())):
                        break
                    time.sleep(0.05)
                else:
                    raise AssertionError('wheel command failed: ' + motor + ' ' + str(speed))
                state(lambda s: s['enabled'] and zero(s))
        print('PASS PC each wheel forward/reverse and release to zero', flush=True)
        request('estop', True)
        state(lambda s: s['emergency_stop'] and not s['enabled'] and zero(s))
        request('enable', True)
        state(lambda s: s['enabled'] and not s['emergency_stop'] and zero(s))
        request('estop', True)
        state(lambda s: s['emergency_stop'] and not s['enabled'] and zero(s))
        request('estop', False)
        state(lambda s: not s['emergency_stop'] and not s['enabled'] and zero(s))
        print('PASS PC estop, single-enable recovery, explicit clear remains disarmed', flush=True)
        request('enable', True)
        state(lambda s: s['enabled'] and not zero(s), (0.1, 0))
        state(lambda s: not s['enabled'] and zero(s), heartbeat=False, timeout=3)
        state(lambda s: not s['enabled'] and zero(s), (0.1, 0))
        print('PASS PC heartbeat loss disarms, resumed heartbeat cannot restart', flush=True)
        request('enable', True)
        state(lambda s: s['enabled'] and zero(s))
        request('enable', False)
        state(lambda s: not s['enabled'] and zero(s))
        print('PASS PC explicit disable', flush=True)

        connection.close()
        assert connection.process is None
        print('PASS PC graceful SSH/bridge/node shutdown', flush=True)
        events.clear()
        connection.connect()
        wait_for(lambda: connection.ready, timeout=30)
        state(lambda s: not s['enabled'] and zero(s))
        print('PASS PC reconnect starts a new disabled session', flush=True)
    finally:
        connection.close()


if __name__ == '__main__':
    main()
