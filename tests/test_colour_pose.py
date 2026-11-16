"""Tests for colour_pose (CPU only)."""

# Channel fixture: tests/fixtures/ (or tests/conftest.py) for per-camera channel data; parametrize by camera channel where relevant.

import numpy as np

from twin.contracts import ColourParams
from twin.stages import colour_pose


def test_lidar_paint_edges_empty():
    arr = colour_pose.lidar_paint_edges([], None, None)
    assert arr.shape == (0, 3)


def test_tangents_shape():
    a = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
    t = colour_pose._tangents(a)
    assert t.shape == (3, 3)


def test_refine_one_no_anchors():
    base = np.eye(4)
    K = np.eye(3)
    img = np.zeros((4, 4, 3), np.uint8)
    anchors = np.zeros((0, 3))
    _corrected, _res, info = colour_pose.refine_one(base, K, img, anchors, ColourParams())
    assert info["applied"] is False
