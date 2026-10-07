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
    inc, _ = store.merge(report(vessel_name="Kazimah", region="Strait of Hormuz", source=src("https://a/1", side="unknown", kind="media", source="Reuters")), incs)
    store.merge(report(vessel_name="Kazimah", region="Strait of Hormuz", source=src("https://u/2", side="neutral", kind="official", source="UKMTO")), incs)
    store.merge(report(vessel_name="Kazimah", region="Strait of Hormuz", source=src("https://news.google.com/rss/articles/x", side="unknown", kind="media", source="Al Jazeera")), incs)
    out = sources_html(incs)
    assert "news.google.com" not in out and "Al Jazeera" in out
    assert out.index("UKMTO") < out.index("Reuters") and "Kazimah, Strait of Hormuz" in out and 'rel="nofollow' in out


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


def test_sources_list_hides_unlisted_outlet():
    """Local outlets not on config/trusted_outlets.yaml stay internal; readers see that the item is unconfirmed."""
    from tracker.brief import sources_html
    out = sources_html([{"region": "Gulf of Aden", "status": "reported", "vessel_type": "tanker",
                         "sources": [{"source": "حياة عدن", "url": "https://news.google.com/x", "kind": "media"}]}])
    assert "حياة عدن" not in out and "not yet confirmed by a major outlet" in out


def test_image_label_ship_types():
    from tracker.image import label
    assert label({"vessel_type": "tanker", "location_text": "off Yemen"}) == "Tanker, off Yemen"
    assert label({"vessel_name": "LIPSI", "vessel_type": "tanker (LR2)", "location_text": "Strait of Hormuz"}) == \
        "LIPSI (tanker LR2), Strait of Hormuz"


def test_review_comment_parse_and_apply(tmp_path, monkeypatch):
    from tracker import review
    from tracker import common
    body = ("/review 2026-10-05\n"
            "merge: INC-20261004-013 into INC-20261004-005 | same UKMTO 151-26 attack\n"
            "name: INC-20261004-002 = Lipsi | https://maritime-executive.com/article/x\n"
            "imo: INC-20261004-002 = 12345 | https://example.com\n"
            "status: INC-20261001-001 = rejected | not in today's draft\n"
            "note: Hormuz count in one source looks inflated.\n")
    day, changes, notes = review.parse(body)
    assert day == "2026-10-05" and len(changes) == 4 and notes
    assert review.parse("hello") is None

    incs = [
        {"id": "INC-20261004-002", "region": "Strait of Hormuz", "status": "confirmed", "sources": [{"url": "a", "source": "UKMTO"}]},
        {"id": "INC-20261004-005", "region": "Red Sea", "status": "confirmed", "sources": [{"url": "b", "source": "UKMTO"}]},
        {"id": "INC-20261004-013", "region": "Gulf of Aden", "status": "reported", "sources": [{"url": "c", "source": "Aden"}]},
        {"id": "INC-20261001-001", "region": "Black Sea", "status": "claimed", "sources": [{"url": "d", "source": "X"}]},
    ]
    saved = {}
    monkeypatch.setattr(review.store, "load", lambda: incs)
    monkeypatch.setattr(review.store, "save", lambda x: saved.setdefault("incs", x))
    monkeypatch.setattr(review, "REVIEW_DIR", tmp_path)
    monkeypatch.setattr(review, "BRIEFS_DIR", tmp_path)
    common.write_json(tmp_path / "2026-10-05.json",
                      {"date": "2026-10-05", "incidents": [{"id": i["id"]} for i in incs[:3]]})
    assert review.apply(body) == "2026-10-05"
    by = {i["id"]: i for i in incs}
    assert by["INC-20261004-013"]["merged_into"] == "INC-20261004-005"
    assert by["INC-20261004-002"]["vessel_name"] == "LIPSI"
    assert "imo" not in by["INC-20261004-002"]                 # bad IMO refused
    assert by["INC-20261001-001"]["status"] == "claimed"       # not in the draft: refused
    rec = common.read_json(tmp_path / "2026-10-05.json", {})
    assert len(rec["review"]["changes"]) == 2 and len(rec["review"]["refused"]) == 2
    line = review.summary_line(rec)
    assert line.startswith("Editor check: 2 fix(es)") and "could not be applied" in line and "Editor notes" in line
    assert review.summary_line({}).startswith("⚠️ Editor check did not run")


