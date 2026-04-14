"""Минимальный тест: без тестовых файлов pytest выходит с кодом 5 и ломает CI."""


def test_ci_smoke():
    assert True
