#!/usr/bin/env python3
"""
Quad Watch — checks for new Quad-related news and official releases every
run and opens a GitHub Issue summarising anything new. It never edits
index.html; a human reviews the issue and decides what, if anything, to
add to the dashboard.

Two Google News RSS queries are used instead of scraping each government
site directly: whitehouse.gov, mofa.go.jp, mea.gov.in and dfat.gov.au were
tested directly and are unreliable to scrape (JS-rendered listings, no
keyword filtering, or blocked non-browser requests). Google News indexes
all of them and exposes a plain RSS feed, which is far more robust.
"""
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "quad_watch_state.json")
MAX_SEEN = 800
UA = "Mozilla/5.0 (compatible; QuadMonitorWatch/1.0; +https://quadmonitor.amitkumar-ak.com)"

OFFICIAL_DOMAINS = ["whitehouse.gov", "mofa.go.jp", "mea.gov.in", "dfat.gov.au", "state.gov"]
QUAD_TERMS = [
    '"Quad Leaders"', '"Quad Foreign Ministers"', '"Quadrilateral Security Dialogue"',
    '"Quad Summit"', '"Quad initiative"', '"Quad partnership"', '"Quad fact sheet"',
]

QUERIES = {
    "Official sources": "({}) ({}) when:20d".format(
        " OR ".join(QUAD_TERMS),
        " OR ".join(f"site:{d}" for d in OFFICIAL_DOMAINS),
    ),
    "Broader coverage": "({}) when:20d".format(" OR ".join(QUAD_TERMS)),
}

RSS_BASE = "https://news.google.com/rss/search"


def fetch_feed(query):
    url = RSS_BASE + "?" + urllib.parse.urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
    except Exception as e:
        print(f"  fetch failed: {e}", file=sys.stderr)
        return []
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        print(f"  parse failed: {e}", file=sys.stderr)
        return []
    items = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        if title and link:
            items.append({"title": title, "link": link, "pubDate": pub, "source": source})
    return items


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"seen": [], "last_run": None}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    state["seen"] = state["seen"][-MAX_SEEN:]
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def build_issue_body(new_by_section):
    lines = [
        "Automated Quad Watch digest. Nothing has been changed on the dashboard —",
        "review the items below and tell me what (if anything) to add.",
        "",
    ]
    for section, items in new_by_section.items():
        if not items:
            continue
        lines.append(f"## {section} ({len(items)})")
        lines.append("")
        for it in items:
            date = it["pubDate"] or "date unknown"
            src = f" — *{it['source']}*" if it["source"] else ""
            lines.append(f"- [{it['title']}]({it['link']}){src} ({date})")
        lines.append("")
    return "\n".join(lines)


def create_issue(title, body):
    body_path = "/tmp/quad_watch_issue_body.md"
    with open(body_path, "w") as f:
        f.write(body)
    subprocess.run(
        ["gh", "issue", "create", "--title", title, "--body-file", body_path, "--label", "quad-watch"],
        check=True,
    )


def main():
    state = load_state()
    seen = set(state.get("seen", []))
    new_by_section = {}
    all_new_links = []

    for section, query in QUERIES.items():
        print(f"Querying: {section}")
        items = fetch_feed(query)
        print(f"  {len(items)} items returned")
        new_items = [it for it in items if it["link"] not in seen]
        # de-dupe within this run too
        dedup = {}
        for it in new_items:
            dedup[it["link"]] = it
        new_items = list(dedup.values())
        new_by_section[section] = new_items
        all_new_links.extend(it["link"] for it in new_items)

    total_new = len(set(all_new_links))
    print(f"Total new items across sections: {total_new}")

    if total_new > 0:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        title = f"Quad Watch — {today} digest ({total_new} new item{'s' if total_new != 1 else ''})"
        body = build_issue_body(new_by_section)
        create_issue(title, body)
        print("Issue created.")
    else:
        print("Nothing new — no issue created.")

    state["seen"] = list(seen | set(all_new_links))
    save_state(state)


if __name__ == "__main__":
    main()
