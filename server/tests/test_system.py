from app.system import compute_smoke_test, library_versions


def test_compute_stack_works():
    assert compute_smoke_test() is True


def test_talib_version_is_pinned():
    assert library_versions()["talib"].startswith("0.8")
