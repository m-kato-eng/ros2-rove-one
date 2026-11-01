"""GPIO/ROS-independent motion limits and stop state machine."""
from dataclasses import dataclass
import math
import time


@dataclass(frozen=True)
class Limits:
    track_width: float = 0.20
    max_linear: float = 0.30
    max_angular: float = 1.0
    max_wheel_speed: float = 0.40
    max_duty: float = 0.35
    command_timeout: float = 0.5

    def __post_init__(self):
        for name, value in vars(self).items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be finite and positive')
        if self.max_duty > 1:
            raise ValueError('max_duty must be <= 1')


class Controller:
    def __init__(self, limits, clock=time.monotonic):
        self.limits = limits
        self.clock = clock
        self.enabled = False
        self.estop = False
        self.reason = 'startup'
        self.last_command = None
        self.left = self.right = 0.0

    def stop(self, reason):
        self.enabled = False
        self.left = self.right = 0.0
        self.last_command = None
        self.reason = reason

    def enable(self, value):
        self.stop('disabled')
        if value and not self.estop:
            self.enabled = True
            self.last_command = self.clock()
            self.reason = 'awaiting_command'
        return self.enabled == value

    def emergency_stop(self, value):
        self.estop = value
        self.stop('emergency_stop' if value else 'estop_cleared_reenable_required')

    def command(self, linear, angular):
        if not all(math.isfinite(v) for v in (linear, angular)):
            self.stop('invalid_command')
            return
        # A command arriving after the deadline cannot revive an expired enable.
        self.tick()
        if not self.enabled or self.estop:
            return
        cfg = self.limits
        linear = max(-cfg.max_linear, min(cfg.max_linear, linear))
        angular = max(-cfg.max_angular, min(cfg.max_angular, angular))
        left = linear - angular * cfg.track_width / 2
        right = linear + angular * cfg.track_width / 2
        scale = max(cfg.max_wheel_speed, abs(left), abs(right))
        self.left = cfg.max_duty * left / scale
        self.right = cfg.max_duty * right / scale
        self.last_command = self.clock()
        self.reason = 'command'

    def tick(self):
        if self.enabled and self.last_command is not None:
            if self.clock() - self.last_command >= self.limits.command_timeout:
                self.stop('command_timeout')
        return self.left, self.right
