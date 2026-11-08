import pytest

from twin import fixtures


@pytest.fixture
def plane_points():
    return fixtures.make_plane(seed=0)


@pytest.fixture
def canopy_points():
    return fixtures.make_canopy(seed=1)


@pytest.fixture
def wall_points():
    return fixtures.make_wall(seed=2)


@pytest.fixture
def scene_points():
    return fixtures.make_scene(seed=0)
