import pytest

from calculator import average, discounted_price


def test_percentage_discount():
    assert discounted_price(200, 10) == 180


def test_average():
    assert average([2, 4, 6]) == 4


def test_invalid_discount():
    with pytest.raises(ValueError):
        discounted_price(10, 101)


def test_empty_average():
    with pytest.raises(ValueError):
        average([])
