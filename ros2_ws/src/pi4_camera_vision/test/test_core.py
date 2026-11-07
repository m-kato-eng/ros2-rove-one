import math
import sys
import types

import pytest

from pi4_camera_vision.core import Detection, JpegFramer, jpeg_dimensions, load_detector


def jpeg(width=320, height=240):
    # Minimal SOF header for parser tests, not a decodable photograph.
    return (b'\xff\xd8\xff\xc0\x00\x0b\x08' + height.to_bytes(2, 'big')
            + width.to_bytes(2, 'big') + b'\x01\x01\x11\x00\xff\xd9')


def test_stream_framing_split_markers_and_multiple_images():
    parser = JpegFramer()
    image = jpeg()
    assert parser.feed(b'noise' + image[:1]) == []
    assert parser.feed(image[1:-1]) == []
    assert parser.feed(image[-1:] + image) == [image, image]
    assert jpeg_dimensions(image) == (320, 240)


def test_jpeg_rejects_malformed_and_bounds_memory():
    for bad in (b'', b'not jpeg', b'\xff\xd8\xff\xc0\x00\x10',
                jpeg()[:8], jpeg(width=0)):
        with pytest.raises(ValueError):
            jpeg_dimensions(bad)
    parser = JpegFramer(limit=20)
    with pytest.raises(ValueError):
        parser.feed(b'\xff\xd8' + b'X' * 30)
    assert len(parser.buffer) == 0
    assert parser.feed(jpeg()) == [jpeg()]


def test_coordinate_contract():
    data = Detection('fixture', 0.9, 10, 20, 100, 40).as_dict(320, 240)
    assert data['center_px'] == {'x': 60, 'y': 40}
    assert data['center_normalized']['x'] == 60 / 320
    assert data['center_normalized']['y'] == 40 / 240


@pytest.mark.parametrize('detection', [
    Detection('', 0.9, 0, 0, 1, 1),
    Detection('x', math.nan, 0, 0, 1, 1),
    Detection('x', 1.1, 0, 0, 1, 1),
    Detection('x', 0.9, -1, 0, 1, 1),
    Detection('x', 0.9, 319, 0, 2, 1),
    Detection('x', 0.9, 0, 0, 0, 1),
])
def test_invalid_detector_coordinates_are_rejected(detection):
    with pytest.raises(ValueError):
        detection.as_dict(320, 240)


def test_detector_loading_without_selecting_an_object(monkeypatch):
    detector = load_detector('none')
    assert not detector.configured
    assert detector.detect(jpeg(), 320, 240) == []
    module = types.ModuleType('test_detector_fixture')
    module.Valid = type('Valid', (), {'detect': lambda self, *args: []})
    module.Invalid = type('Invalid', (), {})
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert load_detector('test_detector_fixture:Valid').detect(b'', 1, 1) == []
    with pytest.raises(TypeError):
        load_detector('test_detector_fixture:Invalid')
    with pytest.raises((ValueError, ModuleNotFoundError)):
        load_detector('missing:Detector')
