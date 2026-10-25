from datetime import date, time

import pytest
from pydantic import ValidationError

from fateweave.domain.calendar import BirthInputError, normalize_birth
from fateweave.models.inputs import BirthProfileInput


def make(**kw):
    base = {"birth_date": date(1990, 1, 1), "calendar": "solar", "gender_for_daewoon": "female"}
    base.update(kw)
    return BirthProfileInput(**base)


def test_known_leap_conversion():
    n = normalize_birth(make(birth_date=date(2017, 5, 1), calendar="lunar", leap_month=True))
    assert n.solar_date == date(2017, 6, 24)
    assert n.calendar == "lunar"
    assert n.leap_month is True
    assert n.original.birth_date == date(2017, 5, 1)


def test_lunar_non_leap_conversion():
    n = normalize_birth(make(birth_date=date(2017, 5, 1), calendar="lunar"))
    assert n.solar_date == date(2017, 5, 26)


def test_solar_passthrough():
    n = normalize_birth(make(birth_date=date(1990, 3, 4)))
    assert n.solar_date == date(1990, 3, 4)
    assert n.leap_month is False


def test_invalid_leap_rejected():
    with pytest.raises(BirthInputError) as e:
        normalize_birth(make(birth_date=date(2017, 6, 1), calendar="lunar", leap_month=True))
    assert e.value.code == "INVALID_LUNAR_DATE"


def test_invalid_lunar_day_rejected():
    with pytest.raises(BirthInputError) as e:
        normalize_birth(make(birth_date=date(2017, 1, 30), calendar="lunar"))
    assert e.value.code == "INVALID_LUNAR_DATE"


def test_lunar_out_of_range_rejected():
    with pytest.raises(BirthInputError) as e:
        normalize_birth(make(birth_date=date(2051, 1, 1), calendar="lunar"))
    assert e.value.code == "UNSUPPORTED_DATE"


def test_solar_out_of_range_rejected():
    for d in (date(1000, 2, 12), date(2051, 1, 1)):
        with pytest.raises(BirthInputError) as e:
            normalize_birth(make(birth_date=d))
        assert e.value.code == "UNSUPPORTED_DATE"


def test_time_unknown_kept_null():
    n = normalize_birth(make())
    assert n.birth_time is None
    assert n.assumptions  # unknown time is recorded explicitly, not silently filled


def test_time_known_kept():
    n = normalize_birth(make(birth_time=time(7, 30), longitude=126.98))
    assert n.birth_time == time(7, 30)
    assert n.longitude == 126.98


def test_non_seoul_timezone_rejected():
    with pytest.raises(BirthInputError) as e:
        normalize_birth(make(timezone="America/New_York"))
    assert e.value.code == "UNSUPPORTED_TIMEZONE"


def test_solar_with_leap_flag_rejected():
    with pytest.raises(BirthInputError) as e:
        normalize_birth(make(leap_month=True))
    assert e.value.code == "INVALID_INPUT"


def test_models_frozen():
    n = normalize_birth(make())
    with pytest.raises(ValidationError):
        n.solar_date = date(2000, 1, 1)
