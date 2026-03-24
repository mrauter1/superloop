from __future__ import annotations


def test_package_imports():
    import autoloop.main
    import autoloop.loop_control  # noqa: F401

    assert callable(autoloop.main.main)
