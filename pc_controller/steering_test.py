"""Local steering checks without SSH, GPIO, ROS or third-party packages."""
import sys
import queue
import time
from pathlib import Path
import tkinter as tk
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ros2_ws/src/pi4_motor_control'))
from pi4_motor_control.control import Controller, Limits
from controller import App


def main():
    for speed, turn, expected in (
        (0, .1, [-.2, 0, .2, 0]), (0, -.1, [.2, 0, -.2, 0]),
        (.1, 0, [.2, .2, .2, .2]),
        (.1, .1, [.14, .2, .26, .2]), (.1, -.1, [.26, .2, .14, .2]),
        (-.1, .1, [-.14, -.2, -.26, -.2]), (-.1, -.1, [-.26, -.2, -.14, -.2]),
        (.3, -.3, [.78, .6, .42, .6]),
    ):
        now = [0.0]
        control = Controller(Limits(max_duty=.8), clock=lambda: now[0])
        control.enable(True)
        control.steer_command(speed, turn)
        assert all(abs(a - b) < 1e-9 for a, b in zip(control.outputs(), expected))
        now[0] = .5
        assert control.outputs() == [0, 0, 0, 0]
        assert not control.enabled
    for speed, turn, expected in ((.3, -.3, [.8, .8, .56, .8]),
                                   (-.3, .3, [-.56, -.8, -.8, -.8])):
        control = Controller(Limits(max_duty=.8, max_wheel_speed=.2))
        control.enable(True)
        control.steer_command(speed, turn)
        assert all(abs(a - b) < 1e-9 for a, b in zip(control.outputs(), expected))
    root = tk.Tk()
    root.withdraw()
    app = App(root)
    app.connection = MagicMock()
    app.connection.status_at = time.monotonic()
    app.connection.events = queue.Queue()
    app.connection.status = {'enabled': True, 'emergency_stop': False,
                             'reason': 'test', 'duties': dict.fromkeys(('LF', 'LR', 'RF', 'RR'), 0)}
    try:
        for drive in ('Up', 'Down'):
            for turn in ('Left', 'Right'):
                app.release()
                app.arrow_press(drive)
                app.arrow_press(turn)
                assert app.vector == (.1 if drive == 'Up' else -.1,
                                      .1 if turn == 'Left' else -.1)
                app.arrow_release(turn)
                app.arrow_press(turn)  # key repeat cancels only this key's release
                assert len(app.arrow_keys) == 2
                app.arrow_release(turn)
                root.after(60, root.quit)
                root.mainloop()
                assert app.vector == (.1 if drive == 'Up' else -.1, 0)
                app.arrow_release(drive)
                root.after(60, root.quit)
                root.mainloop()
                assert app.vector == (0, 0)
        app.arrow_press('Up')
        app.arrow_press('Down')
        assert app.vector == (0, 0)
        app.release()
        assert not app.arrow_keys and not app.arrow_release_jobs
        app.connection.status['command_source'] = 'auto'
        app.hold((1, 0))
        app.hold_wheel('left_front', 1)
        assert app.vector == (0, 0) and app.wheel is None
        app.command_source.set('auto')
        app.request('source', 'auto')
        app.connection.request.assert_called_with('source', 'auto')
        app.stop()
        app.connection.request.assert_called_with('enable', False)
        app.request('estop', True)
        app.connection.request.assert_called_with('estop', True)
    finally:
        app.close()
    print('PASS front steering, rear duties, saturation, timeout, key chords and release')


if __name__ == '__main__':
    main()
