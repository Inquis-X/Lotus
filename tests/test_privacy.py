from datetime import date
import json
from types import SimpleNamespace

import pytest

from lotus.privacy import filter_posts


def make_post(**changes):
    values = {
        "id": "POST-001",
        "mentions_minor": False,
        "mentions_third_party": False,
        "official_duties": False,
        "published": date(2025, 6, 1),
        "page_url": "https://example.invalid/synthetic",
        "text": "Синтетическая публикация",
    }
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("changes,reason", [
    ({"mentions_minor": True}, "несовершеннолетнего"),
    ({"mentions_third_party": True}, "третьем"),
    ({"official_duties": True}, "Должностные"),
    ({"published": date(2024, 1, 1)}, "года"),
    ({"page_url": "https://example.invalid/other"}, "заявленных"),
    ({"text": "Моё здоровье и лечение"}, "Специальная"),
])
def test_each_exclusion_happens_before_extraction(changes, reason):
    accepted, excluded = filter_posts([make_post(**changes)], ["https://example.invalid/synthetic"], 2025)
    assert accepted == []
    assert any(reason in text for text in excluded[0]["reasons"])
    assert set(excluded[0]) == {"post_id", "reasons"}
    assert "text" not in json.dumps(excluded)


def test_boundaries_of_report_year():
    posts = [make_post(published=date(2025, month, day), id=f"POST-{month}") for month, day in [(1, 1), (12, 31)]]
    accepted, excluded = filter_posts(posts, ["https://example.invalid/synthetic"], 2025)
    assert len(accepted) == 2 and not excluded
