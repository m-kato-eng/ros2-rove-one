"""No GPIO import or pin access until explicitly constructing the real backend."""
import math
import time

MOTORS = ('left_front', 'left_rear', 'right_front', 'right_rear')


def validate_pins(pins):
    if set(pins) != set(MOTORS):
        raise ValueError('Exactly four named motors are required')
    used = []
    for name in MOTORS:
        values = pins[name]
        if len(values) != 3 or any(type(p) is not int or not 2 <= p <= 27 for p in values):
            raise ValueError(f'{name}: set BCM [IN1, IN2, EN] pins in range 2..27')
        used.extend(values)
    if len(set(used)) != len(used):
        raise ValueError('GPIO pins must not be shared between motor inputs')


class DryRunBackend:
    def __init__(self):
        self.duties = [0.0] * 4

    def write(self, duties):
        if len(duties) != 4 or any(not math.isfinite(v) or abs(v) > 1 for v in duties):
            raise ValueError('Expected four finite duties in [-1, 1]')
        self.duties = list(duties)

    def close(self):
        self.write([0.0] * 4)


class GpioBackend(DryRunBackend):
    def __init__(self, pins, frequency, confirmed=False, gpio=None, sleep=time.sleep):
        super().__init__()
        if not confirmed:
            raise ValueError('hardware_confirmed must be true for real GPIO')
        validate_pins(pins)
        if not math.isfinite(frequency) or not 10 <= frequency <= 2000:
            raise ValueError('PWM frequency must be in 10..2000 Hz')
        if gpio is None:
            import RPi.GPIO as gpio
        self.gpio = gpio
        self.sleep = sleep
        self.pins = [pins[name] for name in MOTORS]
        self.pwms = []
        self.owned = []
        self.signs = [0] * 4
        gpio.setmode(gpio.BCM)
        try:
            # Disable every EN before configuring any direction output.
            for _, _, en in self.pins:
                gpio.setup(en, gpio.OUT, initial=gpio.LOW)
                self.owned.append(en)
            for in1, in2, _ in self.pins:
                for pin in (in1, in2):
                    gpio.setup(pin, gpio.OUT, initial=gpio.LOW)
                    self.owned.append(pin)
            for _, _, en in self.pins:
                pwm = gpio.PWM(en, frequency)
                self.pwms.append(pwm)
                pwm.start(0)
        except BaseException:
            self.close()
            raise

    def write(self, duties):
        # Validate before mutating any output.
        DryRunBackend.write(self, duties)
        signs = [1 if v > 0 else -1 if v < 0 else 0 for v in duties]
        if signs != self.signs:
            for pwm in self.pwms:
                pwm.ChangeDutyCycle(0)
            # EN off before any direction change, including a reverse through zero.
            self.sleep(0.02)
            for (in1, in2, _), sign in zip(self.pins, signs):
                self.gpio.output(in1, self.gpio.HIGH if sign > 0 else self.gpio.LOW)
                self.gpio.output(in2, self.gpio.HIGH if sign < 0 else self.gpio.LOW)
            self.signs = signs
        for pwm, duty in zip(self.pwms, duties):
            pwm.ChangeDutyCycle(abs(duty) * 100)

    def close(self):
        # Best effort on every channel, even if one GPIO operation fails.
        errors = []
        for pwm in self.pwms:
            try:
                pwm.ChangeDutyCycle(0)
                pwm.stop()
            except Exception as exc:
                errors.append(exc)
        for pin in self.owned:
            try:
                self.gpio.output(pin, self.gpio.LOW)
            except Exception as exc:
                errors.append(exc)
        self.duties = [0.0] * 4
        if self.owned:
            try:
                self.gpio.cleanup(self.owned)
            except Exception as exc:
                errors.append(exc)
        self.owned = []
        self.pwms = []
        if errors:
            raise RuntimeError('GPIO cleanup failed; cut motor power') from errors[0]
