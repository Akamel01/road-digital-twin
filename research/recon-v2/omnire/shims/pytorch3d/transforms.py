"""Minimal stand-in for the two pytorch3d.transforms functions drivestudio uses (no nvcc on the box to build pytorch3d)."""
import torch
import torch.nn.functional as F


def quaternion_to_matrix(q: torch.Tensor) -> torch.Tensor:
    r, i, j, k = torch.unbind(q, -1)
    two_s = 2.0 / (q * q).sum(-1)
    o = torch.stack((
        1 - two_s * (j * j + k * k), two_s * (i * j - k * r), two_s * (i * k + j * r),
        two_s * (i * j + k * r), 1 - two_s * (i * i + k * k), two_s * (j * k - i * r),
        two_s * (i * k - j * r), two_s * (j * k + i * r), 1 - two_s * (i * i + j * j),
    ), -1)
    return o.reshape(q.shape[:-1] + (3, 3))


def _sqrt_positive_part(x):
    ret = torch.zeros_like(x)
    m = x > 0
    ret[m] = torch.sqrt(x[m])
    return ret


def matrix_to_quaternion(matrix: torch.Tensor) -> torch.Tensor:
    batch = matrix.shape[:-2]
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = torch.unbind(matrix.reshape(batch + (9,)), -1)
    q_abs = _sqrt_positive_part(torch.stack([
        1.0 + m00 + m11 + m22, 1.0 + m00 - m11 - m22, 1.0 - m00 + m11 - m22, 1.0 - m00 - m11 + m22], -1))
    quat_by_rijk = torch.stack([
        torch.stack([q_abs[..., 0] ** 2, m21 - m12, m02 - m20, m10 - m01], -1),
        torch.stack([m21 - m12, q_abs[..., 1] ** 2, m10 + m01, m02 + m20], -1),
        torch.stack([m02 - m20, m10 + m01, q_abs[..., 2] ** 2, m12 + m21], -1),
        torch.stack([m10 - m01, m20 + m02, m21 + m12, q_abs[..., 3] ** 2], -1),
    ], -2)
    cands = quat_by_rijk / (2.0 * q_abs[..., None].max(q_abs.new_tensor(0.1)))
    out = cands[F.one_hot(q_abs.argmax(-1), 4) > 0.5, :].reshape(batch + (4,))
    return torch.where(out[..., 0:1] < 0, -out, out)


def axis_angle_to_matrix(axis_angle: torch.Tensor) -> torch.Tensor:
    angles = torch.norm(axis_angle, p=2, dim=-1, keepdim=True)
    half = angles * 0.5
    eps = 1e-6
    small = angles.abs() < eps
    s = torch.empty_like(angles)
    s[~small] = torch.sin(half[~small]) / angles[~small]
    s[small] = 0.5 - (angles[small] * angles[small]) / 48
    q = torch.cat([torch.cos(half), axis_angle * s], dim=-1)
    return quaternion_to_matrix(q)
