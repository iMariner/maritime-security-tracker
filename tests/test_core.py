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


def test_review_pass_merges_and_drops(monkeypatch):
    from tracker import consolidate as c
    incs = []
    a, _ = store.merge(report(region="Strait of Hormuz", vessel_name="Kazimah", source=src("https://n/a", side="neutral", kind="media", source="Splash247")), incs)
    b, _ = store.merge(report(region="Strait of Hormuz", source=src("https://n/b")), incs, model_checked=True)
    d, _ = store.merge(report(region="Persian Gulf", source=src("https://n/d")), incs, model_checked=True)
    f, _ = store.merge(report(region="Strait of Hormuz", source=src("https://n/f")), incs, model_checked=True)
    monkeypatch.setattr(c.llm, "available", lambda: True)
    monkeypatch.setattr(c.llm, "chat_json", lambda *args, **kw: {
        "groups": [{"keep": a["id"], "keep_attack_date": "2026-10-01",
                    "merge": [{"id": b["id"], "attack_date": "2026-10-01"}, {"id": f["id"], "attack_date": "2026-09-28"}],
                    "summary": "Kazimah was hit — crew safe."}],
        "out_of_scope": [{"id": d["id"], "reason": "port strike, no vessel"}]})
    monkeypatch.setattr(c.github_issues, "close_issue", lambda *args, **kw: None)
    assert c.consolidate(incs) == 2
    assert b["status"] == "merged" and b["merged_into"] == a["id"] and len(a["sources"]) == 2
    assert not f.get("merged_into")  # three days apart: refused by the hard date rule
    assert not f.get("merged_into")  # three days apart: refused by the hard date rule
    assert d["status"] == "rejected"
    assert a["summary"] != "Kazimah was hit, crew safe."  # f was refused, so the group's summary is not used
    # a later report about the merged entry lands on the survivor
    e, new = store.merge(report(region="Strait of Hormuz", same_as=b["id"], source=src("https://n/e")), incs, model_checked=True)
    assert not new and e is a


def test_brief_new_vs_update():
    from datetime import timedelta
    from tracker.brief import select
    from tracker.common import iso, now_utc
    since = now_utc() - timedelta(hours=24)
    fresh = {"id": "A", "status": "reported", "region": "Black Sea", "first_seen": iso(now_utc()), "date_utc": iso(now_utc()), "sources": []}
    old_event = dict(fresh, id="B", date_utc=iso(now_utc() - timedelta(days=20)))
    repeated = dict(fresh, id="C", published_in=["2026-10-01"], first_seen=iso(now_utc() - timedelta(days=2)))
    upgraded = dict(repeated, id="D", status="confirmed", status_changed_at=iso(now_utc()))
    rerun = dict(fresh, id="E", published_in=[now_utc().date().isoformat()])
    new, updated, corrections = select([fresh, old_event, repeated, upgraded, rerun], since)
    assert [i["id"] for i in new] == ["A", "E"] and [i["id"] for i in updated] == ["D"] and not corrections


def test_region_override():
    from tracker import geo
    assert geo.region_override({"region": "Strait of Hormuz", "attribution_claimed": "Yemen's Houthis"}) == "Red Sea"
    assert geo.region_override({"region": "Strait of Hormuz", "summary": "Kazimah hit; separately a projectile hit Yanbu"}) is None
    assert geo.region_override({"region": "Strait of Hormuz", "summary": "Tanker hit east of Fujairah"}) is None


def test_vessel_name_numbers():
    assert store.same_vessel("Kazimah", "KAZIMAH III") and store.same_vessel("MV Kazimah III", "Kazimah III")
    assert not store.same_vessel("Kazimah II", "Kazimah III") and not store.same_vessel("Kazimah", "Kairos")
    incs = []
    store.merge(report(vessel_name="Kazimah II"), incs)
    store.merge(report(vessel_name="Kazimah III", source=src("https://n/k3")), incs)
    assert len(incs) == 2


def test_fit_tweet():
    from tracker.brief import fit_tweet
    long = "First sentence about a tanker hit in Hormuz with a fire on board and crew safe. " * 2 + "Second sentence about the Black Sea claim. #MaritimeSecurity #Shipping"
    out = fit_tweet(long)
    assert len(out) + 24 <= 280 and out.endswith("#MaritimeSecurity #Shipping")


def test_imo_list_parse():
    from datetime import datetime, timezone
    from tracker.collectors import imo
    html = """<p>Number of confirmed incidents as at 30 September 2026: 3</p><table>
    <tr><th>Date</th><th>Ship Name (IMO Number)</th><th>Location</th><th>Description</th></tr>
    <tr><td>29 September</td><td>SINBAD (IMO\xa09413688)</td><td>Strait of Hormuz</td><td>Damaged. No pollution.</td></tr>
    <tr><td>23 September</td><td>CAPE DAO (IMO 9219020)</td><td>15NM northeast of Khasab, Oman</td><td>Damaged. One seafarer fatality.</td></tr>
    <tr><td>4 December</td><td>OLD SHIP (IMO 9000001)</td><td>off Fujairah</td><td>Damaged.</td></tr></table>"""
    rows = imo.parse(html)
    assert [r["name"] for r in rows] == ["SINBAD", "CAPE DAO", "OLD SHIP"] and rows[0]["imo"] == "9413688"
    assert rows[0]["date"] == datetime(2026, 9, 29, tzinfo=timezone.utc) and rows[2]["date"].year == 2025
    rep = imo.to_report(rows[1], "2026-10-02T00:00:00Z")
    assert rep["region"] == "Strait of Hormuz" and rep["casualties"] == "One seafarer fatality."
    incs = []
    inc, _ = store.merge(rep, incs, model_checked=True)
    assert inc["status"] == "confirmed" and inc["imo"] == "9219020"
    assert imo.region_for("off Fujairah") == "Gulf of Oman" and imo.region_for("near Hodeidah") == "Red Sea"


