"""Pure-torch stand-in for nvdiffrast.torch.texture with boundary_mode="cube" (EnvLight sky).

No nvcc on the box to build nvdiffrast. The sky cube map is learned from scratch, so only a consistent,
differentiable direction-to-texel mapping matters; this uses the OpenGL cube face convention with bilinear
sampling per face (no filtering across face seams)."""
import torch
import torch.nn.functional as F


def texture(tex, uv, filter_mode="linear", boundary_mode="cube", **_):
    assert boundary_mode == "cube"
    base = tex[0]  # [6, R, R, C]
    shp = uv.shape[:-1]
    d = uv.reshape(-1, 3)
    x, y, z = d.unbind(-1)
    ax, ay, az = x.abs(), y.abs(), z.abs()
    face = torch.where((ax >= ay) & (ax >= az), torch.where(x > 0, 0, 1),
                       torch.where(ay >= az, torch.where(y > 0, 2, 3), torch.where(z > 0, 4, 5)))
    ma = torch.stack([ax, ax, ay, ay, az, az], -1).gather(-1, face[:, None])[:, 0].clamp_min(1e-8)
    sc = torch.stack([-z, z, x, x, x, -x], -1).gather(-1, face[:, None])[:, 0]
    tc = torch.stack([-y, -y, z, -z, -y, -y], -1).gather(-1, face[:, None])[:, 0]
    s, t = sc / ma, tc / ma  # [-1, 1]
    out = d.new_zeros(d.shape[0], base.shape[-1])
    mode = "bilinear" if filter_mode == "linear" else "nearest"
    for f in range(6):
        m = face == f
        if m.any():
            g = torch.stack([s[m], t[m]], -1)[None, None]
            img = base[f].permute(2, 0, 1)[None]
            out[m] = F.grid_sample(img, g, mode=mode, padding_mode="border", align_corners=False)[0, :, 0].T
    return out.reshape(*shp, -1)
