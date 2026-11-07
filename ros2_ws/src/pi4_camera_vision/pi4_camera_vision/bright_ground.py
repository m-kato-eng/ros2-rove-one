"""Lightweight lower-half bright-region detector; no learned model required."""
from collections import deque
from io import BytesIO
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .core import Detection


class BrightGroundDetector:
    def __init__(self):
        self.mode = 'light_spot'
        self.brightness = 190
        self.contrast = 15
        self.min_area = 12
        self.max_area_ratio = 0.25
        self.confirm_frames = 2
        self.max_jump = 0.20
        self.ambiguity_margin = 0.08
        self.confidence_threshold = 0.5
        self.last_target = None
        self.last_debug = None
        self.previous = None
        self.confirmed = 0
        self.track_id = 0
        self.last_stamp = None

    def configure(self, **values):
        for name, value in values.items():
            setattr(self, name, value)

    def reset(self):
        self.previous = None
        self.confirmed = 0

    def detect(self, jpeg, width, height):
        image = Image.open(BytesIO(jpeg)).convert('RGB')
        if image.size != (width, height):
            raise ValueError('decoded image size mismatch')
        gray = image.convert('L').filter(ImageFilter.MedianFilter(3))
        pixels = np.asarray(gray, dtype=np.float32)
        start_y = height // 2
        background = np.asarray(gray.filter(ImageFilter.BoxBlur(max(3, width // 16))), dtype=np.float32)
        difference = pixels - background
        mask = pixels >= self.brightness
        if self.mode == 'light_spot':
            mask &= difference >= self.contrast
        mask[:start_y] = False
        # Remove isolated pixels; retain compact regions instead of individual maxima.
        cleaned = Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
        mask = np.asarray(cleaned) > 0
        mask[:start_y] = False
        visited = np.zeros(mask.shape, dtype=bool)
        candidates = []
        max_area = width * (height - start_y) * self.max_area_ratio
        rows, columns = np.nonzero(mask)
        for y, x in zip(rows.tolist(), columns.tolist()):
            if visited[y, x]:
                continue
            todo = deque([(x, y)])
            visited[y, x] = True
            points = []
            while todo:
                px, py = todo.popleft()
                points.append((px, py))
                for nx, ny in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
                    if 0 <= nx < width and start_y <= ny < height and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        todo.append((nx, ny))
            area = len(points)
            if not self.min_area <= area <= max_area:
                continue
            xy = np.asarray(points)
            xs, ys = xy[:, 0], xy[:, 1]
            # Boundary clipping makes the shape/center unreliable.
            if xs.min() == 0 or xs.max() == width - 1 or ys.min() <= start_y or ys.max() == height - 1:
                continue
            values = pixels[ys, xs]
            if np.mean(values >= 254) > 0.90:
                continue
            local_contrast = float(np.mean(difference[ys, xs]))
            weights = np.maximum(difference[ys, xs], 1)
            cx, cy = float(np.average(xs, weights=weights)), float(np.average(ys, weights=weights))
            quality = min(1.0, 0.5 + max(0, local_contrast) / 255)
            if quality < self.confidence_threshold:
                continue
            bbox = {'x': int(xs.min()), 'y': int(ys.min()),
                    'width': int(xs.max() - xs.min() + 1), 'height': int(ys.max() - ys.min() + 1)}
            candidates.append({'bbox_px': bbox, 'target_px': {'x': cx, 'y': cy},
                               'quality': quality, 'area_px': area,
                               'mean_brightness': float(values.mean()), 'local_contrast': local_contrast})
        candidates.sort(key=lambda item: item['quality'], reverse=True)
        state, reason, chosen = 'searching', 'no_candidate', None
        if candidates:
            pool = candidates
            if self.previous is not None:
                near = [item for item in candidates if math.hypot(
                    (item['target_px']['x'] - self.previous[0]) / width,
                    (item['target_px']['y'] - self.previous[1]) / height) <= self.max_jump]
                if near:
                    pool = near
            if len(pool) > 1 and pool[0]['quality'] - pool[1]['quality'] < self.ambiguity_margin:
                state, reason = 'ambiguous', 'multiple_similar_candidates'
                self.reset()
            else:
                candidate = pool[0]
                point = candidate['target_px']
                close = self.previous is not None and math.hypot(
                    (point['x'] - self.previous[0]) / width,
                    (point['y'] - self.previous[1]) / height) <= self.max_jump
                if not close:
                    self.track_id += 1
                self.confirmed = self.confirmed + 1 if close else 1
                self.previous = (point['x'], point['y'])
                if self.confirmed >= self.confirm_frames:
                    state, reason = 'tracking', ''
                    chosen = dict(candidate, track_id=self.track_id,
                                  target_normalized={'x': point['x'] / width, 'y': point['y'] / height},
                                  ground=None)
                else:
                    reason = 'confirming_candidate'
        else:
            state = 'lost' if self.previous is not None else 'searching'
            self.reset()
        self.last_target = {'schema_version': 1, 'state': state, 'reason': reason,
                            'target_valid': chosen is not None, 'target': chosen,
                            'mode': self.mode, 'ground_basis': 'lower_half_assumption',
                            'config_id': 'lower-half-v1', 'calibration_id': None,
                            'candidate_count': len(candidates)}
        draw = ImageDraw.Draw(image)
        draw.line((0, height // 2, width - 1, height // 2), fill='red', width=1)
        for item in candidates:
            box = item['bbox_px']
            draw.rectangle((box['x'], box['y'], box['x'] + box['width'] - 1,
                            box['y'] + box['height'] - 1), outline='orange', width=1)
        if chosen:
            cx, cy = chosen['target_px']['x'], chosen['target_px']['y']
            draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), outline='lime', width=2)
        output = BytesIO()
        image.save(output, format='JPEG', quality=80)
        self.last_debug = output.getvalue()
        return [Detection('bright_ground', item['quality'], **item['bbox_px']) for item in candidates]
