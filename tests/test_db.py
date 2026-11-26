import contextlib

import pytest

from factorminus import db


def test_upsert_rejects_injected_table():
    with contextlib.closing(db.connect(":memory:")) as conn:
        with pytest.raises(ValueError, match="таблицы"):
            db.upsert(conn, "instruments; DROP TABLE instruments", {"id": "X"})
        with pytest.raises(ValueError, match="колонки"):
            db.upsert(conn, "instruments", {"id": "X", "id FROM instruments--": 1})


def test_upsert_keeps_old_value_on_null():
    with contextlib.closing(db.connect(":memory:")) as conn:
        db.upsert(conn, "instruments", {"id": "SBER_TQBR", "name": "Сбербанк", "source": "mcp"})
        db.upsert(conn, "instruments", {"id": "SBER_TQBR", "name": None, "ticker": "SBER",
                                         "source": "mcp"})  # fmt: skip
        row = conn.execute("SELECT name, ticker FROM instruments").fetchone()
        assert (row["name"], row["ticker"]) == ("Сбербанк", "SBER")
