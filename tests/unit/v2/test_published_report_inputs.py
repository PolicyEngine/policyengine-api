"""What an author may send when publishing a saved report or editing its page.

Authors and tags are IDs from the website's ``authors.json`` and tag lists,
checked for form only; output cards are named by keys v3 defines, each at
most once. A page holds at most 100 blocks, each Markdown block at most
20,000 characters, and a summary of 1 to 300 characters.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from policyengine_api.services.v2.published_reports.types import (
    PublicationCreateInput,
    PublicationUpdateInput,
)
from tests.unit.v2.published_report_support import publication_body, without_run


def _markdown(text: str) -> dict[str, str]:
    return {"type": "markdown", "markdown": text}


def _output(key: str) -> dict[str, str]:
    return {"type": "output", "output": key}


def test_a_publication_takes_its_run_fields_and_content() -> None:
    run_id = uuid4()

    publication = PublicationCreateInput.model_validate(publication_body(run_id))

    assert publication.run_id == run_id
    assert publication.author_ids == ["nikhil-woodruff"]
    assert [block.model_dump() for block in publication.content] == [
        _markdown("## Why this reform"),
        _output("budgetary_impact"),
        _output("poverty_impact"),
    ]


def test_tags_content_and_past_versions_have_defaults() -> None:
    body = {
        key: value
        for key, value in publication_body(uuid4()).items()
        if key not in {"tags", "content", "show_past_versions"}
    }

    publication = PublicationCreateInput.model_validate(body)

    assert publication.tags == []
    assert publication.content == []
    assert publication.show_past_versions is False


def test_the_limits_themselves_are_accepted() -> None:
    publication = PublicationCreateInput.model_validate(
        publication_body(
            uuid4(),
            summary="s" * 300,
            author_ids=[f"author-{number}" for number in range(10)],
            tags=[f"tag-{number}" for number in range(20)],
            content=[_markdown("m" * 20_000)]
            + [_output(f"card_{number}") for number in range(99)],
        )
    )

    assert len(publication.content) == 100


@pytest.mark.parametrize(
    "changes",
    [
        {"summary": ""},
        {"summary": "s" * 301},
        {"author_ids": []},
        {"author_ids": [f"author-{number}" for number in range(11)]},
        {"author_ids": ["Nikhil-Woodruff"]},
        {"author_ids": ["nikhil woodruff"]},
        {"author_ids": ["nikhil--woodruff"]},
        {"author_ids": ["nikhil-woodruff", "nikhil-woodruff"]},
        {"author_ids": ["a" * 65]},
        {"tags": [f"tag-{number}" for number in range(21)]},
        {"tags": ["us_ca"]},
        {"tags": ["us", "us"]},
        {"content": [_markdown("")]},
        {"content": [_markdown("m" * 20_001)]},
        {"content": [_output("budgetary_impact")] * 2},
        {"content": [_output(f"card_{number}") for number in range(101)]},
        {"content": [_output("Budgetary_impact")]},
        {"content": [_output("1_budget")]},
        {"content": [_output("budgetary-impact")]},
        {"content": [_output("c" * 65)]},
        {"content": [{"type": "html", "html": "<script></script>"}]},
        {"content": [{**_markdown("text"), "style": "bold"}]},
        {"show_past_versions": "yes"},
        {"run_id": "615"},
        {"owner_id": str(uuid4())},
    ],
)
def test_a_malformed_publication_is_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PublicationCreateInput.model_validate({**publication_body(uuid4()), **changes})


def test_an_edit_takes_only_the_fields_sent() -> None:
    edit = PublicationUpdateInput.model_validate(
        {"tags": ["uk"], "content": [_markdown("New text")]}
    )

    assert edit.model_fields_set == {"tags", "content"}
    assert edit.tags == ["uk"]


@pytest.mark.parametrize(
    "field", ["summary", "author_ids", "tags", "content", "show_past_versions"]
)
def test_an_edit_cannot_clear_a_field(field: str) -> None:
    with pytest.raises(ValidationError, match="cannot be null"):
        PublicationUpdateInput.model_validate({field: None})


@pytest.mark.parametrize(
    "changes",
    [
        {"author_ids": []},
        {"tags": ["us", "us"]},
        {"content": [_output("budgetary_impact")] * 2},
        {"run_id": str(uuid4())},
    ],
)
def test_an_edit_is_checked_as_a_publication_is(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PublicationUpdateInput.model_validate(changes)


def test_an_edit_may_send_every_field_a_publication_has_but_its_run() -> None:
    edit = PublicationUpdateInput.model_validate(without_run(publication_body(uuid4())))

    assert edit.model_fields_set == {
        "summary",
        "author_ids",
        "tags",
        "content",
        "show_past_versions",
    }


def test_an_edit_sends_at_least_one_field() -> None:
    with pytest.raises(ValidationError, match="at least one field"):
        PublicationUpdateInput.model_validate({})
