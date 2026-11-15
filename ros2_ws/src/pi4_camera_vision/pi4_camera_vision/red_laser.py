"""Small red floor spots, including a white core attached to red pixels."""
from collections import deque

import numpy as np
from PIL import ImageFilter

from .bright_ground import BrightGroundDetector


class RedLaserDetector(BrightGroundDetector):
    def __init__(self):
        super().__init__()
        self.mode = 'red_laser_spot'
        self.label = 'red_laser_spot'
        self.red_min = 100
        self.red_excess = 25
        self.red_contrast = 20
        self.max_laser_area_ratio = 0.001

    def _find_candidates(self, image, width, height):
        rgb = np.asarray(image, dtype=np.float32)
        red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
        red_background = np.asarray(image.getchannel('R').filter(ImageFilter.BoxBlur(5)), dtype=np.float32)
        excess = red - np.maximum(green, blue)
        contrast = red - red_background
        seeds = (red >= self.red_min) & (excess >= self.red_excess) & (contrast >= self.red_contrast)
        gray = image.convert('L')
        light = np.asarray(gray, dtype=np.float32)
        background = np.asarray(gray.filter(ImageFilter.BoxBlur(5)), dtype=np.float32)
        # Only white components CONNECTED to a red seed can become a target.
        white = (np.minimum(np.minimum(red, green), blue) >= 160) & (light - background >= 25)
        mask = seeds | white
        horizon = height // 2
        mask[:horizon] = False
        visited = np.zeros(mask.shape, dtype=bool)
        rows, cols = np.nonzero(seeds & mask)
        candidates = []
        max_area = max(4, width * height * self.max_laser_area_ratio)
        for y, x in zip(rows.tolist(), cols.tolist()):
            if visited[y, x]:
                continue
            queue = deque([(x, y)])
            visited[y, x] = True
            points = []
            while queue:
                px, py = queue.popleft()
                points.append((px, py))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx, ny = px + dx, py + dy
                        if 0 <= nx < width and horizon <= ny < height and mask[ny, nx] and not visited[ny, nx]:
                            visited[ny, nx] = True
                            queue.append((nx, ny))
            if len(points) > max_area:
                continue
            xy = np.asarray(points)
            xs, ys = xy[:, 0], xy[:, 1]
            x0, y0 = int(xs.min()), int(ys.min())
            bw, bh = int(xs.max() - x0 + 1), int(ys.max() - y0 + 1)
            if x0 == 0 or y0 <= horizon or x0 + bw == width or y0 + bh == height:
                continue
            if max(bw, bh) > 3 * min(bw, bh):
                continue
            red_pixels = seeds[ys, xs]
            strength = float(excess[ys[red_pixels], xs[red_pixels]].mean())
            local = float(contrast[ys[red_pixels], xs[red_pixels]].mean())
            quality = min(1.0, 0.5 + strength / 1020 + local / 1020)
            if quality < self.confidence_threshold:
                continue
            weights = np.maximum(contrast[ys, xs], 1)
            cx, cy = float(np.average(xs, weights=weights)), float(np.average(ys, weights=weights))
            candidates.append({'bbox_px': {'x': x0, 'y': y0, 'width': bw, 'height': bh},
                               'target_px': {'x': cx, 'y': cy}, 'quality': quality,
                               'area_px': len(points), 'red_excess': strength,
                               'mean_brightness': float(light[ys, xs].mean()), 'local_contrast': local})
        return candidates
