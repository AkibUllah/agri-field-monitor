import pytest
from django.core.exceptions import ValidationError

from apps.farms import geo
from apps.farms.models import Field
from tests.conftest import SQUARE_100M


def test_square_area_and_perimeter_within_half_percent():
    area = geo.polygon_area_m2(SQUARE_100M)
    assert area == pytest.approx(10_000, rel=0.005)
    assert geo.perimeter_m(SQUARE_100M) == pytest.approx(400, rel=0.005)


def test_triangle_and_closed_ring_and_dict_points():
    tri = [[24.0, 88.0], [24.0 + 100 / 111_320, 88.0], [24.0, 88.0 + 100 / (111_320 * 0.9135)]]
    assert geo.polygon_area_m2(tri) == pytest.approx(5_000, rel=0.01)
    closed = SQUARE_100M + [SQUARE_100M[0]]
    assert geo.polygon_area_m2(closed) == pytest.approx(geo.polygon_area_m2(SQUARE_100M))
    as_dicts = [{"lat": lat, "lng": lng} for lat, lng in SQUARE_100M]
    assert geo.validate_polygon(as_dicts) == [tuple(p) for p in SQUARE_100M]


@pytest.mark.parametrize(
    "bad",
    [
        [[24.0, 88.0], [24.1, 88.0]],
        [[24.0, 88.0], [24.1, 88.0], [24.0, 88.0]],  # closes to 2 distinct points
        [[24.0, 88.0], [24.1, 88.0], [24.1, 88.1], [24.1, 88.0]],  # duplicate
        [[95.0, 88.0], [24.1, 88.0], [24.1, 88.1]],
        [[24.0, "x"], [24.1, 88.0], [24.1, 88.1]],
        [[24.0], [24.1, 88.0], [24.1, 88.1]],
        "not a list",
    ],
)
def test_invalid_polygons(bad):
    with pytest.raises(geo.InvalidPolygonError):
        geo.validate_polygon(bad)


def test_shoelace_orientation_independent():
    xy = [(0, 0), (10, 0), (10, 5), (0, 5)]
    assert geo.shoelace_area(xy) == 50
    assert geo.shoelace_area(list(reversed(xy))) == 50
    assert geo.shoelace_area(xy[:2]) == 0


def test_unit_conversions():
    units = geo.m2_to_units(geo.SQM_PER_BIGHA)
    assert units["bigha"] == 1.0
    assert units["decimal"] == pytest.approx(33.1, abs=0.1)
    assert geo.m2_to_units(10_000)["hectare"] == 1.0
    assert geo.m2_to_units(geo.SQM_PER_ACRE)["acre"] == 1.0


@pytest.mark.django_db
def test_field_save_computes_area_centroid_and_location(field, farmer):
    assert float(field.area_m2) == pytest.approx(10_000, rel=0.005)
    assert field.centroid_lat == pytest.approx(24.3950 + 50 / 111_320, abs=1e-5)
    assert (field.union_name, field.upazila, field.district) == ("Haripur", "Paba", "Rajshahi")
    assert field.area_units["bigha"] == pytest.approx(7.47, abs=0.02)
    assert field.active_season is not None and field.active_season.variety == "BRRI dhan29"
    bad = Field(farmer=farmer, name="bad", polygon=[[1, 2]])
    with pytest.raises(ValidationError):
        bad.clean()
    with pytest.raises(geo.InvalidPolygonError):
        bad.save()
