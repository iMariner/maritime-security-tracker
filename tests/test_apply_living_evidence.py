from copy import deepcopy
import json

import pytest

from tracker.apply_living_evidence import apply_event


def fixture():
    payload = {"incident_id": "inc-1", "casualties": {"status": "confirmed", "deaths": 1, "sources": ["https://owner.example/report"], "nationalities": []},
               "update": {"at": "2026-10-20T12:00:00Z", "text": "Owner confirms one death.", "sources": ["https://owner.example/report"]}}
    event = {"action": "created", "issue": {"number": 38}, "comment": {"id": 1, "author_association": "OWNER", "body": "/evidence\n" + json.dumps(payload), "user": {"login": "reviewer"}, "html_url": "https://github.com/example/repo/issues/38#issuecomment-1", "created_at": "2026-10-20T12:10:00Z"}}
    return event, {"schema_version": 1, "incidents": {}}, [{"id": "inc-1", "status": "confirmed"}]


def test_applies_idempotently_without_touching_incidents():
    event, overlay, incidents = fixture()
    original = deepcopy(incidents)
    result = apply_event(event, overlay, incidents)
    assert result["incidents"]["inc-1"]["casualties"]["deaths"] == 1
    assert len(result["audit"]) == 1
    assert apply_event(event, result, incidents) == result
    assert incidents == original
    assert overlay == {"schema_version": 1, "incidents": {}}


def test_correction_preserves_prior_claim_and_update():
    event, overlay, incidents = fixture()
    first = apply_event(event, overlay, incidents)
    payload = json.loads(event["comment"]["body"].split("\n", 1)[1])
    payload["casualties"]["deaths"] = 0
    payload["update"]["text"] = "Owner corrected death report."
    event["comment"]["id"] = 2
    event["comment"]["body"] = "/evidence\n" + json.dumps(payload)
    result = apply_event(event, first, incidents)
    assert result["incidents"]["inc-1"]["casualties"]["deaths"] == 0
    assert result["audit"][1]["before"]["casualties"]["deaths"] == 1
    assert len(result["incidents"]["inc-1"]["updates"]) == 2


@pytest.mark.parametrize("association", ["NONE", "CONTRIBUTOR", "FIRST_TIMER"])
def test_rejects_untrusted_authors(association):
    event, overlay, incidents = fixture()
    event["comment"]["author_association"] = association
    with pytest.raises(ValueError):
        apply_event(event, overlay, incidents)


@pytest.mark.parametrize("change", [
    {"incident_id": "missing"},
    {"casualties": {"status": "confirmed", "deaths": True, "sources": ["https://owner.example/report"]}},
    {"casualties": {"status": "confirmed", "deaths": 1, "sources": []}},
    {"update": {"at": "invalid", "text": "Test", "sources": ["https://owner.example/report"]}},
    {"image": {"url": "javascript:bad", "source_url": "https://example.com", "alt": "Photo", "credit": "Owner"}},
])
def test_rejects_invalid_claims(change):
    event, overlay, incidents = fixture()
    value = json.loads(event["comment"]["body"].split("\n", 1)[1])
    value.update(change)
    event["comment"]["body"] = "/evidence\n" + json.dumps(value)
    with pytest.raises(ValueError):
        apply_event(event, overlay, incidents)
