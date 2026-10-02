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
