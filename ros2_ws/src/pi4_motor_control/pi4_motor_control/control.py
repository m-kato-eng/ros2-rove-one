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
        self.wheel = None
        self.front = None

    def stop(self, reason):
        self.enabled = False
        self.left = self.right = 0.0
        self.wheel = None
        self.front = None
        self.last_command = None
        self.reason = reason

    def enable(self, value):
        self.stop('disabled')
        if value:
            # An explicit enable acknowledges the software emergency stop.
            # stop() above discards all previous motion before rearming.
            self.estop = False
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
        self.wheel = None
        self.front = None
        self.last_command = self.clock()
        self.reason = 'command'

    def steer_command(self, speed, turn, steering_gain=1.0):
        if (type(steering_gain) not in (int, float) or
                not math.isfinite(steering_gain) or not 1 <= steering_gain <= 2 or
                not all(math.isfinite(v) for v in (speed, turn))):
            self.stop('invalid_command')
            return
        self.tick()
        if not self.enabled or self.estop:
            return
        cfg = self.limits
        speed, turn = [max(-cfg.max_linear, min(cfg.max_linear, v)) for v in (speed, turn)]
        duty = lambda v: cfg.max_duty * max(-cfg.max_wheel_speed, min(cfg.max_wheel_speed, v)) / cfg.max_wheel_speed
        self.left = self.right = duty(speed)
        if speed == 0:
            # Stationary turns use the original output in both modes.
            self.front = (duty(-turn), duty(turn))
        else:
            # Steering changes front duty by 30% of the signed driving duty.
            # Apply the same side multipliers in forward and reverse.
            correction = self.left * steering_gain * (0.3 if turn > 0 else -0.3 if turn < 0 else 0)
            clamp = lambda v: max(-cfg.max_duty, min(cfg.max_duty, v))
            self.front = (clamp(self.left - correction), clamp(self.right + correction))
        self.wheel = None
        self.last_command = self.clock()
        self.reason = 'steer_command'

    def outputs(self):
        self.tick()
        if self.wheel is not None:
            motor, duty = self.wheel
            return [duty if name == motor else 0.0 for name in
                    ('left_front', 'left_rear', 'right_front', 'right_rear')]
        fl, fr = self.front if self.front is not None else (self.left, self.right)
        return [fl, self.left, fr, self.right]

    def wheel_command(self, motor, speed):
        if motor not in ('left_front', 'left_rear', 'right_front', 'right_rear') or not math.isfinite(speed):
            self.stop('invalid_command')
            return
        self.tick()
        if not self.enabled or self.estop:
            return
        speed = max(-self.limits.max_linear, min(self.limits.max_linear, speed))
        duty = self.limits.max_duty * speed / max(self.limits.max_wheel_speed, abs(speed))
        self.wheel = (motor, duty)
        self.front = None
        self.left = self.right = 0.0
        self.last_command = self.clock()
        self.reason = 'wheel_command'

    def tick(self):
        if self.enabled and self.last_command is not None:
            if self.clock() - self.last_command >= self.limits.command_timeout:
                self.stop('command_timeout')
        return self.left, self.right
