import pytest

from avelren.surge_text import surge_body


def test_chop_exact_phrases():
    assert surge_body("surge_started", 17, "fixture") == "Почалось зростання черги на Чопі"
    assert (
        surge_body("surge_forecast", 17, "fixture") == "Можливий початок масової реєстрації на Чопі"
    )


def test_other_checkpoint_name_and_invalid_kind():
    assert surge_body("surge_started", 900, "Тест") == "Почалось зростання черги на КПП «Тест»"
    with pytest.raises(ValueError):
        surge_body("eta", 17, "fixture")


def test_all_38_queue_locations_and_both_messages():
    import json
    from pathlib import Path

    rows = json.loads(
        (Path(__file__).parents[1] / "fixtures/checkpoint-speech.uk.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(rows) == 38
    for row in rows:
        assert (
            surge_body("surge_started", row["id"], row["title"])
            == "Почалось зростання черги " + row["location"]
        )
        assert (
            surge_body("surge_forecast", row["id"], row["title"])
            == "Можливий початок масової реєстрації " + row["location"]
        )
