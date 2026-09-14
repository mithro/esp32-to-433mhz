from pulsegen import code_to_bits, bits_to_code, pwm_standard, pwm_fixed_period


def test_code_roundtrip_25_bits():
    bits = code_to_bits("c3ff3f8", 25)
    assert len(bits) == 25 and bits[:4] == [1, 1, 0, 0] and bits[-1] == 1
    assert bits_to_code(bits) == "c3ff3f8"


def test_standard_train_shape():
    us = pwm_standard("c3ff3f8")
    assert len(us) == 50                   # 25 marks + 25 spaces
    assert us[0] == 730 and us[1] == 200   # first bit is '1' -> long mark
    assert us[-1] == 7300                  # sync gap replaces last space


def test_fixed_period_train_shape():
    us = pwm_fixed_period("fa07cb8")
    assert len(us) == 50 and all(us[i] + us[i + 1] == 1340 for i in range(0, 48, 2))
    assert us[-1] == 3000
