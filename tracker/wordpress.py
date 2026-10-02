"""WordPress REST API publisher for imariners.com (Application Password auth).

Settings:
  WP_URL            https://imariners.com           (variable)
  WP_USER           the bot user's login            (secret)
  WP_APP_PASSWORD   its Application Password        (secret)
  WP_CATEGORY_SLUG  maritime-security               (variable; create the category in WP admin first)
  PUBLISH_MODE      draft | publish                 (variable; draft = wait for your approval in n8n)
"""
from __future__ import annotations

from pathlib import Path

import re
import time

import requests

from .common import env, log


class WordPress:
    def __init__(self):
        self.base = env("WP_URL", required=True).rstrip("/") + "/wp-json/wp/v2"
        self.auth = (env("WP_USER", required=True), env("WP_APP_PASSWORD", required=True))

    def _req(self, method: str, path: str, **kw):
        """One REST call. Retries busy or odd responses (rate limits, a security plugin's HTML page)."""
        last = ""
        for attempt in range(4):
            try:
                resp = requests.request(method, self.base + path, auth=self.auth, timeout=60, **kw)
            except requests.RequestException as exc:
                last = str(exc)
            else:
                if resp.status_code < 300:
                    try:
                        return resp.json()
                    except ValueError:
                        title = re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.S | re.I)
                        last = (f"non-JSON reply ({resp.headers.get('content-type')}), page title: "
                                f"{(title.group(1).strip() if title else resp.text[:150])!r}, server: {resp.headers.get('server')}")
                elif resp.status_code in (401, 403, 404) and attempt == 0 and "json" in resp.headers.get("content-type", ""):
                    raise RuntimeError(f"WordPress {method} {path} -> {resp.status_code}: {resp.text[:300]}")
                else:
                    last = f"{resp.status_code}: {resp.text[:200]}"
            log.warning("WordPress %s %s attempt %d failed: %s", method, path, attempt + 1, last)
            time.sleep(10 * (attempt + 1))
        raise RuntimeError(f"WordPress {method} {path} failed after retries: {last}")

    def category_id(self, slug: str) -> int:
        fixed = env("WP_CATEGORY_ID")
        if fixed:
            return int(fixed)  # skip the lookup: one request fewer per run
        found = self._req("GET", "/categories", params={"slug": slug})
        if not found:
            raise SystemExit(f"Category '{slug}' not found. Create it in WP admin (Posts > Categories) first.")
        return found[0]["id"]

    def upload_image(self, path: Path, alt: str) -> tuple[int, str]:
        """Upload a PNG to the media library. Returns (media id, public URL)."""
        media = self._req("POST", "/media", data=path.read_bytes(), headers={
            "Content-Disposition": f'attachment; filename="{path.name}"', "Content-Type": "image/png"})
        self._req("POST", f"/media/{media['id']}", json={"alt_text": alt})
        return media["id"], media.get("source_url", "")

    def upsert_post(self, post_id: int | None, fields: dict) -> dict:
        if post_id:
            try:
                return self._req("POST", f"/posts/{post_id}", json=fields)
            except RuntimeError as exc:
                log.warning("Could not update post %s (%s); creating a new one", post_id, exc)
        return self._req("POST", "/posts", json=fields)
