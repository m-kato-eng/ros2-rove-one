"""Image-space driving policy. Distance is relative, not metres."""
import math


def plan(data, horizon=0.5):
    stop = dict(speed=0.0, turn=0.0, emergency_stop=False, reason='unknown',
                relative_distance=None, horizontal_error=None)
    if data is None:
        return stop
    try:
        if data.get('target_valid') is not True or data.get('state') != 'tracking':
            return stop
        p = data['target']['target_normalized']
        x, y = p['x'], p['y']
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in (x, y)):
            return dict(stop, reason='invalid_target')
        if y >= 0.75:
            return dict(stop, emergency_stop=True, reason='target_near_emergency')
        if y < horizon:
            return dict(stop, reason='above_horizon')
        distance = (0.75-y)/(0.75-horizon)
        error = 2*x-1
        return dict(speed=0.04+0.16*distance, turn=0.0 if abs(error)<0.1 else -0.3*error,
                    emergency_stop=False, reason='tracking', relative_distance=distance,
                    horizontal_error=error)
    except (KeyError, TypeError, AttributeError):
        return dict(stop, reason='invalid_target')
