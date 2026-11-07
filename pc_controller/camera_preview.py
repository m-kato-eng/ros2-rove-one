"""Independent SSH camera transport and Tk view; never sends motor commands."""
from io import BytesIO
import json
from pathlib import Path
import queue
import socket
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler

from PIL import Image, ImageTk


class CameraClient:
    def __init__(self):
        self.stop_event = threading.Event()
        self.process = None
        self.events = queue.Queue(maxsize=1)
        self.thread = None

    def start(self, config=None):
        if self.thread is not None and self.thread.is_alive() and not self.stop_event.is_set():
            return
        if config is None:
            base = Path(__file__).resolve().parent
            config = json.loads((base / 'connection.json').read_text(encoding='utf-8'))
            for name in ('key', 'known_hosts'):
                config[name] = str((base / config[name]).resolve())
        if not isinstance(config, dict) or config['host'].startswith('-'):
            raise ValueError('Invalid camera SSH configuration')
        self.stop_event = threading.Event()
        self.events = queue.Queue(maxsize=1)
        self.thread = threading.Thread(target=self._work, args=(dict(config), self.stop_event, self.events), daemon=True)
        self.thread.start()

    @staticmethod
    def _put(events, value):
        try:
            events.get_nowait()
        except queue.Empty:
            pass
        events.put_nowait(value)

    def _work(self, config, stop, events):
        process = None
        try:
            with socket.socket() as available:
                available.bind(('127.0.0.1', 0))
                port = available.getsockname()[1]
            args = ['ssh', '-N', '-T', '-i', config['key'],
                    '-o', 'UserKnownHostsFile=' + config['known_hosts'],
                    '-o', 'StrictHostKeyChecking=yes', '-o', 'BatchMode=yes',
                    '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=8',
                    '-o', 'ServerAliveInterval=2', '-o', 'ServerAliveCountMax=2',
                    '-L', f'127.0.0.1:{port}:127.0.0.1:8765', config['host']]
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.PIPE,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if not stop.is_set():
                self.process = process
            opener = build_opener(ProxyHandler({}))

            def fetch(path, limit=2_000_000):
                with opener.open(f'http://127.0.0.1:{port}' + path, timeout=0.8) as response:
                    data = response.read(limit + 1)
                    if len(data) > limit:
                        raise ValueError('Camera response exceeds limit')
                    return data

            while not stop.is_set():
                if process.poll() is not None:
                    raise ConnectionError('映像SSH切断: ' + process.stderr.read().decode('utf-8', 'replace')[:250])
                started = time.monotonic()
                try:
                    health = json.loads(fetch('/health'))
                    target = json.loads(fetch('/target'))
                    if not health.get('image_fresh') or health.get('last_frame_age_sec', 99) > 0.5:
                        raise ConnectionError('カメラ画像停止 / 目標無効')
                    path = '/debug/frame.jpg' if target.get('state') not in ('stale', 'error', 'unconfigured') else '/frame.jpg'
                    try:
                        data = fetch(path)
                    except HTTPError as exc:
                        if path != '/debug/frame.jpg' or exc.code not in (404, 503):
                            raise
                        data = fetch('/frame.jpg')
                    image = Image.open(BytesIO(data))
                    if image.width > 4096 or image.height > 4096:
                        raise ValueError('Camera image exceeds size limit')
                    image = image.convert('RGB')
                    self._put(events, {'image': image, 'target': target, 'at': time.monotonic()})
                except Exception as exc:
                    self._put(events, {'error': str(exc), 'at': time.monotonic()})
                stop.wait(max(0.01, 0.2 - (time.monotonic() - started)))
        except Exception as exc:
            self._put(events, {'error': str(exc), 'at': time.monotonic()})
        finally:
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
                if process.stderr:
                    process.stderr.close()

    def stop(self):
        self.stop_event.set()
        process = self.process
        if process is not None and process.poll() is None:
            process.terminate()


class CameraPanel:
    def __init__(self, parent):
        self.frame = ttk.LabelFrame(parent, text='カメラ / 地面上の明部', padding=12)
        self.client = CameraClient()
        self.image = None
        self.photo = None
        self.last_image_at = 0
        self.status = tk.StringVar(value='映像未接続')
        self.target_text = tk.StringVar(value='目標なし / 自動走行には接続しません')
        row = ttk.Frame(self.frame)
        row.pack(fill='x')
        ttk.Button(row, text='映像接続', command=self.start).pack(side='left')
        ttk.Button(row, text='映像停止', command=self.stop).pack(side='left', padx=8)
        self.canvas = tk.Canvas(self.frame, width=480, height=360, background='#151515', highlightthickness=0)
        self.canvas.pack(fill='x', pady=12)
        self.canvas.bind('<Configure>', lambda event: self.draw())
        ttk.Label(self.frame, text='赤い線に水平線を合わせて、カメラの取り付けを調整してください。\n'
                  '赤線より下を、平坦・水平な地面として認識します。', wraplength=480).pack(anchor='w')
        ttk.Label(self.frame, textvariable=self.status, wraplength=480).pack(anchor='w', pady=10)
        ttk.Label(self.frame, textvariable=self.target_text, wraplength=480).pack(anchor='w')
        self.frame.after(100, self.refresh)
        self.draw()

    def start(self, config=None):
        try:
            self.client.start(config)
            self.status.set('映像SSH接続中…')
        except Exception as exc:
            self.status.set(str(exc))

    def stop(self):
        self.client.stop()
        self.last_image_at = 0
        self.image = None
        self.status.set('映像停止')
        self.target_text.set('目標無効 / 自動走行には接続しません')
        self.draw()

    def draw(self):
        canvas = self.canvas
        canvas.delete('all')
        width = max(1, canvas.winfo_width())
        height = max(1, canvas.winfo_height())
        if self.image is not None:
            image = self.image.copy()
            image.thumbnail((width, height), Image.Resampling.BILINEAR)
            self.photo = ImageTk.PhotoImage(image, master=canvas)
            x, y = (width - image.width) / 2, (height - image.height) / 2
            canvas.create_image(x, y, image=self.photo, anchor='nw')
            # Draw against the actual displayed image, excluding any letterbox area.
            canvas.create_line(x, y + image.height / 2, x + image.width, y + image.height / 2,
                               fill='red', width=2, tags='horizon')
        else:
            self.photo = None
            canvas.create_line(0, height / 2, width, height / 2, fill='red', width=2, tags='horizon')
            canvas.create_text(width / 2, height / 2 - 25, text='映像なし', fill='white')

    def refresh(self):
        try:
            event = self.client.events.get_nowait()
        except queue.Empty:
            event = None
        if event and not self.client.stop_event.is_set():
            if 'error' in event:
                self.status.set(event['error'])
                self.target_text.set('目標無効')
                self.image = None
            else:
                self.image = event['image']
                self.last_image_at = event['at']
                target = event['target']
                self.status.set('映像受信中 / 認識: ' + target.get('state', 'unknown'))
                item = target.get('target')
                if target.get('target_valid') and item:
                    point = item['target_px']
                    self.target_text.set(f"目標: ({point['x']:.1f}, {point['y']:.1f}) px")
                else:
                    self.target_text.set('目標なし / ' + target.get('reason', target.get('state', '')))
            self.draw()
        if self.image is not None and time.monotonic() - self.last_image_at > 0.8:
            self.image = None
            self.status.set('映像受信停止 / 再接続を確認してください')
            self.target_text.set('目標無効')
            self.draw()
        self.frame.after(100, self.refresh)
