from twin.geo import utm_to_latlon


def test_utm_to_latlon_test_point():
    assert utm_to_latlon(332414.0, 4690067.2) == (42.344822, -71.034536)


def test_utm_to_latlon_rounds_to_six_dp():
    lat, lon = utm_to_latlon(332414.0, 4690067.2)
    assert round(lat, 6) == lat
    assert round(lon, 6) == lon
    # second point
    lat2, lon2 = utm_to_latlon(332400.0, 4690000.0)
    assert round(lat2, 6) == lat2
    assert round(lon2, 6) == lon2
    assert len(str(lat2).split(".")[-1]) <= 6
    assert len(str(lon2).split(".")[-1]) <= 6
