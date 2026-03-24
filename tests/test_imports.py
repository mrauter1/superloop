from __future__ import annotations


def test_package_imports():
    import autoloop.main
    import autoloop.autoloop
    import autoloop.loop_control  # noqa: F401

    assert autoloop.autoloop.main is autoloop.main.main
