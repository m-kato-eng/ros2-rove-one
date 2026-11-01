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
        root.geometry('720x590')
        root.minsize(660, 550)
        self.connection = None
        self.vector = (0.0, 0.0)
        self.message = tk.StringVar(value='未接続')
        self.state = tk.StringVar(value='無効 / 仮想モーター出力 0')
        self.duties = tk.StringVar(value='LF 0.000   LR 0.000   RF 0.000   RR 0.000')
        self.speed = tk.DoubleVar(value=0.1)
        self.last_tick = time.monotonic()
        panel = ttk.Frame(root, padding=20)
        panel.pack(fill='both', expand=True)
        ttk.Label(panel, text='ROS 2 モーター制御テスト', font=('', 19, 'bold')).pack(anchor='w')
        ttk.Label(panel, text='DRY RUN 専用 • GPIO出力なし • 押している間だけ方向指令',
                  foreground='#196747').pack(anchor='w', pady=(5, 16))
        toolbar = ttk.Frame(panel)
        toolbar.pack(fill='x')
        ttk.Button(toolbar, text='SSH 接続', command=self.connect).pack(side='left', padx=(0, 8))
        ttk.Button(toolbar, text='切断', command=self.disconnect).pack(side='left')
        ttk.Label(panel, textvariable=self.message, wraplength=660).pack(anchor='w', pady=10)
        ttk.Separator(panel).pack(fill='x')
        ttk.Label(panel, textvariable=self.state, font=('', 12, 'bold')).pack(anchor='w', pady=(12, 4))
        ttk.Label(panel, textvariable=self.duties, font=('Consolas', 11)).pack(anchor='w')
        row = ttk.Frame(panel)
        row.pack(fill='x', pady=12)
        ttk.Button(row, text='有効化', command=lambda: self.request('enable', True)).pack(side='left')
        ttk.Button(row, text='停止 / 無効化', command=self.stop).pack(side='left', padx=8)
        ttk.Label(row, text='速度目標 m/s').pack(side='left', padx=(15, 5))
        ttk.Spinbox(row, from_=0.02, to=0.3, increment=0.02, width=6,
                    textvariable=self.speed).pack(side='left')
        pad = ttk.Frame(panel)
        pad.pack(pady=6)
        for label, vector, position in [
                ('前進', (1, 0), (0, 1)), ('左旋回', (0, 0.6), (1, 0)),
                ('後退', (-1, 0), (1, 1)), ('右旋回', (0, -0.6), (1, 2))]:
            button = ttk.Button(pad, text=label, width=16)
            button.grid(row=position[0], column=position[1], padx=4, pady=4, ipady=9)
            button.bind('<ButtonPress-1>', lambda event, v=vector: self.hold(v))
        root.bind_all('<ButtonRelease-1>', lambda event: self.release())
        root.bind('<FocusOut>', self.focus_out)
        root.bind('<space>', lambda event: self.stop())
        root.bind('<Escape>', lambda event: self.request('estop', True))
        emergency = tk.Button(panel, text='緊急停止  /  Esc', bg='#a6202c', fg='white',
                              font=('', 13, 'bold'), command=lambda: self.request('estop', True))
        emergency.pack(fill='x', pady=(12, 5), ipady=8)
        ttk.Button(panel, text='緊急停止ラッチ解除（解除後も無効）',
                   command=lambda: self.request('estop', False)).pack(anchor='w')
        ttk.Label(panel, text='ボタンを離すと速度0。Spaceで無効化。フォーカス喪失・通信途絶でも停止。\n'
                  '有効化時は方向ボタンを離してください。状態表示と詳細ログを確認できます。',
                  wraplength=660).pack(anchor='w', pady=12)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.tick)

    def connect(self):
        if self.connection and self.connection.process and self.connection.process.poll() is None:
            return
        self.release()
        try:
            self.connection = Connection()
            self.connection.connect()
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
                    self.vector = (vector[0] * speed, vector[1])
                except (ValueError, tk.TclError) as exc:
                    self.message.set(str(exc))
                    self.stop()

    def release(self):
        self.vector = (0.0, 0.0)

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
                    self.message.set('接続済み / DRY RUN専用 / 有効化して操作できます')
                elif kind == 'response':
                    self.message.set(('成功: ' if event['ok'] else '拒否: ') + event['message'])
                elif kind in ('error', 'disconnected', 'event'):
                    self.message.set(event.get('message', kind))
                    if kind != 'event':
                        self.release()
                    if kind == 'disconnected':
                        self.state.set('通信切断 / 出力状態を受信できません')
                        self.duties.set('LF —   LR —   RF —   RR —')
            fresh = now - connection.status_at <= 1.0
            if connection.ready and fresh:
                try:
                    connection.drive(*self.vector)
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
        root.update()
        assert root.winfo_exists()
        app.vector = (0.1, 0.0)
        app.release()
        assert app.vector == (0, 0)
        app.close()
        print('PASS Tk GUI construction, release, close')
    else:
        root.mainloop()


if __name__ == '__main__':
    main()
