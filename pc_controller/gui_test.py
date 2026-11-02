"""Drive the actual Tk callbacks and scheduler through a real SSH session."""
import time
import tkinter as tk
from unittest.mock import patch

from controller import App
from transport import Connection


def main():
    root = tk.Tk()
    root.withdraw()
    app = App(root)

    def wait_for(predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            root.update()
            if predicate():
                return
            time.sleep(0.02)
        raise AssertionError(app.message.get() + ' / ' + app.state.get())

    def status():
        return app.connection.status if app.connection else None

    def moving():
        return status() and status()['enabled'] and any(status()['duties'].values())

    def stopped():
        return status() and not status()['enabled'] and not any(status()['duties'].values())

    try:
        with patch('controller.Connection', side_effect=lambda **kwargs: Connection(dry_run=True)):
            app.connect()
        wait_for(lambda: app.connection and app.connection.ready and stopped(), timeout=30)
        print('PASS GUI connect and feedback', flush=True)
        app.request('enable', True)
        wait_for(lambda: status() and status()['enabled'])
        app.hold((1, 0))
        wait_for(moving)
        assert '有効' in app.state.get()
        print('PASS GUI hold forward, Tk heartbeat, duty display', flush=True)
        app.release()
        wait_for(lambda: status() and not any(status()['duties'].values()))
        print('PASS GUI button release sends zero', flush=True)
        for key, sign in (('Up', 1), ('Down', -1), ('Left', -1), ('Right', 1)):
            app.arrow_press(key)
            wait_for(lambda: status() and status()['enabled'] and
                     status()['duties']['left_front'] * sign > 0)
            app.arrow_release(key)
            wait_for(lambda: status() and not any(status()['duties'].values()))
        app.arrow_press('Up')
        wait_for(moving)
        app.arrow_release('Up')
        app.arrow_press('Up')  # A repeat press cancels the pending release.
        time.sleep(0.06)
        root.update()
        assert app.vector[0] > 0
        app.arrow_release('Up')
        wait_for(lambda: status() and not any(status()['duties'].values()))
        print('PASS GUI arrow keys, release, and key repeat', flush=True)
        for motor in ('left_front', 'left_rear', 'right_front', 'right_rear'):
            for direction in (1, -1):
                app.hold_wheel(motor, direction)
                wait_for(lambda: status() and status()['enabled'] and
                         all((value * direction > 0) if name == motor else value == 0
                             for name, value in status()['duties'].items()))
                app.release()
                wait_for(lambda: status() and not any(status()['duties'].values()))
        print('PASS GUI individual wheel forward/reverse and release', flush=True)
        app.hold((-1, 0))
        wait_for(lambda: moving() and status()['duties']['left_front'] < 0)
        app.stop()
        wait_for(stopped)
        print('PASS GUI reverse and stop button', flush=True)

        app.request('enable', True)
        wait_for(lambda: status()['enabled'])
        app.hold((1, 0))
        wait_for(moving)
        # Windows may retain the logical Tk focus for a withdrawn window.
        # Inject the actual FocusOut handler's "no app focus" condition.
        with patch.object(root, 'focus_displayof', return_value=None):
            app.check_focus()
        wait_for(stopped)
        assert app.vector == (0, 0)
        print('PASS GUI focus loss disarms and clears held direction', flush=True)

        app.request('enable', True)
        wait_for(lambda: status()['enabled'])
        app.hold((1, 0))
        wait_for(moving)
        time.sleep(0.65)  # Deliberately stall the GUI scheduler/heartbeat.
        wait_for(stopped)
        assert app.vector == (0, 0)
        print('PASS GUI scheduling stall stops; no auto-resume', flush=True)

        app.request('estop', True)
        wait_for(lambda: stopped() and status()['emergency_stop'])
        app.request('estop', False)
        wait_for(lambda: stopped() and not status()['emergency_stop'])
        print('PASS GUI emergency stop and latch clear', flush=True)

        app.request('enable', True)
        wait_for(lambda: status()['enabled'])
        app.speed.set(99)
        app.hold((1, 0))
        wait_for(stopped)
        assert app.vector == (0, 0)
        print('PASS GUI invalid speed refuses motion and disarms', flush=True)

        app.connection.process.terminate()  # Simulate abrupt SSH loss.
        wait_for(lambda: not app.connection.ready)
        wait_for(lambda: '通信切断' in app.state.get())
        assert app.vector == (0, 0)
        assert '—' in app.duties.get()
        print('PASS GUI SSH loss clears controls and marks feedback unavailable', flush=True)
    finally:
        app.close()


if __name__ == '__main__':
    main()
