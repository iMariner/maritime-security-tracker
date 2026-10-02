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


def test_repeated_party_claim_stays_claimed():
    incs = []
    a, _ = store.merge(report(independent_evidence=False, source=src("https://n/1", side="unknown", kind="media", source="Outlet A")), incs)
    store.merge(report(same_as=a["id"], independent_evidence=False, source=src("https://n/2", side="unknown", kind="media", source="Outlet B")), incs, model_checked=True)
    assert a["status"] == "claimed" and len(a["sources"]) == 2
    store.merge(report(same_as=a["id"], independent_evidence=True, source=src("https://n/3", side="neutral", kind="media", source="Splash247")), incs, model_checked=True)
    assert a["status"] == "reported"


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
    store.merge(report(lat=46.45, lon=30.70, independent_evidence=True, source=src("https://t.me/c/3", side="neutral", kind="media", source="ASTRA")), incs)
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
    v2 = apply_verdict.parse("/verdict claimed\nvessel_name: <corrected name, only if wrong or missing>\nsource: https://x.y/z")
    assert v2["status"] == "claimed" and v2["fields"] == {}


def test_brief_selection_and_html():
    incs = []
    inc, _ = store.merge(report(vessel_name="Kairos", flag="Gambia", vessel_type="tanker"), incs)
    since = datetime(2000, 1, 1, tzinfo=timezone.utc)
    new, updated, corrections = select(incs, since)
    assert new == [inc] and not updated and not corrections
    html = incident_html(inc)
    assert "Kairos" in html and "Claimed" in html and "—" not in html


def test_no_em_dash():
    assert no_em_dash("ABC News - Latest") == "ABC News, Latest" and no_em_dash("ro-ro, 2-3 knots") == "ro-ro, 2-3 knots"
    assert no_em_dash("Tanker hit — crew safe") == "Tanker hit, crew safe"


def test_model_same_as_hint_merges():
    incs = []
    a, _ = store.merge(report(region="Strait of Hormuz", vessel_type="tanker"), incs, model_checked=True)
    b, new = store.merge(report(region="Strait of Hormuz", same_as=a["id"], source=src("https://n/2", side="neutral", kind="media", source="gCaptain")), incs, model_checked=True)
    assert not new and b is a and len(incs) == 1
    _, new = store.merge(report(region="Strait of Hormuz", source=src("https://n/3")), incs, model_checked=True)
    assert new  # model said it is a different attack


def test_undated_reports_match_by_publish_time():
    incs = []
    store.merge(report(date_utc=None, lat=26.5, lon=56.3, region="Strait of Hormuz"), incs)
    assert incs[0]["date_utc"] == "2026-10-01T10:00:00Z" and incs[0]["date_approx"]
    store.merge(report(date_utc=None, lat=26.55, lon=56.35, region="Strait of Hormuz", source=src("https://n/9", side="neutral", kind="media", source="ASTRA")), incs)
    assert len(incs) == 1


def test_party_ministry_never_confirms():
    assert store.neutral_confirmation("UKMTO")
    assert store.neutral_confirmation("the ship's manager")
    assert store.neutral_confirmation("Kuwait Oil Tanker Company")
    assert not store.neutral_confirmation("Russian Ministry of Defence")
    assert not store.neutral_confirmation("Ukrainian Navy")
    incs = []
    inc, _ = store.merge(report(official_source_cited="Russian Ministry of Defence"), incs)
    assert inc["status"] == "claimed"


def test_approximate_positions():
    from tracker import geo
    inc = {"region": "Black Sea", "location_text": "Chornomorsk port, Odesa region", "lat": None, "lon": None}
    assert geo.fill_position(inc) and (inc["lat"], inc["lon"]) == (46.30, 30.66) and inc["position_approx"]
    inc2 = {"region": "Strait of Hormuz", "location_text": None, "summary": "A tanker was hit", "lat": None, "lon": None}
    geo.fill_position(inc2)
    assert (inc2["lat"], inc2["lon"]) == (26.55, 56.35)
    incs = []
    a, _ = store.merge(report(region="Strait of Hormuz"), incs)
    geo.fill_position(a)
    store.merge(report(region="Strait of Hormuz", vessel_name="Kazimah", lat=26.4, lon=56.5, source=src("https://n/k")), incs)
    assert len(incs) == 2  # an approximate position is never used to merge two incidents


def test_article_helpers():
    from tracker.brief import _clean_html, sources_html
    assert _clean_html('<p>Hi <script>x</script><img src=x><strong>b</strong></p>') == "<p>Hi x<strong>b</strong></p>"
    incs = []
    inc, _ = store.merge(report(vessel_name="Kazimah", region="Strait of Hormuz", source=src("https://a/1", side="unknown", kind="media", source="Outlet")), incs)
    store.merge(report(vessel_name="Kazimah", region="Strait of Hormuz", source=src("https://u/2", side="neutral", kind="official", source="UKMTO")), incs)
    store.merge(report(vessel_name="Kazimah", region="Strait of Hormuz", source=src("https://news.google.com/rss/articles/x", side="unknown", kind="media", source="Wire")), incs)
    out = sources_html(incs)
    assert "news.google.com" not in out and "Wire" in out
    assert out.index("UKMTO") < out.index("Outlet") and "Kazimah, Strait of Hormuz" in out and 'rel="nofollow' in out


def test_key_points_card_and_map():
    from tracker.brief import key_points_html, with_map
    card = key_points_html(["Tanker hit", "Claim by Russia"])
    assert card.count("<li ") == 2 and "Key points" in card and "#0A91AB" in card
    body = with_map(card + "<p>Lede</p>", "https://x/y.png", "2 October 2026")
    assert body.index("Key points") < body.index("msb-map") < body.index("Lede")
    assert with_map(body, "https://x/y.png", "2 October 2026") == body  # never twice
