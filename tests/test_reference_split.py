import hashlib

from twin.reference_split import element_id, is_anchor, split_reference


def _feat(layer, token):
    return {"type": "Feature", "properties": {"layer": layer, "token": token}, "geometry": None}


def test_element_id():
    f = _feat("ped_crossing", "cw1")
    assert element_id(f) == "ped_crossing:cw1"


def test_is_anchor_deterministic():
    f = _feat("layer", "tok")
    eid = element_id(f)
    val = int(hashlib.sha256(eid.encode("utf-8")).hexdigest(), 16) % 1000
    expected = val < 700
    assert is_anchor(f, 0.7) is expected
    assert is_anchor(f) is expected


def test_split_preserves_input_order():
    feats = [_feat("a", str(i)) for i in range(20)]
    from twin.reference_split import is_anchor

    anchors, heldout, meta = split_reference(feats, 0.7)
    expected_anchors = [f for f in feats if is_anchor(f, 0.7)]
    assert anchors == expected_anchors
    # partition
    assert len(anchors) + len(heldout) == len(feats)
    # meta
    assert meta["ratio"] == 0.7
    assert meta["method"] == "sha256-mod-1000"
    assert meta["n_total"] == 20
    assert meta["n_anchor"] == len(anchors)
    assert meta["n_heldout"] == len(heldout)
    assert meta["holdout"] is True
    assert meta["heldout_ids"] == sorted(element_id(f) for f in heldout)


def test_counts_by_layer():
    feats = [_feat("a", "1"), _feat("a", "2"), _feat("b", "1")]
    _anchors, _heldout, meta = split_reference(feats, 0.7)
    assert meta["counts_by_layer"] == {"a": 2, "b": 1}


def test_empty():
    anchors, heldout, meta = split_reference([], 0.5)
    assert anchors == [] and heldout == []
    assert meta["n_total"] == 0
    assert meta["heldout_ids"] == []
    assert meta["ratio"] == 0.5


def test_ratio_zero_all_heldout():
    feats = [_feat("l", "t")]
    anchors, heldout, _meta = split_reference(feats, 0.0)
    assert anchors == []
    assert len(heldout) == 1


def test_ratio_one_all_anchor():
    feats = [_feat("l", "t")]
    anchors, heldout, _meta = split_reference(feats, 1.0)
    assert len(anchors) == 1
    assert heldout == []