from copy import deepcopy

from tracker.living import casualties, export


def incident(id="A", **changes):
    return {"id": id, "status": "reported", "region": "Black Sea", "date_utc": "2026-10-01", "vessel_category": "merchant", "casualties": "One death reported", **changes}


def evidence(**changes):
    return {"status": "confirmed", "deaths": 1, "sources": [{"url": "https://example.com/report"}], **changes}


def test_only_publishable_civilian_incidents_newest_first_without_mutation():
    records = [incident("old"), incident("new", date_utc="2026-10-02"), incident("signal", status="signal"), incident("merged", status="merged"), incident("warship", vessel_type="naval frigate")]
    before = deepcopy(records)
    result = export(records)["incidents"]
    assert [i["id"] for i in result] == ["new", "old"]
    assert records == before
    assert result[0]["casualties"]["deaths"] is None
    assert result[0]["casualties_text"] == "One death reported"
    assert result[0]["updates"] == []


def test_counts_require_explicit_confirmation_real_sources_and_integer():
    for claim in [evidence(status="reported"), evidence(sources=[]), evidence(sources=[{"url": "javascript:alert(1)"}]), evidence(deaths=True), evidence(deaths=-1), evidence(deaths="1")]:
        assert casualties(claim)["deaths"] is None
    assert casualties(evidence(deaths=0))["deaths"] == 0


def test_nationalities_need_independent_explicit_support_and_consistent_total():
    indian = {"nationality": "Indian", "deaths": 1, "status": "confirmed", "sources": ["https://example.com/report"]}
    assert casualties(evidence(nationalities=[indian]))["nationalities"][0]["deaths"] == 1
    assert casualties(evidence(nationalities=[{**indian, "status": "reported"}]))["nationalities"] == []
    assert casualties(evidence(nationalities=[{**indian, "sources": []}]))["nationalities"] == []
    assert casualties(evidence(nationalities=[{**indian, "deaths": 2}]))["nationalities"] == []


def test_reviewed_overlay_updates_same_incident_without_fabricated_history():
    update = {"at": "2026-10-02T00:00:00Z", "text": "Death confirmed", "sources": ["https://example.com/report"]}
    payload = export([incident()], {"schema_version": 1, "incidents": {"A": {"casualties": evidence(), "updates": [update]}}})
    item = payload["incidents"][0]
    assert item["casualties"]["deaths"] == 1
    assert item["updates"][0]["text"] == "Death confirmed"
    assert len(item["updates"]) == 1
    assert item["date_utc"] == "2026-10-01"


def test_images_require_attribution_and_sourced_history_is_preserved():
    update = {"at": "2026-10-02T00:00:00Z", "text": "Correction", "sources": ["https://example.com/report"]}
    item = export([incident(updates=[update])], {"schema_version": 1, "incidents": {"A": {"image": {"url": "https://example.com/image.jpg"}}}})["incidents"][0]
    assert item["image"] is None
    assert item["updates"][0]["text"] == "Correction"


def test_only_known_geographies_with_explicit_hormuz_grouping():
    records = [incident("black"), incident("oman", region="Gulf of Oman"), incident("unknown", region=None), incident("other", region="Baltic Sea")]
    result = export(records)["incidents"]
    assert {i["id"] for i in result} == {"black", "oman"}
    assert next(i for i in result if i["id"] == "oman")["region_group"] == "Strait of Hormuz"


def test_existing_latest_news_reuses_timestamp_linked_evidence_only():
    stamp = "2026-10-02T00:00:00Z"
    refs = [{"url": "https://example.com/review", "published_at": stamp}, {"url": "https://example.com/old", "published_at": "2026-10-01T00:00:00Z"}]
    item = export([incident(latest_news="Crew rescued", news_changed_at=stamp, sources=refs)])["incidents"][0]
    assert len(item["updates"]) == 1
    assert item["updates"][0]["sources"][0]["url"] == "https://example.com/review"
    assert len(item["updates"][0]["sources"]) == 1
    assert export([incident(news_changed_at=stamp, sources=refs)])["incidents"][0]["updates"] == []
    assert export([incident(latest_news="Crew rescued", news_changed_at=stamp, sources=refs[1:])])["incidents"][0]["updates"] == []


def test_malformed_nationality_collections_do_not_crash_or_invent_breakdown():
    for value in (None, "Indian", 1, {"nationality": "Indian"}):
        assert casualties(evidence(nationalities=value))["nationalities"] == []
