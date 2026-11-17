from calculator import clamp
def test_clamp():
    assert clamp(3,0,10) == 3
    assert clamp(-1,0,10) == 0
    assert clamp(12,0,10) == 10
