"""Neutral pose helpers (no stage/GPU dependencies).

`pose_report` is shared by splats and (later) the colour stage. Keep it free of torch/cupy.
"""

from collections import Counter
from typing import Any, Protocol

import numpy as np


class PoseParams(Protocol):
    """Structural params exposing the pose-correction thresholds."""

    pose_flag_deg: float
    pose_flag_m: float
    pose_max_deg: float
    pose_max_m: float


def pose_report(deltas: np.ndarray, names: list[str], p: Any, info: Any = None) -> dict:
    """Per-camera corrections (deltas rows: rotation vector rad, translation m), summarised and flagged.

    Frozen key set: n_cameras, rotation_deg_p50, rotation_deg_p95, rotation_deg_max,
    translation_m_p50, translation_m_p95, translation_m_max, n_flagged, drive_flagged,
    by_channel; with info (one dict per camera) also applied, reason, hit_bound, reasons (count per reason) and
    n_applied.
    """
    deltas = np.asarray(deltas)
    if deltas.size == 0 or len(deltas) == 0:
        return {
            "n_cameras": 0,
            "rotation_deg_p50": None,
            "rotation_deg_p95": None,
            "rotation_deg_max": None,
            "translation_m_p50": None,
            "translation_m_p95": None,
            "translation_m_max": None,
            "n_flagged": 0,
            "drive_flagged": False,
            "by_channel": {},
            "applied": False,
            "reason": "no_cameras",
            "hit_bound": False,
            "reasons": {},
            "n_applied": 0,
        }
    deg = np.degrees(np.linalg.norm(deltas[:, :3], axis=1))
    m = np.linalg.norm(deltas[:, 3:], axis=1)
    flag_deg = getattr(p, "pose_flag_deg", 0.5)
    flag_m = getattr(p, "pose_flag_m", 0.05)
    flag = (deg > flag_deg) | (m > flag_m)
    by_ch: dict[str, dict] = {}
    for ch in sorted(set(names)):
        s = np.array([n == ch for n in names])
        if not s.any():
            continue
        by_ch[ch] = {
            "median_deg": round(float(np.median(deg[s])), 4),
            "median_m": round(float(np.median(m[s])), 4),
        }
    result = {
        "n_cameras": len(deg),
        "rotation_deg_p50": round(float(np.percentile(deg, 50)), 4),
        "rotation_deg_p95": round(float(np.percentile(deg, 95)), 4),
        "rotation_deg_max": round(float(deg.max()), 4),
        "translation_m_p50": round(float(np.percentile(m, 50)), 4),
        "translation_m_p95": round(float(np.percentile(m, 95)), 4),
        "translation_m_max": round(float(m.max()), 4),
        "n_flagged": int(flag.sum()),
        "drive_flagged": bool(flag.mean() >= 0.25),
        "by_channel": by_ch,
    }
    if info is not None:
        # One info per camera frame (colour_pose.refine_one). applied / hit_bound: any frame; reason: "converged"
        # when every frame applied its correction, otherwise the commonest reason a frame kept its calibrated pose.
        reasons = Counter(i["reason"] for i in info)
        failed = Counter({k: v for k, v in reasons.items() if k != "converged"})
        result.update(
            applied=any(i["applied"] for i in info),
            hit_bound=any(i["hit_bound"] for i in info),
            reason=failed.most_common(1)[0][0] if failed else "converged",
            reasons=dict(sorted(reasons.items())),
            n_applied=sum(i["applied"] for i in info),
        )
    return result
