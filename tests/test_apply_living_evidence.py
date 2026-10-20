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


def reviewed():
    return {"status": "verified", "checked_at": "2026-10-20T12:00:00Z", "vessel_name": "Test Star", "date_utc": "2026-10-19", "vessel_type": "Bulk carrier", "summary": "Attack checked against owner statement.", "sources": [{"url": "https://owner.example/report", "source": "Owner"}]}


def test_review_assertion_audited_with_previous_values():
    event, overlay, incidents = fixture()
    def submit(value):
        payload = json.loads(event["comment"]["body"].split("\n", 1)[1])
        payload["verification"] = value
        event["comment"]["body"] = "/evidence\n" + json.dumps(payload)
    submit(reviewed())
    first = apply_event(event, overlay, incidents)
    event["comment"]["id"] = 2
    submit({**reviewed(), "summary": "Corrected reviewed summary."})
    second = apply_event(event, first, incidents)
    assert second["audit"][-1]["before"]["verification"]["summary"] == reviewed()["summary"]
    assert second["incidents"]["inc-1"]["verification"]["summary"] == "Corrected reviewed summary."


@pytest.mark.parametrize("change", [{"vessel_name": "Unidentified tanker"}, {"sources": []}, {"checked_at": "yesterday"}, {"date_utc": "2026-13-10"}, {"summary": ""}])
def test_rejects_incomplete_verification(change):
    event, overlay, incidents = fixture()
    payload = json.loads(event["comment"]["body"].split("\n", 1)[1])
    payload["verification"] = {**reviewed(), **change}
    event["comment"]["body"] = "/evidence\n" + json.dumps(payload)
    with pytest.raises(ValueError):
        apply_event(event, overlay, incidents)


def test_rejected_incident_cannot_be_published_through_review():
    event, overlay, incidents = fixture()
    incidents[0]["status"] = "merged"
    payload = json.loads(event["comment"]["body"].split("\n", 1)[1])
    payload["verification"] = reviewed()
    event["comment"]["body"] = "/evidence\n" + json.dumps(payload)
    with pytest.raises(ValueError):
        apply_event(event, overlay, incidents)


@pytest.mark.parametrize("stamp", ["2026-10-20", "2026-10-20T12:00:00", "2026-10-20 12:00:00+00:00"])
def test_ingestion_rejects_updates_without_full_zoned_timestamp(stamp):
    event, overlay, incidents = fixture()
    payload = json.loads(event["comment"]["body"].split("\n", 1)[1])
    payload["update"]["at"] = stamp
    event["comment"]["body"] = "/evidence\n" + json.dumps(payload)
    with pytest.raises(ValueError):
        apply_event(event, overlay, incidents)


def test_trusted_retraction_withholds_public_record_and_preserves_review_audit():
    from tracker.living import export
    event, overlay, incidents = fixture()
    incidents[0]["region"] = "Black Sea"
    payload = json.loads(event["comment"]["body"].split("\n", 1)[1])
    payload["verification"] = reviewed()
    event["comment"]["body"] = "/evidence\n" + json.dumps(payload)
    first = apply_event(event, overlay, incidents)
    assert len(export(incidents, first)["incidents"]) == 1
    event["comment"]["id"] = 2
    payload["verification"] = None
    payload["update"]["text"] = "Review withdrawn pending clarification from owner."
    event["comment"]["body"] = "/evidence\n" + json.dumps(payload)
    second = apply_event(event, first, incidents)
    assert export(incidents, second)["incidents"] == []
    assert second["incidents"]["inc-1"]["verification"] is None
    assert second["audit"][-1]["before"]["verification"] == reviewed()
    event["comment"]["id"] = 3
    event["comment"]["author_association"] = "NONE"
    with pytest.raises(ValueError):
        apply_event(event, first, incidents)
