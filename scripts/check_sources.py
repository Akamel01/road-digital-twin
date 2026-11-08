#!/usr/bin/env python3
"""Validate docs/research/sources.yaml (stdlib only).

sources.yaml is written as JSON-compatible YAML (a JSON array), so it is parsed
with the stdlib json module. No YAML library is needed.

Checks:
  - schema: required fields per entry type, unique ids, valid questions and relevance
  - minimum counts: 25 papers, 10 repos, 5 products; at least 3 sources per question
  - DOI: Crossref record exists and its title matches the entry title
  - pdf_url: HTTP 200 with an application/pdf content type
  - repo: GitHub API returns the repo and full_name matches the entry url
  - url: every entry url answers with HTTP status below 400
  - citations: every [id] cited in docs/research/related-work.md exists, and every source is cited

Exit status is 1 when any check fails.
"""
import difflib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = os.path.join(ROOT, "docs", "research", "sources.yaml")
RELATED = os.path.join(ROOT, "docs", "research", "related-work.md")

TYPES = {"paper", "repo", "product", "dataset", "standard"}
MIN_COUNTS = {"paper": 25, "repo": 10, "product": 5}
MIN_PER_QUESTION = 3
QUESTIONS = range(1, 9)
USER_AGENT = "road-digital-twin-check-sources/1.0"


def fetch(url):
    """Return (status, content_type, body_bytes). Status is None on network failure."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as ex:
        return ex.code, ex.headers.get("Content-Type", "") if ex.headers else "", b""
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, "", b""


def norm(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def load(path=SOURCES):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check_schema(entry):
    errs = []
    eid = entry.get("id")
    if not eid or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", eid):
        errs.append("id must be kebab-case")
    t = entry.get("type")
    if t not in TYPES:
        errs.append(f"type must be one of {sorted(TYPES)}")
    if not entry.get("title"):
        errs.append("title missing")
    if not entry.get("url"):
        errs.append("url missing")
    qs = entry.get("questions")
    if not isinstance(qs, list) or not qs or any(q not in QUESTIONS for q in qs):
        errs.append("questions must be a non-empty list of 1..8")
    if entry.get("relevance") not in (1, 2, 3):
        errs.append("relevance must be 1, 2 or 3")
    if t == "paper":
        if not isinstance(entry.get("authors"), list) or not entry["authors"]:
            errs.append("paper needs authors")
        if not isinstance(entry.get("year"), int):
            errs.append("paper needs integer year")
    if t == "repo":
        for key in ("stars", "licence", "last_push"):
            if entry.get(key) in (None, ""):
                errs.append(f"repo needs {key}")
    return errs


def check_doi(entry, get=fetch):
    doi = entry.get("doi")
    if not doi:
        return []
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/")
    status, _, body = get(url)
    if status != 200:
        return [f"DOI {doi}: Crossref HTTP {status}"]
    titles = json.loads(body)["message"].get("title") or [""]
    ratio = difflib.SequenceMatcher(None, norm(entry["title"]), norm(titles[0])).ratio()
    if ratio < 0.95:
        return [f"DOI {doi}: Crossref title {titles[0]!r} does not match {entry['title']!r}"]
    return []


def check_pdf(entry, get=fetch):
    url = entry.get("pdf_url")
    if not url:
        return []
    status, ctype, _ = get(url)
    if status != 200:
        return [f"pdf_url HTTP {status}: {url}"]
    if "application/pdf" not in ctype.lower():
        return [f"pdf_url content type {ctype!r}: {url}"]
    return []


def check_repo(entry, get=fetch):
    if entry.get("type") != "repo":
        return []
    slug = urllib.parse.urlparse(entry["url"]).path.strip("/")
    status, _, body = get(f"https://api.github.com/repos/{slug}")
    if status != 200:
        return [f"repo {slug}: GitHub API HTTP {status}"]
    if json.loads(body).get("full_name", "").lower() != slug.lower():
        return [f"repo {slug}: full_name mismatch"]
    return []


def check_url(entry, get=fetch):
    if entry.get("type") == "repo" or entry.get("doi"):
        return []  # repos: check_repo; DOIs: check_doi (doi.org blocks scripted clients with HTTP 403)
    status, _, _ = get(entry["url"])
    if status is None or status >= 400:
        return [f"url HTTP {status}: {entry['url']}"]
    return []


def check_counts(entries):
    errs = []
    counts = {t: sum(1 for e in entries if e.get("type") == t) for t in MIN_COUNTS}
    for t, minimum in MIN_COUNTS.items():
        if counts[t] < minimum:
            errs.append(f"need at least {minimum} {t} entries, have {counts[t]}")
    for q in QUESTIONS:
        n = sum(1 for e in entries if q in e.get("questions", []))
        if n < MIN_PER_QUESTION:
            errs.append(f"question {q} has {n} sources, need {MIN_PER_QUESTION}")
    return errs, counts


def check_citations(entries, related_path=RELATED):
    if not os.path.exists(related_path):
        return [f"missing {related_path}"]
    with open(related_path, encoding="utf-8") as f:
        text = f.read()
    cited = set(re.findall(r"\[([a-z0-9]+(?:-[a-z0-9]+)+)\]", text))
    ids = {e["id"] for e in entries}
    errs = [f"related-work cites unknown id [{c}]" for c in sorted(cited - ids)]
    errs += [f"source {i} is never cited in related-work.md" for i in sorted(ids - cited)]
    return errs


def main(get=fetch):
    entries = load()
    results = []  # (ok, label, messages)

    seen = set()
    for e in entries:
        eid = e.get("id", "?")
        errs = []
        if eid in seen:
            errs.append("duplicate id")
        seen.add(eid)
        errs += check_schema(e)
        errs += check_doi(e, get)
        errs += check_pdf(e, get)
        errs += check_repo(e, get)
        errs += check_url(e, get)
        results.append((not errs, f"{e.get('type', '?'):8} {eid}", errs or ["ok"]))

    count_errs, counts = check_counts(entries)
    results.append((not count_errs, "counts", count_errs or [str(counts)]))
    cite_errs = check_citations(entries)
    results.append((not cite_errs, "citations", cite_errs or ["all cited, none missing"]))

    failed = 0
    for ok, label, msgs in results:
        print(f"{'PASS' if ok else 'FAIL'}  {label}")
        if not ok:
            failed += 1
            for m in msgs:
                print(f"        {m}")
    print(f"\n{len(results) - failed} of {len(results)} checks passed; counts {counts}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
