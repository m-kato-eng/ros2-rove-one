"""Actual Tk + SSH preview test. Does not connect to the motor bridge."""
import time
import tkinter as tk

from controller import App


def main():
    root = tk.Tk()
    root.withdraw()
    app = App(root)
    app.camera.start()
    try:
        deadline = time.monotonic() + 20
        while app.camera.image is None and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        assert app.camera.image is not None, app.camera.status.get()
        assert app.camera.photo is not None
        assert app.connection is None, 'Camera preview must not open a motor session'
        root.deiconify()
        root.update()
        app.camera.draw()
        canvas = app.camera.canvas
        coords = canvas.coords('horizon')
        assert len(coords) == 4
        assert abs(coords[1] - canvas.winfo_height() / 2) <= 1
        assert coords[1] == coords[3]
        print('PASS live SSH image embedded in Tk; centered horizon; no motor connection', flush=True)
        app.camera.stop()
        root.update()
        assert app.camera.image is None
        assert app.camera.client.stop_event.is_set()
        print('PASS preview stop clears stale image', flush=True)
    finally:
        app.close()


if __name__ == '__main__':
    main()
