"""Short constant-velocity prediction, timed only from real observations."""
import math

from .autonomy import plan


class TargetPredictor:
    def __init__(self, horizon=0.5, timeout=0.3, grace=1.0):
        self.horizon, self.timeout, self.grace = horizon, timeout, grace
        self.clear()

    def clear(self):
        self.sample = None
        self.velocity = (0.0, 0.0)
        self.image_time = None
        self.missing = False

    def observe(self, data, frame_time):
        point = data['target']['target_normalized']
        x, y = point['x'], point['y']
        if any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1
               for v in (x, y)):
            raise ValueError('invalid target')
        if self.image_time is not None and frame_time <= self.image_time:
            return
        track = data['target'].get('track_id')
        velocity = (0.0, 0.0)
        if self.sample is not None:
            px, py, previous_time, previous_track = self.sample
            dt = frame_time - previous_time
            if 0.01 <= dt <= self.timeout and track == previous_track:
                velocity = ((x-px)/dt, (y-py)/dt)
        self.sample = (x, y, frame_time, track)
        self.velocity = velocity
        self.image_time = frame_time
        self.missing = False

    def miss(self, frame_time):
        if self.image_time is None or frame_time > self.image_time:
            self.image_time = frame_time
            self.missing = True

    @staticmethod
    def target(x, y):
        return {'state': 'tracking', 'target_valid': True,
                'target': {'target_normalized': {'x': x, 'y': y}}}

    def command(self, now):
        stopped = plan(None, self.horizon)
        if self.sample is None or self.image_time is None:
            return stopped
        x, y, observed, _ = self.sample
        age = now - observed
        # Image/recognition stream failure is not an ordinary missed detection.
        if now-self.image_time > self.timeout or age < 0:
            return dict(stopped, reason='prediction_stream_stale')
        if not self.missing:
            return plan(self.target(x, y), self.horizon)
        if age >= self.grace:
            return dict(stopped, reason='prediction_expired')
        original = plan(self.target(x, y), self.horizon)
        if original['speed'] == 0:
            return stopped  # Missing near targets do not keep rotating blindly.
        px, py = x + self.velocity[0]*age, y + self.velocity[1]*age
        if not (0 <= px <= 1 and self.horizon <= py < 0.75):
            return dict(stopped, reason='prediction_outside_drive_range')
        command = plan(self.target(px, py), self.horizon)
        command['speed'] = min(command['speed'], original['speed'])
        command.update(reason='predicting', prediction_age_sec=age,
                       predicted_target_normalized={'x': px, 'y': py})
        return command
