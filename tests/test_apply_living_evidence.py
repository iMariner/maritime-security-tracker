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


@pytest.mark.parametrize("minimum", [True, False])
def test_accepts_boolean_minimum_and_preserves_audited_claim(minimum):
    event, overlay, incidents = fixture()
    payload = json.loads(event["comment"]["body"].split("\n", 1)[1])
    payload["casualties"]["minimum"] = minimum
    event["comment"]["body"] = "/evidence\n" + json.dumps(payload)
    result = apply_event(event, overlay, incidents)
    assert result["incidents"]["inc-1"]["casualties"]["minimum"] is minimum
    assert result["audit"][0]["change"]["casualties"]["minimum"] is minimum


@pytest.mark.parametrize("minimum", ["true", "false", 1, 0, None])
def test_rejects_nonboolean_minimum(minimum):
    event, overlay, incidents = fixture()
    payload = json.loads(event["comment"]["body"].split("\n", 1)[1])
    payload["casualties"]["minimum"] = minimum
    event["comment"]["body"] = "/evidence\n" + json.dumps(payload)
    with pytest.raises(ValueError, match="minimum must be a boolean"):
        apply_event(event, overlay, incidents)


@pytest.mark.parametrize("history_present", [True, False])
def test_cli_accepts_historical_and_existing_ids(tmp_path, monkeypatch, history_present):
    from tracker import apply_living_evidence as command
    event, _, incidents = fixture()
    (tmp_path / "data").mkdir()
    (tmp_path / "data/incidents.json").write_text(json.dumps([] if history_present else incidents))
    if history_present:
        (tmp_path / "data/living-history.json").write_text(json.dumps(incidents))
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event))
    monkeypatch.setattr(command, "ROOT", tmp_path)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    command.main()
    result = json.loads((tmp_path / "data/living-evidence.json").read_text())
    assert result["incidents"]["inc-1"]["casualties"]["deaths"] == 1
    assert json.loads((tmp_path / "data/incidents.json").read_text()) == ([] if history_present else incidents)


def test_cli_history_duplicate_cannot_override_rejected_original(tmp_path, monkeypatch):
    from tracker import apply_living_evidence as command
    event, _, incidents = fixture()
    payload = json.loads(event["comment"]["body"].split("\n", 1)[1])
    payload["verification"] = reviewed()
    event["comment"]["body"] = "/evidence\n" + json.dumps(payload)
    (tmp_path / "data").mkdir()
    (tmp_path / "data/incidents.json").write_text(json.dumps([{**incidents[0], "status": "merged"}]))
    (tmp_path / "data/living-history.json").write_text(json.dumps(incidents))
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event))
    monkeypatch.setattr(command, "ROOT", tmp_path)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    with pytest.raises(SystemExit, match="Cannot verify nonpublic"):
        command.main()
    assert not (tmp_path / "data/living-evidence.json").exists()


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


def historical_event():
    event, overlay, _ = fixture()
    payload = json.loads(event["comment"]["body"].split("\n", 1)[1])
    payload.update(incident_id="HIST-BLACK-20220302-TEST", historical=True,
                   verification={**reviewed(), "region": "Black Sea"})
    event["comment"]["body"] = "/evidence\n" + json.dumps(payload)
    return event, overlay, payload


def run_cli(tmp_path, monkeypatch, event, incidents=None):
    from tracker import apply_living_evidence as command
    (tmp_path / "data").mkdir(exist_ok=True)
    if not (tmp_path / "data/incidents.json").exists():
        (tmp_path / "data/incidents.json").write_text(json.dumps(incidents or []))
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event))
    monkeypatch.setattr(command, "ROOT", tmp_path)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    command.main()


def test_cli_creates_reviewed_history_once_without_mutating_original(tmp_path, monkeypatch):
    event, _, payload = historical_event()
    run_cli(tmp_path, monkeypatch, event)
    history_path = tmp_path / "data/living-history.json"
    evidence_path = tmp_path / "data/living-evidence.json"
    history = json.loads(history_path.read_text())
    assert history == [{"id": payload["incident_id"], "status": "reported", "vessel_category": "merchant", "region": "Black Sea", "vessel_type": "Bulk carrier"}]
    evidence = json.loads(evidence_path.read_text())
    assert evidence["audit"][0]["change"]["historical"] is True
    before = (history_path.read_bytes(), evidence_path.read_bytes())
    run_cli(tmp_path, monkeypatch, event)
    assert (history_path.read_bytes(), evidence_path.read_bytes()) == before
    assert json.loads((tmp_path / "data/incidents.json").read_text()) == []


@pytest.mark.parametrize("change", [
    {"historical": "true"}, {"historical": 1}, {"historical": False},
    {"verification": None}, {"verification": {**reviewed(), "region": "Pacific"}},
    {"verification": reviewed()}, {"incident_id": "../HIST-bad"},
    {"incident_id": "inc-new"}, {"incident_id": ["HIST-bad"]},
])
def test_invalid_creation_leaves_no_history_or_evidence(tmp_path, monkeypatch, change):
    event, _, payload = historical_event()
    payload.update(change)
    event["comment"]["body"] = "/evidence\n" + json.dumps(payload)
    with pytest.raises(SystemExit):
        run_cli(tmp_path, monkeypatch, event)
    assert not (tmp_path / "data/living-history.json").exists()
    assert not (tmp_path / "data/living-evidence.json").exists()


def test_untrusted_creation_cannot_persist_candidate(tmp_path, monkeypatch):
    event, _, _ = historical_event()
    event["comment"]["author_association"] = "NONE"
    with pytest.raises(SystemExit, match="Only trusted"):
        run_cli(tmp_path, monkeypatch, event)
    assert not (tmp_path / "data/living-history.json").exists()
    assert not (tmp_path / "data/living-evidence.json").exists()


def test_historical_flag_cannot_replace_rejected_original(tmp_path, monkeypatch):
    event, _, payload = historical_event()
    with pytest.raises(SystemExit, match="Cannot verify nonpublic"):
        run_cli(tmp_path, monkeypatch, event, [{"id": payload["incident_id"], "status": "merged"}])
    assert not (tmp_path / "data/living-history.json").exists()


def test_historical_flag_on_existing_id_does_not_create_stub(tmp_path, monkeypatch):
    event, _, payload = historical_event()
    run_cli(tmp_path, monkeypatch, event, [{"id": payload["incident_id"], "status": "reported", "region": "Black Sea"}])
    assert not (tmp_path / "data/living-history.json").exists()
    assert json.loads((tmp_path / "data/living-evidence.json").read_text())["incidents"][payload["incident_id"]]["verification"] == payload["verification"]