def test_outlet_names_and_context():
    from datetime import datetime, timezone
    from tracker.brief import outlet_name, tracker_context
    assert outlet_name({"source": "rivieramm.com", "url": "https://www.rivieramm.com/news/x"}) == "Riviera Maritime Media"
    assert outlet_name({"source": "Editor check", "url": "https://www.ukmto.org/-/media/x.pdf"}) == "UKMTO"
    assert outlet_name({"source": "Gulf News - Latest", "url": "https://news.google.com/x"}) == "Gulf News"
    assert outlet_name({"source": "example-news.com", "url": "https://example-news.com/a"}) == "Example News"
    now = datetime(2026, 10, 5, 5, tzinfo=timezone.utc)
    incs = [{"region": "Strait of Hormuz", "status": "confirmed", "date_utc": "2026-10-04", "vessel_name": "LIPSI"},
            {"region": "Gulf of Oman", "status": "reported", "date_utc": "2026-10-01", "vessel_type": "tanker"},
            {"region": "Strait of Hormuz", "status": "reported", "date_utc": "2026-10-03"},  # a statistic, no ship
            {"region": "Strait of Hormuz", "status": "claimed", "date_utc": "2026-10-03"},
            {"region": "Strait of Hormuz", "status": "merged", "merged_into": "X", "date_utc": "2026-10-03"},
            {"region": "Black Sea", "status": "confirmed", "date_utc": "2026-09-20"}]
    ctx = tracker_context(incs, now)
    assert ctx == [{"area": "Strait of Hormuz and the Gulf", "merchant_ships_reported_hit_in_last_7_days": 2,
                    "merchant_ships_reported_hit_in_the_7_days_before": 0, "named_ships": ["LIPSI"]}]


def test_lessons_add_and_replace(tmp_path, monkeypatch):
    from tracker import lessons
    monkeypatch.setattr(lessons, "PATH", tmp_path / "lessons.yaml")
    assert lessons.add("writing", "Name the ship in the headline when it is known.")
    assert not lessons.add("writing", "name the ship in the headline, when it is known")   # near-duplicate
    assert not lessons.add("writing", "too short")
    assert not lessons.add("style", "An unknown section is refused here.")
    assert lessons.add("facts", "A report with no ship, flag or type is a statistic, not an incident.")
    assert "Lessons from earlier mistakes" in lessons.prompt_block("writing")
    body = ("/lessons\nwriting:\n- Keep headlines under 80 characters and name the ship.\n"
            "- Credit ship names to whoever identified the ship.\nfacts:\n- One outlet retelling a UKMTO warning is the same attack.\n")
    assert lessons.replace_from_comment(body)
    data = lessons.load()
    assert len(data["writing"]) == 2 and len(data["facts"]) == 1
    assert not lessons.replace_from_comment("/lessons\nwriting:\n- Only writing rules here, facts would be emptied.\n")
    assert lessons.load()["facts"]  # refused: kept


def test_review_lesson_line():
    from tracker import review
    _, changes, _ = review.parse("/review 2026-10-05\nlesson: writing = Do not call explosions near a ship an attack on it.\n")
    assert changes == [("lesson", "writing", "Do not call explosions near a ship an attack on it.", "")]


def test_review_position_line(tmp_path, monkeypatch):
    from tracker import common, review
    incs = [{"id": "INC-20261004-005", "region": "Red Sea", "status": "confirmed", "lat": 12.6, "lon": 43.4,
             "sources": [{"url": "b", "source": "UKMTO"}]}]
    monkeypatch.setattr(review.store, "load", lambda: incs)
    monkeypatch.setattr(review.store, "save", lambda x: None)
    monkeypatch.setattr(review, "REVIEW_DIR", tmp_path)
    monkeypatch.setattr(review, "BRIEFS_DIR", tmp_path)
    common.write_json(tmp_path / "2026-10-05.json", {"incidents": [{"id": "INC-20261004-005"}]})
    review.apply("/review 2026-10-05\nposition: INC-20261004-005 = 12.32, 43.25 | 60 nm south of Al-Mokha per UKMTO\n"
                 "position: INC-20261004-005 = 51.5, -0.1 | London\n")
    assert (incs[0]["lat"], incs[0]["lon"]) == (12.32, 43.25)
    rec = common.read_json(tmp_path / "2026-10-05.json", {})
    assert len(rec["review"]["refused"]) == 1


def test_balance_line():
    from tracker.llm import balance_line
    assert balance_line(None) == ""
    assert balance_line(19.0) == "DeepSeek balance: $19.00."
    low = balance_line(2.5)
    assert low.startswith("⚠️") and "$2.50" in low and "keeps running" in low


def test_brief_watchdog_decide():
    import importlib.util
    spec = importlib.util.spec_from_file_location("wd", "scripts/hermes/brief_watchdog.py")
    wd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wd)
    comment, msg = wd.decide(None, "2026-10-07")
    assert comment == "/brief now" and msg.startswith("⚠️")
    comment, msg = wd.decide({"post_id": 1}, "2026-10-07")
    assert comment.startswith("/review 2026-10-07\nnote:") and "not been sent" in msg
    assert wd.decide({"post_id": 1, "notified": "2026-10-07T05:10:00Z"}, "2026-10-07") == (None, "")
    # the note line must be accepted by the tracker's /review parser
    from tracker import review
    day, changes, notes = review.parse(wd.decide({"post_id": 1}, "2026-10-07")[0])
    assert day == "2026-10-07" and changes == [] and notes


