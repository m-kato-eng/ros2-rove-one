import math
import pytest

from pi4_motor_control.control import Controller, Limits
from pi4_motor_control.backends import DryRunBackend, GpioBackend, MOTORS, validate_pins


@pytest.fixture
def machine():
    now = [100.0]
    return Controller(Limits(), clock=lambda: now[0]), now


def test_startup_drops_commands_and_enable_does_not_replay(machine):
    controller, _ = machine
    controller.command(0.2, 0)
    assert controller.tick() == (0, 0)
    assert controller.enable(True)
    assert controller.tick() == (0, 0)
    controller.command(0.2, 0)
    left, right = controller.tick()
    assert left == right and left > 0


def test_direction_turn_and_saturation(machine):
    controller, _ = machine
    controller.enable(True)
    controller.command(-0.2, 0)
    assert controller.left == controller.right < 0
    controller.command(0, 1)
    assert controller.left < 0 < controller.right
    controller.command(999, 999)
    assert max(abs(controller.left), abs(controller.right)) <= 0.35
    assert controller.left / controller.right == pytest.approx(0.5)


def test_deadline_disables_and_late_command_cannot_revive(machine):
    controller, now = machine
    controller.enable(True)
    controller.command(0.2, 0)
    now[0] += 0.5
    # Enforce expiration even if no timer tick happened before this callback.
    controller.command(0.2, 0)
    assert controller.tick() == (0, 0)
    assert not controller.enabled
    assert controller.reason == 'command_timeout'
    controller.enable(True)
    assert controller.tick() == (0, 0)


def test_estop_latches_and_clear_needs_new_enable(machine):
    controller, _ = machine
    controller.enable(True)
    controller.command(0.2, 0)
    controller.emergency_stop(True)
    controller.command(0.2, 0)
    assert controller.tick() == (0, 0)
    controller.emergency_stop(False)
    assert not controller.enabled
    controller.command(0.2, 0)
    assert controller.tick() == (0, 0)
    assert controller.enable(True)
    controller.emergency_stop(True)
    assert controller.enable(True)
    assert not controller.estop
    assert controller.outputs() == [0, 0, 0, 0]
    controller.command(0.2, 0)
    assert any(controller.outputs())


@pytest.mark.parametrize('bad', [math.nan, math.inf, -math.inf])
def test_nonfinite_command_stops(machine, bad):
    controller, _ = machine
    controller.enable(True)
    controller.command(0.2, 0)
    controller.command(bad, 0)
    assert controller.tick() == (0, 0)
    assert not controller.enabled


@pytest.mark.parametrize('field,value', [
    ('track_width', 0), ('max_linear', -1), ('max_angular', math.nan),
    ('max_wheel_speed', math.inf), ('max_duty', 1.01), ('command_timeout', 0),
])
def test_invalid_limits(field, value):
    with pytest.raises(ValueError):
        Limits(**{field: value})


def valid_pins():
    return dict(zip(MOTORS, [(4, 5, 6), (12, 13, 16), (17, 18, 19), (20, 21, 22)]))


@pytest.mark.parametrize('speed,turn,expected', [
    (0, 0.1, [-0.2, 0, 0.2, 0]),
    (0, -0.1, [0.2, 0, -0.2, 0]),
    (0.1, 0.1, [0.14, 0.2, 0.26, 0.2]),
    (-0.1, 0.1, [-0.14, -0.2, -0.26, -0.2]),
    (0.3, -0.3, [0.78, 0.6, 0.42, 0.6]),
])
def test_front_steering_preserves_rear_drive(speed, turn, expected):
    now = [0.0]
    controller = Controller(Limits(max_duty=0.8), clock=lambda: now[0])
    controller.enable(True)
    controller.steer_command(speed, turn)
    assert controller.outputs() == pytest.approx(expected)
    now[0] += 0.5
    assert controller.outputs() == [0, 0, 0, 0]
    assert not controller.enabled


