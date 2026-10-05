"""Lessons learned (config/lessons.yaml): rules the writer, the fact-checker and the duplicate review follow.

The list grows from mistakes, not by hand: Hermes adds a lesson when its daily editor check finds a repeatable
error, and its weekly learning review rewrites the list from the week's log of fixes.
"""
from __future__ import annotations

import re

import yaml

from .common import ROOT, log, no_em_dash

PATH = ROOT / "config" / "lessons.yaml"
KINDS = ("writing", "facts")
MAX_PER_KIND = 25
HEADER = ("# Lessons learned: short rules every brief is written and checked against.\n"
          "# Hermes adds lessons during the daily editor check (\"lesson:\" lines) and rewrites this list in its weekly\n"
          "# learning review (at most 25 per section). Keep each rule one concrete sentence.\n")


def load() -> dict[str, list[str]]:
    try:
        data = yaml.safe_load(PATH.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        data = {}
    return {k: [str(x) for x in data.get(k) or []] for k in KINDS}


def save(data: dict[str, list[str]]) -> None:
    body = yaml.safe_dump({k: data.get(k, []) for k in KINDS}, allow_unicode=True, sort_keys=False, width=200)
    PATH.write_text(HEADER + body, encoding="utf-8")


def prompt_block(kind: str) -> str:
    rules = load().get(kind) or []
    if not rules:
        return ""
    return "\nLessons from earlier mistakes (always follow):\n" + "\n".join(f"- {r}" for r in rules) + "\n"


def clean(text: str) -> str | None:
    text = no_em_dash(re.sub(r"\s+", " ", text or "")).strip()
    return text if 15 <= len(text) <= 240 else None


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def add(kind: str, text: str) -> bool:
    """Add one lesson unless it is a near-duplicate. The oldest goes when a section is full."""
    rule = clean(text)
    if kind not in KINDS or not rule:
        return False
    data = load()
    if any(_key(rule) == _key(r) for r in data[kind]):
        return False
    data[kind] = (data[kind] + [rule])[-MAX_PER_KIND:]
    save(data)
    log.info("Lesson added (%s): %s", kind, rule)
    return True


def replace_from_comment(body: str) -> bool:
    """'/lessons' comment from the weekly review: the complete new list, one rule per line under
    'writing:' and 'facts:' headings. Refused if it would empty a section or exceed the limit."""
    lines = (body or "").strip().splitlines()
    if not lines or not lines[0].strip().startswith("/lessons"):
        return False
    new, section = {k: [] for k in KINDS}, None
    for line in lines[1:]:
        s = line.strip()
        head = s.rstrip(":").lower()
        if head in KINDS:
            section = head
            continue
        rule = clean(s.lstrip("-* ").strip())
        if section and rule and not any(_key(rule) == _key(r) for r in new[section]):
            new[section].append(rule)
    old = load()
    for k in KINDS:
        if old[k] and not new[k]:
            log.warning("Lessons: the new list has no %s rules; keeping the current list", k)
            return False
        if len(new[k]) > MAX_PER_KIND:
            new[k] = new[k][:MAX_PER_KIND]
    save(new)
    log.info("Lessons replaced: %s", ", ".join(f"{k} {len(old[k])} -> {len(new[k])}" for k in KINDS))
    return True
