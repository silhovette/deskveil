import unittest
import numpy as np
from ui.rain import visible_shapes
from ui.rain_shaders import FRAGMENT


class RainRenderingTests(unittest.TestCase):
    def test_fragment_shader_declares_drop_radii_varying(self):
        self.assertIn('varying vec2 radii;', FRAGMENT)

    def test_falling_trails_have_no_side_edge_glow(self):
        self.assertNotIn('edgeGlow', FRAGMENT)
        self.assertNotIn('filmGradient', FRAGMENT)
        self.assertNotIn('contact *= mix(1., .94, trail)', FRAGMENT)

    def test_highlight_strength_is_size_dependent(self):
        self.assertIn('float dropRadius = min(radii.x,radii.y);', FRAGMENT)
        self.assertIn('float sizeHighlight = dropRadius <= 4.5 ? .20 : mix(.60,1.25,smoothstep(4.5,14.,dropRadius));', FRAGMENT)
        self.assertIn('highlight*sizeHighlight*1.70', FRAGMENT)

    def test_culling_keeps_rotated_and_edge_crossing_quads_in_order(self):
        shapes = np.array([
            (150, 150, 2, 2, 1, 0, 0, 0, 1, 0),  # Center.
            (0, 0, 2, 2, 1, 0, 0, 0, 1, 0),      # Outside.
            (90, 150, 10, 2, 1, 0, 0, 0, 1, 0),  # Crosses left edge.
            (60, 150, 2, 40, 0, 1, 0, 1, 1, 0),  # Rotated long trail.
            (150, 240, 2, 40, 1, 0, 0, 1, 1, 0), # Crosses bottom edge.
            (250, 250, 2, 2, 1, 0, 0, 0, 1, 0),  # Outside.
        ], dtype=np.float32)
        np.testing.assert_array_equal(visible_shapes(shapes, 300, 300, 3),
                                      shapes[[0, 2, 3, 4]])
        self.assertEqual(visible_shapes(shapes[:0], 300, 300, 3).shape, (0, 10))

    def test_culling_never_removes_a_quad_whose_bounds_touch_viewport(self):
        rng = np.random.default_rng(19)
        shapes = rng.uniform(-500, 1500, (2000, 10)).astype(np.float32)
        shapes[:, 2:4] = rng.uniform(.1, 200, (2000, 2))
        angle = rng.uniform(-np.pi, np.pi, 2000)
        shapes[:, 4], shapes[:, 5] = np.cos(angle), np.sin(angle)
        shapes[:, 6] = np.arange(2000)
        corners = np.array([[-1.2, -1.2], [-1.2, 1.2], [1.2, -1.2], [1.2, 1.2]])
        for width, height, scale in [(1280, 800, 3), (800, 1200, 1), (640, 480, 2)]:
            kept = set(visible_shapes(shapes, width, height, scale)[:, 6])
            for shape in shapes:
                local = corners * shape[2:4]
                rotation = np.array([[shape[4], -shape[5]], [shape[5], shape[4]]])
                points = ((local @ rotation.T + shape[:2]) - (width/2, height/2)) * scale + (width/2, height/2)
                intersects = (points[:, 0].max() >= 0 and points[:, 0].min() <= width and
                              points[:, 1].max() >= 0 and points[:, 1].min() <= height)
                if intersects:
                    self.assertIn(shape[6], kept)
