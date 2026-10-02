"""RSS feeds and Google News search feeds."""
from __future__ import annotations

import html
import re
from urllib.parse import quote_plus

import feedparser
import requests

from ..common import USER_AGENT, iso, item_id, load_yaml, log, parse_dt

_TAGS = re.compile(r"<[^>]+>")


def _google_news_url(q: dict) -> str:
    lang, gl = q["lang"], q["gl"]
    return f"https://news.google.com/rss/search?q={quote_plus(q['q'] + ' when:2d')}&hl={lang}&gl={gl}&ceid={gl}:{lang}"


def _parse(url: str) -> list:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return feedparser.parse(resp.content).entries


def _entry_time(e) -> str | None:
    for key in ("published_parsed", "updated_parsed"):
        t = e.get(key)
        if t:
            from datetime import datetime, timezone

            return iso(datetime(*t[:6], tzinfo=timezone.utc))
    return iso(parse_dt(e.get("published"))) if parse_dt(e.get("published")) else None


def collect(seen: dict) -> list[dict]:
    cfg = load_yaml("feeds.yaml")
    sources = [dict(f) for f in cfg.get("feeds", [])]
    defaults = cfg.get("google_news_defaults", {})
    for q in cfg.get("google_news", []):
        sources.append({**defaults, "name": f"Google News ({q['lang']}): {q['q'][:40]}", "url": _google_news_url(q), "google": True})

    items, seen_links = [], set()
    for src in sources:
        try:
            entries = _parse(src["url"])
        except Exception as exc:
            log.warning("Feed %s failed: %s", src["name"], exc)
            continue
        for e in entries:
            link = e.get("link") or ""
            title = (e.get("title") or "").strip()
            if not link or link in seen_links:
                continue
            seen_links.add(link)
            summary = html.unescape(_TAGS.sub(" ", e.get("summary") or ""))
            title = html.unescape(title)
            publisher = ""
            if src.get("google"):
                # Google News titles end in " - Publisher"
                publisher = (e.get("source") or {}).get("title", "") if isinstance(e.get("source"), dict) else ""
            items.append(
                {
                    "id": "rss:" + item_id(link),
                    "url": link,
                    "source": publisher or src["name"],
                    "source_type": "news",
                    "side": src.get("side", "neutral"),
                    "kind": src.get("kind", "media"),
                    "title": title,
                    "text": re.sub(r"\s+", " ", summary).strip()[:2000],
                    "published_at": _entry_time(e),
                    "require_region_term": bool(src.get("require_region_term")),
                }
            )
    log.info("RSS: %d entries from %d feeds", len(items), len(sources))
    return items
