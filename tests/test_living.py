from copy import deepcopy

from tracker.living import casualties, export


def incident(id="A", **changes):
    return {"id": id, "status": "reported", "region": "Black Sea", "date_utc": "2026-10-01", "vessel_category": "merchant", "casualties": "One death reported", **changes}


def evidence(**changes):
    return {"status": "confirmed", "deaths": 1, "sources": [{"url": "https://example.com/report"}], **changes}


def review(**changes):
    return {"status": "verified", "checked_at": "2026-10-20T12:00:00Z", "sources": [{"url": "https://authority.example/report", "source": "Authority"}], "vessel_name": "Example Star", "date_utc": "2026-10-01", "vessel_type": "Bulk carrier", "summary": "Reviewed attack account", **changes}


def overlay(**entries):
    return {"schema_version": 1, "incidents": entries}


def test_public_gate_hides_unreviewed_and_old_news_without_mutation():
    records = [incident(), incident("B", latest_news="unreviewed spam", sources=[{"url": "https://spam.example"}])]
    before = deepcopy(records)
    payload = export(records, overlay(A={"verification": review()}))
    assert [i["id"] for i in payload["incidents"]] == ["A"]
    assert records == before
    assert payload["review"]["awaiting_review_count"] == 1
    assert "unreviewed spam" not in str(payload)
    assert payload["incidents"][0]["sources"][0]["source"] == "Authority"
    assert "casualties_text" not in payload["incidents"][0]


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


def test_reviewed_facts_override_corpus_and_only_overlay_history_survives():
    change = {"at": "2026-10-02T00:00:00Z", "text": "Reviewed correction", "sources": ["https://authority.example/report"]}
    record = incident(vessel_name="Unknown", latest_news="spam", updates=[{**change, "text": "unreviewed"}])
    item = export([record], overlay(A={"verification": review(date_utc="2026-09-30"), "casualties": evidence(), "updates": [change]}))["incidents"][0]
    assert item["vessel_name"] == "Example Star"
    assert item["date_utc"] == "2026-09-30"
    assert item["latest_news"] == "Reviewed attack account"
    assert item["casualties"]["deaths"] == 1
    assert [u["text"] for u in item["updates"]] == ["Reviewed correction"]


def test_invalid_or_incomplete_review_never_opens_gate():
    invalid = [None, {}, review(vessel_name="Unnamed vessel"), review(date_utc="2026-02-30"), review(checked_at="2026-10-20"), review(sources=[]), review(sources=[{"url": "https://example.com"}]), review(imo="1234568"), review(summary="")]
    for value in invalid:
        assert export([incident()], overlay(A={"verification": value}))["incidents"] == []


def test_nonpublic_and_military_remain_excluded_even_with_review():
    for changes in ({"status": "merged"}, {"status": "rejected"}, {"vessel_category": "military"}):
        assert export([incident(**changes)], overlay(A={"verification": review()}))["incidents"] == []


def test_sorting_uses_reviewed_dates_descending():
    result = export([incident("A"), incident("B")], overlay(A={"verification": review()}, B={"verification": review(date_utc="2026-10-02")}))
    assert [i["id"] for i in result["incidents"]] == ["B", "A"]


def test_malformed_nationality_collections_do_not_crash_or_invent_breakdown():
    for value in (None, "Indian", 1, {"nationality": "Indian"}):
        assert casualties(evidence(nationalities=value))["nationalities"] == []


def test_duplicate_reviewed_vessel_date_not_counted_twice():
    payload = export([incident("A"), incident("B")], overlay(A={"verification": review()}, B={"verification": review()}))
    assert len(payload["incidents"]) == 1
    assert payload["review"]["excluded_count"] == 1


def test_naive_review_updates_are_withheld_without_crashing_export():
    for stamp in ("2026-10-20", "2026-10-20T12:00:00", "2026-10-20 12:00:00+00:00"):
        item = export([incident()], overlay(A={"verification": review(), "updates": [{"at": stamp, "text": "Unsuitable time", "sources": ["https://authority.example/report"]}]}))["incidents"][0]
        assert item["updates"] == []
        assert item["last_updated"] == review()["checked_at"]


def test_review_update_order_compares_instants_across_timezones():
    changes = [{"at": stamp, "text": "Reviewed", "sources": ["https://authority.example/report"]} for stamp in ("2026-10-20T15:00:00+05:30", "2026-10-20T10:00:00Z")]
    item = export([incident()], overlay(A={"verification": review(), "updates": changes}))["incidents"][0]
    assert item["updates"][0]["at"] == "2026-10-20T10:00:00Z"
