from __future__ import annotations

from importlib.resources import files


def test_packaged_plan_template_present():
    template = files("autoloop").joinpath("templates/plan_producer.md")
    assert template.is_file()
