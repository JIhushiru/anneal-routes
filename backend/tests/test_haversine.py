"""Haversine distance: known geodesics, symmetry, and matrix construction."""

import math

import pytest

from app.solver.distance import haversine_km, haversine_matrix

MANILA = (14.5995, 120.9842)
CEBU = (10.3157, 123.8854)
DAVAO = (7.1907, 125.4553)


def test_zero_distance_for_identical_points():
    assert haversine_km(*MANILA, *MANILA) == 0.0


def test_manila_to_cebu_known_distance():
    # Great-circle Manila-Cebu is ~572 km (cross-checked against geographiclib;
    # haversine on a sphere differs from the ellipsoid by well under 0.5%).
    d = haversine_km(*MANILA, *CEBU)
    assert d == pytest.approx(572, abs=6)


def test_manila_to_davao_known_distance():
    # ~957 km on the sphere, cross-checked against the spherical law of cosines
    # (agrees to 1e-9 km) and ~961 km on the WGS84 ellipsoid.
    d = haversine_km(*MANILA, *DAVAO)
    assert d == pytest.approx(957.4, abs=6)


def test_small_distance_precision():
    # 0.001 deg of latitude is ~111.2 m everywhere; the haversine form must not
    # lose this to floating-point cancellation (the law-of-cosines form would).
    d = haversine_km(14.5995, 120.9842, 14.6005, 120.9842)
    assert d == pytest.approx(0.1112, abs=0.0005)


def test_symmetry():
    assert haversine_km(*MANILA, *CEBU) == pytest.approx(haversine_km(*CEBU, *MANILA), abs=1e-12)


def test_triangle_inequality():
    ab = haversine_km(*MANILA, *CEBU)
    bc = haversine_km(*CEBU, *DAVAO)
    ac = haversine_km(*MANILA, *DAVAO)
    assert ac <= ab + bc + 1e-9


def test_matrix_shape_diagonal_and_symmetry():
    coords = [MANILA, CEBU, DAVAO]
    m = haversine_matrix(coords)
    assert len(m) == 3 and all(len(row) == 3 for row in m)
    for i in range(3):
        assert m[i][i] == 0.0
        for j in range(3):
            assert m[i][j] == pytest.approx(m[j][i], abs=1e-12)
    assert m[0][1] == pytest.approx(haversine_km(*MANILA, *CEBU), abs=1e-12)


def test_quarter_meridian_sanity():
    # Equator to pole along a meridian: pi/2 * R = ~10007.5 km.
    d = haversine_km(0.0, 0.0, 90.0, 0.0)
    assert d == pytest.approx(math.pi / 2 * 6371.0088, rel=1e-6)
