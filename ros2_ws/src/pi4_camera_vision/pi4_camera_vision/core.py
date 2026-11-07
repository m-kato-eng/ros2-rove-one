"""ROS-independent JPEG framing and the detector/result contract."""
from dataclasses import dataclass
import importlib
import math


class JpegFramer:
    def __init__(self, limit=4_000_000):
        self.buffer = bytearray()
        self.limit = limit

    def feed(self, chunk):
        self.buffer.extend(chunk)
        frames = []
        while True:
            start = self.buffer.find(b'\xff\xd8')
            if start < 0:
                self.buffer[:] = self.buffer[-1:]  # SOI may straddle two reads.
                break
            if start:
                del self.buffer[:start]
            end = self.buffer.find(b'\xff\xd9', 2)
            if end < 0:
                break
            frames.append(bytes(self.buffer[:end + 2]))
            del self.buffer[:end + 2]
        if len(self.buffer) > self.limit:
            self.buffer.clear()
            raise ValueError('JPEG frame exceeds buffer limit')
        return frames


def jpeg_dimensions(data):
    """Read JPEG SOF dimensions without decoding pixels (baseline/progressive)."""
    if not data.startswith(b'\xff\xd8'):
        raise ValueError('not a JPEG')
    pos = 2
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
           0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while pos + 3 < len(data):
        if data[pos] != 0xFF:
            raise ValueError('invalid JPEG marker')
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker in (0xDA, 0xD9):
            break
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
            continue
        if pos + 2 > len(data):
            break
        size = int.from_bytes(data[pos:pos + 2], 'big')
        if size < 2 or pos + size > len(data):
            raise ValueError('truncated JPEG segment')
        if marker in sof:
            if size < 8:
                raise ValueError('invalid JPEG SOF')
            height = int.from_bytes(data[pos + 3:pos + 5], 'big')
            width = int.from_bytes(data[pos + 5:pos + 7], 'big')
            if width and height:
                return width, height
            break
        pos += size
    raise ValueError('JPEG dimensions missing')


@dataclass(frozen=True)
class Detection:
    """Axis-aligned box in SOURCE image pixels, with confidence in [0, 1]."""
    label: str
    confidence: float
    x: float
    y: float
    width: float
    height: float

    def as_dict(self, image_width, image_height):
        values = (self.confidence, self.x, self.y, self.width, self.height)
        if not isinstance(self.label, str) or not self.label or not all(math.isfinite(v) for v in values):
            raise ValueError('invalid detection label or non-finite value')
        if not 0 <= self.confidence <= 1 or self.width <= 0 or self.height <= 0:
            raise ValueError('invalid confidence or box size')
        if (self.x < 0 or self.y < 0 or self.x + self.width > image_width
                or self.y + self.height > image_height):
            raise ValueError('box is outside source image; map/clip detector output first')
        cx, cy = self.x + self.width / 2, self.y + self.height / 2
        return {
            'label': self.label, 'confidence': float(self.confidence),
            'bbox_px': {'x': self.x, 'y': self.y, 'width': self.width, 'height': self.height},
            'center_px': {'x': cx, 'y': cy},
            'center_normalized': {'x': cx / image_width, 'y': cy / image_height},
        }


class NoDetector:
    configured = False

    def detect(self, jpeg, width, height):
        return []


def load_detector(spec):
    """Plugin is a no-argument class exposing detect(jpeg_bytes, width, height)."""
    if spec == 'none':
        return NoDetector()
    module, name = spec.split(':', 1)
    detector = getattr(importlib.import_module(module), name)()
    if not callable(getattr(detector, 'detect', None)):
        raise TypeError('detector must provide detect(jpeg, width, height)')
    return detector


def result(state, detector, frame=None, detections=(), processing_ms=0.0, error=''):
    return {'schema_version': 1, 'state': state, 'detector': detector,
            'frame': frame, 'detections': list(detections),
            'processing_ms': processing_ms, 'error': error}
