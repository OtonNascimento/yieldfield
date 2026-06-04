"""Application-layer error hierarchy (§4.4)."""

from __future__ import annotations

from yieldfield.application.errors import ApplicationError, EntityNotFoundError


def test_entity_not_found_is_an_application_error() -> None:
    assert issubclass(EntityNotFoundError, ApplicationError)
    assert issubclass(ApplicationError, Exception)


def test_entity_not_found_carries_its_message() -> None:
    err = EntityNotFoundError("Finding 'f_1' not found.")
    assert str(err) == "Finding 'f_1' not found."
