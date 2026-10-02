"""Read public Telegram channels through the t.me/s web preview (no account needed)."""
from __future__ import annotations

import time

import requests
from bs4 import BeautifulSoup

from ..common import USER_AGENT, load_yaml, log, parse_dt


_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


def _fetch_page(handle: str, before: str | None = None) -> list[dict]:
    url = f"https://t.me/s/{handle}" + (f"?before={before}" if before else "")
    resp = _session.get(url, timeout=(10, 40))
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    posts = []
    for msg in soup.select("div.tgme_widget_message[data-post]"):
        text_el = msg.select_one(".tgme_widget_message_text")
        if not text_el:
            continue
        time_el = msg.select_one("time[datetime]")
        post = msg["data-post"]  # "<handle>/<number>"
        posts.append(
            {
                "post": post,
                "number": int(post.rsplit("/", 1)[-1]),
                "text": text_el.get_text("\n", strip=True),
                "published_at": time_el["datetime"] if time_el else None,
            }
        )
    return posts


def collect(seen: dict, max_pages: int = 3) -> list[dict]:
    items = []
    for ch in load_yaml("channels.yaml").get("channels", []):
        handle = ch["handle"]
        try:
            page = _fetch_page(handle)
            if not page:
                log.warning("Telegram @%s returned no posts; check the handle in config/channels.yaml", handle)
                continue
            posts = list(page)
            # Busy channels can post more than one page between runs: page back until we reach seen posts.
            # On the very first run (nothing seen yet) one page per channel is enough.
            for _ in range(max_pages - 1 if seen else 0):
                oldest = min(p["number"] for p in page)
                if any(f"tg:{p['post']}" in seen for p in page):
                    break
                page = _fetch_page(handle, before=str(oldest))
                if not page:
                    break
                posts.extend(page)
                time.sleep(1)
        except requests.RequestException as exc:
            log.warning("Telegram @%s failed: %s", handle, exc)
            continue
        for p in posts:
            items.append(
                {
                    "id": f"tg:{p['post']}",
                    "url": f"https://t.me/{p['post']}",
                    "source": ch["name"],
                    "source_type": "telegram",
                    "side": ch["side"],
                    "kind": ch["kind"],
                    "title": "",
                    "text": p["text"],
                    "published_at": p["published_at"],
                    "require_region_term": False,
                }
            )
        time.sleep(1)
    log.info("Telegram: %d posts from %d channels", len(items), len(load_yaml("channels.yaml").get("channels", [])))
    return items


if __name__ == "__main__":
    for it in collect({})[:5]:
        print(it["source"], parse_dt(it["published_at"]), it["text"][:120].replace("\n", " "))
