from calculator import average
def test_mean():
    assert average([2,4,6]) == 4
    assert average([-2,2]) == 0
    assert average([]) == 0
