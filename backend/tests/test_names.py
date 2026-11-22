from types import SimpleNamespace

import pytest

from app.names import first_name, real_name
from app.service import _checkin_message


@pytest.mark.parametrize("value", [None, "", "   ", "App user", "app  USER"])
def test_placeholder_and_blank_names_are_unnamed(value):
    assert real_name(value) == ""
    assert first_name(value) == ""


def message(user_name):
    journey = SimpleNamespace(user_name=user_name, destination=SimpleNamespace(name="Tim Hortons"))
    return _checkin_message(journey, SimpleNamespace(reasons=[SimpleNamespace(code="off_route")]))


@pytest.mark.parametrize("value", ["App user", "   "])
def test_unnamed_checkin_is_neutral(value):
    assert message(value).startswith("Hi, you're on your way to Tim Hortons.")


def test_named_checkin_uses_first_name():
    assert message("Margaret Tremblay").startswith("Hi Margaret, you're on your way to Tim Hortons.")
