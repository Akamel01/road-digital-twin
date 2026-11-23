"""knn_points stand-in (only the SMPL paths use it; brute force with torch.cdist)."""
import torch


def knn_points(p1, p2, K=1, return_nn=False, **_):
    d = torch.cdist(p1, p2) ** 2
    dist, idx = d.topk(K, dim=-1, largest=False)
    return dist, idx, None