def test_editor_notes_reach_the_writer(tmp_path, monkeypatch):
    """A /review note (wrong credit, conflicting dates) must be given to the writer and the fact-checker on the rebuild."""
    import json as _json
    from tracker import brief
    from tracker.common import write_json
    monkeypatch.setattr(brief, "BRIEFS_DIR", tmp_path)
    note = "The 12 injured came from India's foreign ministry, not from UKMTO."
    write_json(tmp_path / "2026-10-07.json", {"review": {"status": "done", "notes": [note]}})
    assert brief.editor_notes("2026-10-07") == [note]
    assert brief.editor_notes("2026-10-08") == []
    write_json(tmp_path / "2026-10-09.json", {"review": {"status": "pending", "notes": [note]}})
    assert brief.editor_notes("2026-10-09") == []

    seen = []
    def fake_chat(system, user, **kw):
        seen.append((system, _json.loads(user)))
        return {"title": "t", "excerpt": "e", "key_points": ["k"], "article_html": "<p>a</p>", "x_post": "x"}
    monkeypatch.setattr(brief.llm, "chat_json", fake_chat)
    brief.write_copy("7 October 2026", [], [], [], [], None, [note])
    writer_system, writer_user = seen[0]
    assert writer_user["editor_notes"] == [note] and "notes win" in writer_system
    checker_system, checker_user = seen[1]
    assert checker_user["FACTS"]["editor_notes"] == [note] and "editor_notes" in checker_system


def test_second_review_keeps_first_notes(tmp_path, monkeypatch):
    from tracker import brief, review
    from tracker.common import write_json
    monkeypatch.setattr(review.store, "load", lambda: [])
    monkeypatch.setattr(review.store, "save", lambda x: None)
    monkeypatch.setattr(review, "REVIEW_DIR", tmp_path)
    monkeypatch.setattr(review, "BRIEFS_DIR", tmp_path)
    monkeypatch.setattr(brief, "BRIEFS_DIR", tmp_path)
    write_json(tmp_path / "2026-10-07.json", {})
    review.apply("/review 2026-10-07\nnote: Credit the 12 injured to India, not UKMTO.")
    review.apply("/review 2026-10-07\nnote: Automatic resend at 06:00 UTC: the approval message had not been sent.")
    assert brief.editor_notes("2026-10-07") == ["Credit the 12 injured to India, not UKMTO."]


def test_public_sources_only_trusted():
    from tracker import brief
    inc = {"vessel_name": "ALFA WATAN", "region": "Black Sea", "status": "confirmed", "sources": [
        {"source": "opindia.com", "url": "https://news.google.com/rss/x", "kind": "media", "source_type": "news"},
        {"source": "Rybar", "url": "https://t.me/rybar/1", "kind": "osint", "source_type": "telegram"},
        {"source": "bbc.com", "url": "https://www.bbc.com/news/articles/x", "kind": "media", "source_type": "news"},
        {"source": "Euronews - Son Dakika", "url": "https://news.google.com/rss/y", "kind": "media", "source_type": "news"},
        {"source": "vesselfinder.com", "url": "https://www.vesselfinder.com/vessels/details/1", "kind": "media", "source_type": "news"},
        {"source": "Odesa Regional Military Administration", "url": "https://t.me/odeskaODA/1", "kind": "official", "source_type": "telegram"}]}
    out = brief.sources_html([inc])
    assert "BBC" in out and "Euronews" in out and "Odesa Regional Military Administration" in out
    assert "opindia" not in out.lower() and "Rybar" not in out and "inder" not in out
    only_local = {**inc, "sources": inc["sources"][:2]}
    assert "not yet confirmed by a major outlet" in brief.sources_html([only_local])


def test_older_unhurt_attacks_become_one_liners(monkeypatch):
    import json as _json
    from tracker import brief
    now = datetime(2026, 10, 7, 7, tzinfo=timezone.utc)
    base = {"region": "Strait of Hormuz", "status": "reported", "sources": []}
    old_quiet = {**base, "id": "A", "vessel_name": "MARAN GAS MYSTRAS", "date_utc": "2026-10-04", "casualties": None}
    old_hurt = {**base, "id": "B", "vessel_name": "ON PEACE", "date_utc": "2026-10-05", "casualties": "12 crew injured"}
    fresh = {**base, "id": "C", "vessel_name": "X", "date_utc": "2026-10-06", "casualties": "no injuries reported"}
    seen = []
    monkeypatch.setattr(brief.llm, "chat_json", lambda system, user, **kw: seen.append(_json.loads(user)) or {})
    brief.write_copy("7 October 2026", [old_quiet, old_hurt, fresh], [], [], [], now)
    sent = seen[0]
    assert [i["vessel_name"] for i in sent["earlier_this_week"]] == ["MARAN GAS MYSTRAS"]
    assert [i["vessel_name"] for i in sent["new_incidents"]] == ["ON PEACE", "X"]
