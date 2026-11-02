"""Windows Tk UI for a private GPIO-free ROS 2 test session."""
import argparse
import queue
import time
import tkinter as tk
from tkinter import ttk

from transport import Connection


class App:
    def __init__(self, root):
        self.root = root
        root.title('ROS 2 Control Trial — DRY RUN')
        root.geometry('720x790')
        root.minsize(660, 740)
        self.dry_run = tk.BooleanVar(value=True)
        self.mode = 'ドライラン / GPIO出力なし'
        root.title('ROS 2 Control Trial — ' + self.mode)
        self.connection = None
        self.vector = (0.0, 0.0)
        self.wheel = None
        self.arrow_keys = set()
        self.arrow_release_jobs = {}
        self.message = tk.StringVar(value='未接続')
        self.state = tk.StringVar(value='無効 / 仮想モーター出力 0')
        self.duties = tk.StringVar(value='LF 0.000   LR 0.000   RF 0.000   RR 0.000')
        self.speed = tk.DoubleVar(value=0.1)
        self.last_tick = time.monotonic()
        panel = ttk.Frame(root, padding=20)
        panel.pack(fill='both', expand=True)
        ttk.Label(panel, text='ROS 2 モーター制御テスト', font=('', 19, 'bold')).pack(anchor='w')
        self.mode_label = tk.StringVar(value=self.mode + ' • 押している間だけ方向指令')
        ttk.Label(panel, textvariable=self.mode_label,
                  foreground='#196747').pack(anchor='w', pady=(5, 16))
        toolbar = ttk.Frame(panel)
        toolbar.pack(fill='x')
        ttk.Button(toolbar, text='SSH 接続', command=self.connect).pack(side='left', padx=(0, 8))
        ttk.Button(toolbar, text='切断', command=self.disconnect).pack(side='left')
        self.mode_checkbox = ttk.Checkbutton(
            toolbar, text='ドライラン（GPIO出力なし）', variable=self.dry_run,
            command=self.update_mode)
        self.mode_checkbox.pack(side='left', padx=16)
        ttk.Label(panel, textvariable=self.message, wraplength=660).pack(anchor='w', pady=10)
        ttk.Separator(panel).pack(fill='x')
        ttk.Label(panel, textvariable=self.state, font=('', 12, 'bold')).pack(anchor='w', pady=(12, 4))
        ttk.Label(panel, textvariable=self.duties, font=('Consolas', 11)).pack(anchor='w')
        row = ttk.Frame(panel)
        row.pack(fill='x', pady=12)
        ttk.Button(row, text='有効化', command=lambda: self.request('enable', True)).pack(side='left')
        ttk.Button(row, text='停止 / 無効化', command=self.stop).pack(side='left', padx=8)
        ttk.Label(row, text='速度目標 m/s').pack(side='left', padx=(15, 5))
        speed_input = ttk.Spinbox(row, from_=0.02, to=0.3, increment=0.02, width=6,
                                  textvariable=self.speed)
        speed_input.pack(side='left')
        for key in ('Up', 'Down', 'Left', 'Right'):
            speed_input.bind('<KeyPress-' + key + '>',
                             lambda event, k=key: self.arrow_press(k))
            speed_input.bind('<KeyRelease-' + key + '>',
                             lambda event, k=key: self.arrow_release(k))
        pad = ttk.Frame(panel)
        pad.pack(pady=6)
        for label, vector, position in [
                ('前進', (1, 0), (0, 1)), ('左旋回', (0, 1), (1, 0)),
                ('後退', (-1, 0), (1, 1)), ('右旋回', (0, -1), (1, 2))]:
            button = ttk.Button(pad, text=label, width=16)
            button.grid(row=position[0], column=position[1], padx=4, pady=4, ipady=9)
            button.bind('<ButtonPress-1>', lambda event, v=vector: self.hold(v))
        root.bind_all('<ButtonRelease-1>', lambda event: self.release())
        for key in ('Up', 'Down', 'Left', 'Right'):
            root.bind_all('<KeyPress-' + key + '>',
                          lambda event, k=key: self.arrow_press(k))
            root.bind_all('<KeyRelease-' + key + '>',
                          lambda event, k=key: self.arrow_release(k))
        wheel_pad = ttk.LabelFrame(panel, text='一輪ずつ回す（押下中のみ）', padding=8)
        wheel_pad.pack(fill='x', pady=8)
        for row, (label, motor) in enumerate((('左前', 'left_front'), ('左後', 'left_rear'),
                                               ('右前', 'right_front'), ('右後', 'right_rear'))):
            ttk.Label(wheel_pad, text=label, width=8).grid(row=row, column=0, padx=5, pady=3)
            for column, (direction, sign) in enumerate((('正転', 1), ('逆転', -1)), start=1):
                button = ttk.Button(wheel_pad, text=direction, width=14)
                button.grid(row=row, column=column, padx=5, pady=3)
                button.bind('<ButtonPress-1>', lambda event, m=motor, v=sign: self.hold_wheel(m, v))
        root.bind('<FocusOut>', self.focus_out)
        root.bind('<space>', lambda event: self.stop())
        root.bind('<Escape>', lambda event: self.request('estop', True))
        emergency = tk.Button(panel, text='緊急停止  /  Esc', bg='#a6202c', fg='white',
                              font=('', 13, 'bold'), command=lambda: self.request('estop', True))
        emergency.pack(fill='x', pady=(12, 5), ipady=8)
        ttk.Button(panel, text='緊急停止ラッチ解除（解除後も無効）',
                   command=lambda: self.request('estop', False)).pack(anchor='w')
        ttk.Label(panel, text='方向ボタンまたは↑↓←→を離すと速度0。Spaceで無効化。フォーカス喪失・通信途絶でも停止。\n'
                  '有効化時は方向ボタンを離してください。状態表示と詳細ログを確認できます。',
                  wraplength=660).pack(anchor='w', pady=12)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.tick)

    def update_mode(self):
        self.mode = 'ドライラン / GPIO出力なし' if self.dry_run.get() else '実機 / PWM上限80%'
        self.mode_label.set(self.mode + ' • 押している間だけ方向指令')
        self.root.title('ROS 2 Control Trial — ' + self.mode)

    def connect(self):
        if self.connection and self.connection.process and self.connection.process.poll() is None:
            return
        self.release()
        try:
            self.update_mode()
            self.connection = Connection(dry_run=self.dry_run.get())
            self.connection.connect()
            self.mode_checkbox.state(['disabled'])
            self.message.set('SSH接続中…（専用ROSセッションを準備）')
        except Exception as exc:
            self.message.set(str(exc))

    def request(self, op, value):
        self.release()
        try:
            if not self.connection or not self.connection.ready:
                raise ConnectionError('先にSSH接続してください')
            self.connection.drive()
            self.connection.request(op, value)
        except Exception as exc:
            self.message.set(str(exc))

    def hold(self, vector):
        if self.connection and self.connection.ready and self.connection.status:
            if self.connection.status.get('enabled'):
                try:
                    speed = self.speed.get()
                    if not 0.02 <= speed <= 0.3:
                        raise ValueError('速度は0.02〜0.3にしてください')
                    self.vector = (vector[0] * speed, vector[1] * speed)
                    self.wheel = None
                except (ValueError, tk.TclError) as exc:
                    self.message.set(str(exc))
                    self.stop()

    def release(self):
        self.vector = (0.0, 0.0)
        self.wheel = None
        self.arrow_keys.clear()
        for job in self.arrow_release_jobs.values():
            self.root.after_cancel(job)
        self.arrow_release_jobs.clear()

    def arrow_press(self, key):
        job = self.arrow_release_jobs.pop(key, None)
        if job is not None:
            self.root.after_cancel(job)
        if self.connection and self.connection.ready and self.connection.status and self.connection.status.get('enabled'):
            self.arrow_keys.add(key)
            self.update_arrows()
        return 'break'

    def update_arrows(self):
        keys = self.arrow_keys
        if {'Up', 'Down'} <= keys or {'Left', 'Right'} <= keys:
            self.vector = (0.0, 0.0)
            self.wheel = None
            return
        self.hold((int('Up' in keys) - int('Down' in keys),
                   int('Left' in keys) - int('Right' in keys)))

    def arrow_release(self, key):
        if key in self.arrow_keys and key not in self.arrow_release_jobs:
            def finish():
                self.arrow_release_jobs.pop(key, None)
                self.arrow_keys.discard(key)
                self.update_arrows()
            self.arrow_release_jobs[key] = self.root.after(40, finish)
        return 'break'

    def hold_wheel(self, motor, direction):
        if self.connection and self.connection.ready and self.connection.status:
            if self.connection.status.get('enabled'):
                try:
                    speed = self.speed.get()
                    if not 0.02 <= speed <= 0.3:
                        raise ValueError('速度は0.02〜0.3にしてください')
                    self.vector = (0.0, 0.0)
                    self.wheel = (motor, direction * speed)
                except (ValueError, tk.TclError) as exc:
                    self.message.set(str(exc))
                    self.stop()

    def stop(self):
        self.request('enable', False)

    def focus_out(self, event):
        # Moving focus between controls is allowed; leaving this app disarms it.
        self.root.after_idle(self.check_focus)

    def check_focus(self):
        if self.root.focus_displayof() is None:
            self.release()
            if self.connection and self.connection.ready:
                self.request('enable', False)

    def tick(self):
        now = time.monotonic()
        if now - self.last_tick > 0.3:
            self.release()
            if self.connection and self.connection.ready:
                self.request('enable', False)
        self.last_tick = now
        connection = self.connection
        if connection:
            for _ in range(100):
                try:
                    event = connection.events.get_nowait()
                except queue.Empty:
                    break
                kind = event.get('type')
                if kind == 'ready':
                    self.message.set('接続済み / ' + self.mode + ' / 有効化して操作できます')
                elif kind == 'response':
                    self.message.set(('成功: ' if event['ok'] else '拒否: ') + event['message'])
                elif kind in ('error', 'disconnected', 'event'):
                    self.message.set(event.get('message', kind))
                    if kind != 'event':
                        self.release()
                    if kind == 'disconnected':
                        self.mode_checkbox.state(['!disabled'])
                        self.state.set('通信切断 / 出力状態を受信できません')
                        self.duties.set('LF —   LR —   RF —   RR —')
            fresh = now - connection.status_at <= 1.0
            if connection.ready and fresh:
                try:
                    if self.wheel is not None:
                        connection.wheel(*self.wheel)
                    else:
                        connection.steer(*self.vector)
                except (ConnectionError, ValueError) as exc:
                    self.release()
                    self.message.set(str(exc))
                status = connection.status
                if status:
                    self.state.set(('有効' if status['enabled'] else '無効') +
                                   (' / 緊急停止中' if status['emergency_stop'] else '') +
                                   ' / ' + status['reason'])
                    values = list(status['duties'].values())
                    self.duties.set('   '.join(f'{name} {value:+.3f}' for name, value in
                                              zip(('LF', 'LR', 'RF', 'RR'), values)))
            elif connection.ready:
                self.release()
                self.state.set('状態受信が途絶えました / 指令送信停止')
                self.duties.set('LF —   LR —   RF —   RR —')
        self.root.after(100, self.tick)

    def disconnect(self):
        self.release()
        if self.connection:
            self.connection.close()
            self.connection = None
        self.message.set('切断済み')
        self.mode_checkbox.state(['!disabled'])
        self.state.set('無効 / SSHセッション終了')
        self.duties.set('LF 0.000   LR 0.000   RF 0.000   RR 0.000')

    def close(self):
        self.disconnect()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--gui-check', action='store_true')
    args = parser.parse_args()
    root = tk.Tk()
    app = App(root)
    if args.gui_check:
        from unittest.mock import MagicMock, patch
        root.update()
        assert root.winfo_exists()
        assert app.dry_run.get() is True
        for dry_run in (True, False):
            app.dry_run.set(dry_run)
            with patch('controller.Connection' if __name__ != '__main__' else '__main__.Connection') as factory:
                connection = MagicMock()
                connection.process = None
                factory.return_value = connection
                app.connect()
                factory.assert_called_once_with(dry_run=dry_run)
                assert app.mode_checkbox.instate(['disabled'])
                app.disconnect()
                connection.close.assert_called_once()
                assert app.mode_checkbox.instate(['!disabled'])
        app.vector = (0.1, 0.0)
        app.release()
        assert app.vector == (0, 0)
        app.close()
        print('PASS Tk GUI construction, release, close')
    else:
        root.mainloop()


if __name__ == '__main__':
    main()