def test_flags_and_official_absorb():
    from tracker import consolidate as c
    from tracker.collectors import imo
    from datetime import datetime, timezone
    assert store.different_flags({"flag": "Kuwait"}, {"flag": "Panama"})
    assert not store.different_flags({"flag": "Kuwaiti"}, {"flag": "Kuwait"}) and not store.different_flags({"flag": None}, {"flag": "Panama"})
    incs = []
    row = {"date": datetime(2026, 9, 29, tzinfo=timezone.utc), "name": "SINBAD", "imo": "9413688", "location": "Strait of Hormuz", "description": "Damaged."}
    off, _ = store.merge(imo.to_report(row, "2026-10-02T00:00:00Z"), incs, model_checked=True)
    roundup, _ = store.merge(report(region="Strait of Hormuz", date_utc="2026-09-29T10:00:00Z",
                                    summary="Three tankers hit.", source=src("https://n/r", side="neutral", kind="media", source="Seatrade")), incs, model_checked=True)
    panama, _ = store.merge(report(region="Strait of Hormuz", date_utc="2026-09-29T12:00:00Z", flag="Panama",
                                   source=src("https://n/p")), incs, model_checked=True)
    assert c.absorb_into_official(incs) == 1
    assert roundup["merged_into"] == off["id"] and off["summary"].startswith("The IMO lists SINBAD")
    assert not panama.get("merged_into")  # a flagged report is a specific ship: never absorbed on a guess


def test_quality_report_flags_gaps():
    from datetime import datetime, timezone
    from tracker.brief import quality_report
    from tracker.collectors import imo
    incs = []
    row = {"date": datetime.now(timezone.utc), "name": "SINBAD", "imo": "9413688", "location": "Strait of Hormuz", "description": "Damaged."}
    off, _ = store.merge(imo.to_report(row, "2026-10-02T00:00:00Z"), incs, model_checked=True)
    claim, _ = store.merge(report(attribution_claimed=None, source=src("https://t/1", side="ru", kind="media", source="TASS")), incs)
    brief = {"incident_ids": [claim["id"]], "html": "<p>Text — more</p>", "title": "T", "x_post": "x" * 300, "fact_check": "no corrections needed"}
    q = quality_report(brief, incs)["checks"]
    assert q["official coverage"].endswith("MISSING") and "TOO LONG" in q["tweet"] and q["dashes"] == "1 found"
    assert "without a named source" in q["attribution"]


def test_image_label():
    from tracker.image import label
    assert label({"vessel_name": "KAZIMAH III", "vessel_type": "tanker", "location_text": "Strait of Hormuz"}) == \
        "KAZIMAH III (tanker), Strait of Hormuz"
    assert label({"vessel_type": "general cargo", "flag": "Liberia", "location_text": "Odesa region, Ukraine"}) == \
        "General cargo ship (Liberia), Odesa region"
    assert label({"region": "Red Sea"}) == "Unnamed ship, Red Sea"


def test_image_no_position_for_whole_sea():
    from tracker.image import no_position
    assert no_position({"location_text": "Black Sea", "lat": 43.4, "lon": 34.5, "position_approx": True})
    assert not no_position({"location_text": "Odesa region, Ukraine", "lat": 46.49, "lon": 30.74, "position_approx": True})
    assert not no_position({"location_text": "Strait of Hormuz", "lat": 26.55, "lon": 56.35, "position_approx": True})
    assert not no_position({"location_text": "Black Sea", "lat": 44.1, "lon": 33.2})  # a reported position


def test_generic_authority_is_not_neutral():
    assert store.neutral_confirmation("UK maritime agency (UKMTO)")
    assert not store.neutral_confirmation("Maritime Authority")
    assert not store.neutral_confirmation("shipping sources")
    assert not store.neutral_confirmation("tanker tracking data")


def test_echo_of_confirmed_attack_is_absorbed():
    from tracker.consolidate import absorb_echoes
    anchor = {"id": "A", "region": "Red Sea", "date_utc": "2026-10-04", "vessel_type": "tanker", "status": "confirmed",
              "verdict": {"status": "confirmed"}, "sources": [{"source": "UKMTO", "url": "u1"}]}
    echo = {"id": "B", "region": "Gulf of Aden", "date_utc": "2026-10-04", "vessel_type": "tanker", "status": "reported",
            "sources": [{"source": "Hayat Aden", "url": "u2"}]}
    other_day = {"id": "C", "region": "Gulf of Aden", "date_utc": "2026-10-08", "vessel_type": "tanker",
                 "status": "reported", "sources": [{"source": "X", "url": "u3"}]}
    named = {"id": "D", "region": "Gulf of Aden", "date_utc": "2026-10-04", "vessel_name": "SOME SHIP",
             "vessel_type": "tanker", "status": "reported", "sources": [{"source": "Y", "url": "u4"}]}
    items = [anchor, echo, other_day, named]
    assert absorb_echoes(items) == 1
    assert echo["status"] == "merged" and other_day["status"] == "reported" and named["status"] == "reported"
    assert any(s["url"] == "u2" for s in anchor["sources"])


def test_sources_list_keeps_arabic_outlet():
    from tracker.brief import sources_html
    out = sources_html([{"region": "Gulf of Aden", "status": "reported", "vessel_type": "tanker",
                         "sources": [{"source": "حياة عدن", "url": "https://news.google.com/x", "kind": "media"}]}])
    assert "حياة عدن" in out
