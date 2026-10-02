from datetime import datetime, timezone

from tracker import apply_verdict, incidents as store
from tracker.brief import incident_html, select
from tracker.collectors.firms import classify, point_in_polygon
from tracker.common import load_yaml, no_em_dash
from tracker.prefilter import is_candidate


def src(url, side="ua", kind="official", source="Ukrainian Navy"):
    return {"url": url, "source": source, "source_type": "telegram", "side": side, "kind": kind,
            "published_at": "2026-10-01T10:00:00Z", "title": None}


def report(**kw):
    base = {"region": "Black Sea", "vessel_name": None, "imo": None, "date_utc": "2026-10-01T08:00:00Z",
            "summary": "Ukraine's navy said a drone hit a bulk carrier.", "confidence": 0.8, "source": src("https://t.me/a/1")}
    base.update(kw)
    return base


def test_prefilter_word_start():
    assert is_candidate({"title": "", "text": "Drone strike hits tanker near Novorossiysk"})
    assert not is_candidate({"title": "", "text": "The report shows support for a ceasefire"})
    assert is_candidate({"title": "", "text": "Безекіпажний катер атакував танкер"})
    assert not is_candidate({"title": "Tanker rates climb", "text": "Freight market report", "require_region_term": True})


def test_merge_by_name_and_status_ladder():
    incs = []
    a, new = store.merge(report(vessel_name="MV Kairos"), incs)
    assert new and a["status"] == "claimed"
    b, new = store.merge(report(vessel_name="KAIROS", source=src("https://t.me/b/2", side="ru", source="Russian MoD")), incs)
    assert not new and b is a and a["status"] == "reported"  # both sides agree something happened
    store.merge(report(vessel_name="Kairos", official_source_cited="UKMTO", source=src("https://x.com/n", side="neutral", kind="media", source="gCaptain")), incs)
    assert a["status"] == "confirmed" and len(a["sources"]) == 3 and len(incs) == 1


def test_different_vessels_stay_separate():
    incs = []
    store.merge(report(vessel_name="Kairos"), incs)
    store.merge(report(vessel_name="Virat", source=src("https://t.me/a/9")), incs)
    assert len(incs) == 2


def test_unnamed_reports_match_by_position():
    incs = []
    store.merge(report(lat=46.49, lon=30.74), incs)
    store.merge(report(lat=46.45, lon=30.70, source=src("https://t.me/c/3", side="neutral", kind="media", source="ASTRA")), incs)
    assert len(incs) == 1 and incs[0]["status"] == "reported"


def test_firms_regions():
    cfg = load_yaml("regions.yaml")["firms"]
    assert classify(34.0, 43.5, cfg) == ("offshore", "Black Sea")
    assert classify(30.72, 46.48, cfg) == ("port", "Odesa")
    assert classify(32.0, 47.5, cfg) is None  # inland Ukraine
    assert point_in_polygon(0.5, 0.5, [[0, 0], [1, 0], [1, 1], [0, 1]])


def test_verdict_parse():
    v = apply_verdict.parse("/verdict rejected\nnote: owner says no incident — vessel in Istanbul\nsource: https://example.com/x")
    assert v["status"] == "rejected" and v["sources"] == ["https://example.com/x"]
    assert v["note"] == "owner says no incident, vessel in Istanbul"
    assert apply_verdict.parse("looks fine to me") is None


def test_brief_selection_and_html():
    incs = []
    inc, _ = store.merge(report(vessel_name="Kairos", flag="Gambia", vessel_type="tanker"), incs)
    since = datetime(2000, 1, 1, tzinfo=timezone.utc)
    new, updated, corrections = select(incs, since)
    assert new == [inc] and not updated and not corrections
    html = incident_html(inc)
    assert "Kairos" in html and "Claimed" in html and "—" not in html


def test_no_em_dash():
    assert no_em_dash("Tanker hit — crew safe") == "Tanker hit, crew safe"
