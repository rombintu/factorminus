import pytest

from factorminus.ingest.parse import (
    parse_asset,
    parse_brand,
    parse_candles,
    parse_instrument,
    parse_risk_rates,
    to_float,
    to_msk_date,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        ({"value": "0.125"}, 0.125),
        ({"units": "3", "nano": 500000000}, 3.5),
        ({"units": 3, "nano": "500000000"}, 3.5),
        ({"units": "-1", "nano": -250000000}, -1.25),
        ({"currency": "rub", "units": "100", "nano": 0}, 100.0),
        ({"nano": 10000000}, 0.01),
        ("12.5", 12.5),
        ("12,5", 12.5),
        (7, 7.0),
        (0.3, 0.3),
        (None, None),
        ("", None),
        ({}, None),
    ],
)
def test_to_float(value, expected):
    assert to_float(value) == (pytest.approx(expected) if expected is not None else None)


def test_to_float_rejects_garbage():
    with pytest.raises(ValueError):
        to_float("abc")


@pytest.mark.parametrize(
    "ts,expected",
    [
        ("2026-11-20T21:00:00Z", "2026-11-21"),
        ("2026-11-20T20:59:59Z", "2026-11-20"),
        ("2026-11-20T07:00:00.000000Z", "2026-11-20"),
        ("2026-11-20T07:00:00+00:00", "2026-11-20"),
        ("2026-11-20", "2026-11-20"),
        (None, None),
        ("", None),
    ],
)
def test_to_msk_date(ts, expected):
    assert to_msk_date(ts) == expected


SHARE = {
    "instrument": {
        "uid": "uid-1",
        "ticker": "SYN_A",
        "classCode": "SYN",
        "isin": "RU000SYN0001",
        "lot": 10,
        "currency": "rub",
        "name": "Синтетика А",
        "assetUid": "asset-1",
        "positionUid": "pos-1",
        "first1dayCandleDate": "2020-01-03T07:00:00Z",
        "dlongClient": {"units": "0", "nano": 250000000},
        "dshortClient": {"value": "0.3"},
        "apiTradeAvailableFlag": True,
    }
}


def test_parse_share():
    row = parse_instrument(SHARE, "share")
    assert "instrument_id" not in row  # id задаёт вселенная, а не карточка
    assert row["ticker"] == "SYN_A"
    assert row["class_code"] == "SYN"
    assert row["uid"] == "uid-1"
    assert row["lot"] == 10
    assert row["asset_uid"] == "asset-1"
    assert row["first_day_candle"] == "2020-01-03"
    assert row["dlong"] == 0.25
    assert row["dshort"] == 0.3
    assert row["api_trade_flag"] == 1
    assert row["maturity_date"] is None


def test_parse_bond_maturity_and_bare_root():
    bond = dict(SHARE["instrument"], maturityDate="2031-03-15T00:00:00Z", dlong=None)
    bond.pop("dlongClient")
    row = parse_instrument(bond, "bond")  # без обёртки "instrument"
    assert row["maturity_date"] == "2031-03-15"
    assert row["dlong"] is None


def test_parse_instrument_requires_ticker():
    with pytest.raises(ValueError):
        parse_instrument({"instrument": {"name": "x"}}, "share")


def test_parse_asset_and_brand():
    asset = parse_asset({"asset": {"uid": "a1", "name": "ПАО Тест", "brand": {"uid": "b1"}}})
    assert asset == {"asset_uid": "a1", "name": "ПАО Тест", "brand_uid": "b1"}
    brand = parse_brand(
        {
            "brand": {
                "uid": "b1",
                "name": "Тест",
                "company": "ПАО Тест",
                "sector": "energy",
                "description": "Нефть",
                "countryOfRisk": "RU",
            }
        }
    )
    assert brand["brand_uid"] == "b1"
    assert brand["sector"] == "energy"
    assert brand["country_of_risk"] == "RU"
    assert parse_brand({"uid": "b2"})["sector"] is None


def test_parse_candles():
    payload = {
        "candles": [
            {
                "time": "2024-01-02T21:00:00Z",
                "open": {"value": "1"},
                "high": {"value": "2"},
                "low": {"value": "0.5"},
                "close": {"units": "1", "nano": 500000000},
                "volume": "100",
                "isComplete": True,
            },
            {"time": "2024-01-03T21:00:00Z", "close": None},
        ]
    }
    rows = parse_candles(payload)
    assert rows == [
        {"date": "2024-01-03", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0}
    ]
    assert parse_candles({}) == []


def test_parse_risk_rates_real_shape():
    # форма реального ответа (24.11.2026): списки по уровням риска, порядок как в запросе
    payload = {
        "instrumentRiskRates": [
            {
                "instrumentUid": "uid-1",
                "longRiskRates": [
                    {"riskLevelCode": "HIGH", "value": {"value": "0.125"}},
                    {"riskLevelCode": "STANDARD", "value": {"value": "0.2"}},
                ],
                "shortRiskRates": [
                    {"riskLevelCode": "HIGH", "value": {"value": "0.1428"}},
                    {"riskLevelCode": "STANDARD", "value": {"units": "0", "nano": 250000000}},
                ],
            },
            {"instrumentUid": "", "longRiskRates": [], "shortRiskRates": []},
        ]
    }
    assert parse_risk_rates(payload) == [
        {
            "uid": "uid-1",
            "long": {"HIGH": 0.125, "STANDARD": 0.2},
            "short": {"HIGH": 0.1428, "STANDARD": 0.25},
        },
        {"uid": None, "long": {}, "short": {}},
    ]
    assert parse_risk_rates({}) == []
