#!/usr/bin/env python3
"""Safely probe one configured motor GPIO without motor supply voltage."""
import argparse
import time

PINS = {
    4: 'front IN3', 5: 'front IN4', 6: 'front ENB',
    12: 'rear IN3', 13: 'rear IN4', 16: 'rear ENB',
    17: 'front IN1', 18: 'front IN2', 19: 'front ENA',
    20: 'rear IN1', 21: 'rear IN2', 22: 'rear ENA',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bcm_pin', type=int, choices=sorted(PINS))
    parser.add_argument('--seconds', type=float, default=3.0)
    args = parser.parse_args()
    if not 0.2 <= args.seconds <= 5.0:
        parser.error('--seconds must be between 0.2 and 5')

    print('Keep both motor supplies disconnected. This drives one GPIO at 3.3V.')
    print(f'BCM GPIO{args.bcm_pin} ({PINS[args.bcm_pin]}): meter should read ~3.3V to GND.')
    input('Press Enter to continue, or Ctrl+C to cancel: ')

    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    configured = False
    try:
        GPIO.setup(args.bcm_pin, GPIO.OUT, initial=GPIO.LOW)
        configured = True
        GPIO.output(args.bcm_pin, GPIO.HIGH)
        time.sleep(args.seconds)
    finally:
        if configured:
            try:
                GPIO.output(args.bcm_pin, GPIO.LOW)
            finally:
                GPIO.cleanup(args.bcm_pin)
    print('Probe complete: output returned LOW and GPIO was released.')


if __name__ == '__main__':
    main()