def test_gpio_gates_validate_before_import_or_access():
    with pytest.raises(ValueError, match='hardware_confirmed'):
        GpioBackend(valid_pins(), 100)
    with pytest.raises(ValueError, match='BCM'):
        GpioBackend(dict.fromkeys(MOTORS, [-1, -1, -1]), 100, confirmed=True)
    pins = valid_pins()
    pins['right_rear'] = (4, 23, 24)
    with pytest.raises(ValueError, match='shared'):
        validate_pins(pins)


def test_dry_backend_rejects_invalid_output():
    backend = DryRunBackend()
    with pytest.raises(ValueError):
        backend.write([math.nan, 0, 0, 0])
    assert backend.duties == [0, 0, 0, 0]


class FakePwm:
    def __init__(self, gpio, pin):
        self.gpio, self.pin = gpio, pin

    def start(self, duty):
        self.ChangeDutyCycle(duty)

    def ChangeDutyCycle(self, duty):
        self.gpio.events.append(('duty', self.pin, duty))

    def stop(self):
        self.gpio.events.append(('stop', self.pin))


class FakeGpio:
    BCM, OUT, LOW, HIGH = 'BCM', 'OUT', 0, 1

    def __init__(self):
        self.events = []

    def setmode(self, mode):
        self.events.append(('mode', mode))

    def setup(self, pin, mode, initial):
        self.events.append(('setup', pin, initial))

    def output(self, pin, value):
        self.events.append(('output', pin, value))

    def PWM(self, pin, frequency):
        return FakePwm(self, pin)

    def cleanup(self, pins):
        self.events.append(('cleanup', tuple(pins)))


def test_gpio_disable_precedes_direction_changes_and_cleanup():
    gpio = FakeGpio()
    backend = GpioBackend(valid_pins(), 100, confirmed=True, gpio=gpio,
                          sleep=lambda seconds: gpio.events.append(('sleep', seconds)))
    setups = [e for e in gpio.events if e[0] == 'setup']
    assert [e[1] for e in setups[:4]] == [6, 16, 19, 22]
    assert all(e[2] == 0 for e in setups)
    backend.write([0.2] * 4)
    gpio.events.clear()
    backend.write([-0.2] * 4)
    assert gpio.events[:4] == [('duty', pin, 0) for pin in (6, 16, 19, 22)]
    assert gpio.events[4] == ('sleep', 0.02)
    assert gpio.events[5] == ('output', 4, 0)
    assert gpio.events[6] == ('output', 5, 1)
    backend.close()
    assert backend.duties == [0, 0, 0, 0]
    assert len([e for e in gpio.events if e[0] == 'stop']) == 4
    assert gpio.events[-1][0] == 'cleanup'


def test_auto_doubles_driving_correction_and_stationary_is_original_for_both_modes():
    controller = Controller(Limits(max_duty=0.8))
    controller.enable(True)
    controller.steer_command(0.1, 0.1, steering_gain=2)
    assert controller.outputs() == pytest.approx([0.08, 0.2, 0.32, 0.2])
    controller.steer_command(0, 0.1, steering_gain=2)
    assert controller.outputs() == pytest.approx([-0.2, 0, 0.2, 0])
    controller.steer_command(0, 0.3, steering_gain=2)
    assert controller.outputs() == pytest.approx([-0.6, 0, 0.6, 0])
    controller.steer_command(0, 0.1)
    assert controller.outputs() == pytest.approx([-0.2, 0, 0.2, 0])
    controller.steer_command(0.1, 0.1)
    assert controller.outputs() == pytest.approx([0.14, 0.2, 0.26, 0.2])
    controller.enable(False)
    controller.steer_command(0, 0.1, steering_gain=2)
    assert controller.outputs() == [0, 0, 0, 0]


@pytest.mark.parametrize('gain', [True, 0, 3, math.nan, math.inf])
def test_invalid_steering_gain_disarms(gain):
    controller = Controller(Limits())
    controller.enable(True)
    controller.steer_command(0.1, 0.1, steering_gain=gain)
    assert not controller.enabled
    assert controller.outputs() == [0, 0, 0, 0]
