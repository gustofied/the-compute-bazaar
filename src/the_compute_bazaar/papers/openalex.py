"""OpenAlex candidate search for papers that mention training compute."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests


OPENALEX_WORKS_URL = "https://api.openalex.org/works"

DEFAULT_QUERIES = [
    "GPU-hours",
    "GPU hours",
    "large language model training compute tokens",
    "pretraining tokens GPU hours",
    "trained on A100 tokens language model",
    "trained on H100 tokens language model",
    "trained on H800 tokens",
    "training cost",
    "compute budget",
    "training FLOPs tokens GPU",
    "million GPU hours pretraining",
    "A100",
    "H100",
    "H800",
    "TPU hours",
]

DEFAULT_COMPUTE_TERMS = [
    "GPU-hours",
    "GPU hours",
    "GPU-days",
    "GPU days",
    "GPU-years",
    "GPU years",
    "A100",
    "V100",
    "H100",
    "H800",
    "TPU",
    "training cost",
    "compute budget",
    "cloud cost",
    "FLOPs",
    "tokens",
    "trained on",
    "experiments took",
]

CSV_FIELDS = [
    "status",
    "confidence",
    "compute_type",
    "model_name",
    "organization",
    "model_size",
    "training_tokens",
    "dataset_size",
    "accelerator",
    "gpu_count",
    "training_duration",
    "gpu_hours",
    "training_flops",
    "reported_cost",
    "estimated_cost",
    "evidence_quote",
    "title",
    "year",
    "matched_terms",
    "snippet",
    "pdf_url",
    "landing_page_url",
    "doi",
    "cited_by_count",
    "authors",
    "matched_query",
    "openalex_id",
    "is_open_access",
    "publication_date",
    "notes",
]

FULL_CSV_FIELDS = [
    *CSV_FIELDS,
    "abstract",
]


@dataclass(frozen=True)
class PaperCandidate:
    title: str
    year: int | None
    publication_date: str | None
    matched_query: str
    matched_terms: str
    snippet: str
    doi: str | None
    openalex_id: str
    landing_page_url: str | None
    pdf_url: str | None
    is_open_access: bool
    cited_by_count: int
    authors: str
    abstract: str


class OpenAlexClient:
    def __init__(
        self,
        *,
        api_key: str,
        mailto: str | None = None,
        session: requests.Session | None = None,
        timeout: int = 30,
        polite_sleep: float = 0.15,
    ) -> None:
        self.api_key = api_key
        self.mailto = mailto
        self.session = session or requests.Session()
        self.timeout = timeout
        self.polite_sleep = polite_sleep

    def search_works(
        self,
        *,
        query: str,
        from_date: str,
        to_date: str,
        max_results: int,
    ) -> Iterator[dict[str, Any]]:
        remaining = max_results
        cursor = "*"

        while remaining > 0:
            per_page = min(200, remaining)
            params = {
                "api_key": self.api_key,
                "search": query,
                "filter": f"from_publication_date:{from_date},to_publication_date:{to_date}",
                "per-page": str(per_page),
                "cursor": cursor,
                "select": ",".join(
                    [
                        "id",
                        "doi",
                        "display_name",
                        "publication_year",
                        "publication_date",
                        "cited_by_count",
                        "primary_location",
                        "open_access",
                        "authorships",
                        "abstract_inverted_index",
                    ]
                ),
            }
            if self.mailto:
                params["mailto"] = self.mailto

            response = self.session.get(OPENALEX_WORKS_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()

            results = payload.get("results") or []
            if not results:
                return

            for work in results:
                yield work
                remaining -= 1
                if remaining <= 0:
                    return

            cursor = (payload.get("meta") or {}).get("next_cursor")
            if not cursor:
                return
            time.sleep(self.polite_sleep)


def candidates_from_openalex(
    *,
    queries: Iterable[str],
    terms: Iterable[str],
    from_date: str,
    to_date: str,
    max_per_query: int,
    api_key: str,
    mailto: str | None = None,
    include_empty_matches: bool = True,
) -> Iterator[PaperCandidate]:
    client = OpenAlexClient(api_key=api_key, mailto=mailto)
    seen_ids: set[str] = set()

    for query in queries:
        for work in client.search_works(
            query=query,
            from_date=from_date,
            to_date=to_date,
            max_results=max_per_query,
        ):
            openalex_id = str(work.get("id") or "")
            if not openalex_id or openalex_id in seen_ids:
                continue
            seen_ids.add(openalex_id)

            candidate = candidate_from_work(work, query=query, terms=terms)
            if candidate.matched_terms or include_empty_matches:
                yield candidate


def candidate_from_work(
    work: dict[str, Any],
    *,
    query: str,
    terms: Iterable[str],
) -> PaperCandidate:
    title = clean_text(work.get("display_name") or "")
    abstract = abstract_from_inverted_index(work.get("abstract_inverted_index") or {})
    matched_terms = find_terms(" ".join([title, abstract]), terms)
    landing_page_url, pdf_url = location_urls(work.get("primary_location") or {})

    return PaperCandidate(
        title=title,
        year=work.get("publication_year"),
        publication_date=work.get("publication_date"),
        matched_query=query,
        matched_terms="; ".join(matched_terms),
        snippet=snippet_for_terms(abstract or title, matched_terms or [query]),
        doi=work.get("doi"),
        openalex_id=str(work.get("id") or ""),
        landing_page_url=landing_page_url,
        pdf_url=pdf_url,
        is_open_access=bool((work.get("open_access") or {}).get("is_oa")),
        cited_by_count=int(work.get("cited_by_count") or 0),
        authors=authors_from_work(work),
        abstract=abstract,
    )


def abstract_from_inverted_index(index: dict[str, list[int]]) -> str:
    if not index:
        return ""

    positioned: list[tuple[int, str]] = []
    for word, positions in index.items():
        positioned.extend((position, word) for position in positions)
    positioned.sort(key=lambda item: item[0])
    return clean_text(" ".join(word for _, word in positioned))


def authors_from_work(work: dict[str, Any], *, limit: int = 8) -> str:
    names: list[str] = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        name = author.get("display_name")
        if name:
            names.append(str(name))
    if len(names) > limit:
        return "; ".join(names[:limit]) + "; et al."
    return "; ".join(names)


def location_urls(location: dict[str, Any]) -> tuple[str | None, str | None]:
    landing_page_url = location.get("landing_page_url")
    pdf_url = location.get("pdf_url")
    return (
        str(landing_page_url) if landing_page_url else None,
        str(pdf_url) if pdf_url else None,
    )


def find_terms(text: str, terms: Iterable[str]) -> list[str]:
    matches: list[str] = []
    text_lower = text.lower()
    for term in terms:
        cleaned = term.strip()
        if cleaned and cleaned.lower() in text_lower and cleaned not in matches:
            matches.append(cleaned)
    return matches


def snippet_for_terms(text: str, terms: Iterable[str], *, max_chars: int = 500) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    lowered_terms = [term.lower() for term in terms if term.strip()]
    for sentence in sentences:
        sentence_lower = sentence.lower()
        if any(term in sentence_lower for term in lowered_terms):
            return truncate(sentence, max_chars)
    return truncate(cleaned, max_chars)


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def clean_text(value: str) -> str:
    return " ".join(str(value).split())


def write_csv(path: str, rows: Iterable[PaperCandidate], *, include_abstract: bool = False) -> int:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = FULL_CSV_FIELDS if include_abstract else CSV_FIELDS
    count = 0
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(candidate_csv_row(row, include_abstract=include_abstract))
            count += 1
    return count


def read_csv_rows(path: str) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def candidate_csv_row(candidate: PaperCandidate, *, include_abstract: bool = False) -> dict[str, Any]:
    row = {
        "status": "",
        "confidence": "",
        "compute_type": "",
        "model_name": "",
        "organization": "",
        "model_size": "",
        "training_tokens": "",
        "dataset_size": "",
        "accelerator": "",
        "gpu_count": "",
        "training_duration": "",
        "gpu_hours": "",
        "training_flops": "",
        "reported_cost": "",
        "estimated_cost": "",
        "evidence_quote": "",
        **asdict(candidate),
        "notes": "",
    }
    if not include_abstract:
        row.pop("abstract", None)
    return row


def candidate_html_row(candidate: PaperCandidate) -> dict[str, Any]:
    return candidate_csv_row(candidate, include_abstract=False)


def write_jsonl(path: str, rows: Iterable[PaperCandidate]) -> int:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(asdict(row), sort_keys=True) + "\n")
            count += 1
    return count


def write_html(path: str, rows: Iterable[Mapping[str, Any] | PaperCandidate]) -> int:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    clean_rows = [normalize_html_row(row) for row in rows]
    payload = json.dumps({"rows": clean_rows}, ensure_ascii=True).replace("</", "<\\/")
    output_path.write_text(HTML_TEMPLATE.replace("__DATA__", payload), encoding="utf-8")
    return len(clean_rows)


def normalize_html_row(row: Mapping[str, Any] | PaperCandidate) -> dict[str, str]:
    if isinstance(row, PaperCandidate):
        row = candidate_html_row(row)
    return {field: clean_text(row.get(field, "")) for field in CSV_FIELDS}


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpenAlex Compute Paper Candidates</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8f5;
      --ink: #1d2522;
      --muted: #5d6862;
      --line: #d9ded7;
      --panel: #ffffff;
      --accent: #0f766e;
      --accent-soft: #dff4ee;
      --warn: #a16207;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 3;
      border-bottom: 1px solid var(--line);
      background: rgba(247, 248, 245, 0.96);
      backdrop-filter: blur(10px);
    }
    .bar {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 16px;
      align-items: end;
      max-width: 1500px;
      margin: 0 auto;
      padding: 16px 20px;
    }
    h1 {
      margin: 0 0 6px;
      font-size: 20px;
      letter-spacing: 0;
    }
    .meta { color: var(--muted); font-size: 13px; }
    .tools {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
    }
    input, select, textarea, button {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      font: inherit;
    }
    input, select {
      min-height: 34px;
      padding: 6px 9px;
    }
    textarea {
      width: 100%;
      min-height: 68px;
      padding: 8px;
      resize: vertical;
    }
    button {
      min-height: 34px;
      padding: 6px 10px;
      cursor: pointer;
    }
    button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
    }
    main {
      max-width: 1500px;
      margin: 0 auto;
      padding: 18px 20px 32px;
    }
    .table-wrap {
      overflow: auto;
      border: 1px solid var(--line);
      background: var(--panel);
    }
    table {
      width: 100%;
      min-width: 1280px;
      border-collapse: collapse;
    }
    th, td {
      vertical-align: top;
      border-bottom: 1px solid var(--line);
      padding: 10px;
      text-align: left;
    }
    th {
      position: sticky;
      top: 83px;
      z-index: 2;
      background: #eef2ec;
      color: #33413b;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0;
      white-space: nowrap;
    }
    tr:hover td { background: #fbfcfa; }
    .review { width: 250px; }
    .paper { width: 410px; }
    .snippet { width: 430px; }
    .links { width: 150px; }
    .small { width: 110px; }
    .title {
      font-weight: 700;
      font-size: 15px;
      margin-bottom: 6px;
    }
    .authors, .subtle {
      color: var(--muted);
      font-size: 12px;
    }
    .terms {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      margin-top: 8px;
    }
    .term {
      border-radius: 999px;
      background: var(--accent-soft);
      color: #115e59;
      padding: 2px 7px;
      font-size: 12px;
    }
    a {
      color: #0f5f8f;
      text-decoration: none;
      font-weight: 600;
    }
    a:hover { text-decoration: underline; }
    .link-list {
      display: grid;
      gap: 6px;
    }
    .review-grid {
      display: grid;
      gap: 7px;
    }
    .review-grid label {
      display: grid;
      gap: 3px;
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .review-grid input, .review-grid select { width: 100%; }
    .empty {
      padding: 36px;
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--muted);
      text-align: center;
    }
    @media (max-width: 760px) {
      .bar { grid-template-columns: 1fr; align-items: start; }
      .tools { justify-content: flex-start; }
      th { top: 150px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <div>
        <h1>OpenAlex Compute Paper Candidates</h1>
        <div class="meta"><span id="count">0</span> visible. Edits are saved in this browser and can be exported.</div>
      </div>
      <div class="tools">
        <input id="search" type="search" placeholder="Search title, snippet, authors">
        <select id="statusFilter" aria-label="Status filter">
          <option value="">All statuses</option>
          <option value="candidate">Candidate</option>
          <option value="verified">Verified</option>
          <option value="reject">Reject</option>
          <option value="maybe">Maybe</option>
        </select>
        <select id="sort" aria-label="Sort">
          <option value="cited_by_count:desc">Citations high</option>
          <option value="year:desc">Year new</option>
          <option value="year:asc">Year old</option>
          <option value="title:asc">Title A-Z</option>
        </select>
        <button class="primary" id="exportCsv">Export CSV</button>
      </div>
    </div>
  </header>
  <main>
    <div id="tableMount"></div>
  </main>
  <script id="paper-data" type="application/json">__DATA__</script>
  <script>
    const baseRows = JSON.parse(document.getElementById("paper-data").textContent).rows;
    const storageKey = "compute-bazaar-openalex-review:" + location.pathname;
    const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
    const reviewFields = ["status", "compute_value", "compute_unit", "compute_scope", "notes"];
    const exportFields = [
      "status", "compute_value", "compute_unit", "compute_scope", "notes", "title", "year",
      "matched_terms", "snippet", "pdf_url", "landing_page_url", "doi", "cited_by_count",
      "authors", "matched_query", "openalex_id", "is_open_access", "publication_date"
    ];

    function rowKey(row, index) {
      return row.openalex_id || row.doi || String(index);
    }

    function mergedRows() {
      return baseRows.map((row, index) => ({...row, ...(saved[rowKey(row, index)] || {}), _index: index}));
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[char]));
    }

    function link(url, label) {
      if (!url) return "";
      return `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
    }

    function termPills(value) {
      return String(value || "").split(";").map(v => v.trim()).filter(Boolean)
        .map(v => `<span class="term">${escapeHtml(v)}</span>`).join("");
    }

    function filteredRows() {
      const query = document.getElementById("search").value.trim().toLowerCase();
      const status = document.getElementById("statusFilter").value;
      const [sortField, sortDir] = document.getElementById("sort").value.split(":");
      const rows = mergedRows().filter(row => {
        const text = [row.title, row.snippet, row.authors, row.matched_terms, row.notes].join(" ").toLowerCase();
        return (!query || text.includes(query)) && (!status || row.status === status);
      });
      rows.sort((a, b) => {
        const left = sortField === "title" ? String(a[sortField] || "") : Number(a[sortField] || 0);
        const right = sortField === "title" ? String(b[sortField] || "") : Number(b[sortField] || 0);
        const result = left > right ? 1 : left < right ? -1 : 0;
        return sortDir === "desc" ? -result : result;
      });
      return rows;
    }

    function reviewCell(row) {
      const key = rowKey(row, row._index);
      return `
        <div class="review-grid" data-key="${escapeHtml(key)}">
          <label>Status
            <select data-field="status">
              ${["", "candidate", "verified", "reject", "maybe"].map(v =>
                `<option value="${v}" ${row.status === v ? "selected" : ""}>${v || "blank"}</option>`
              ).join("")}
            </select>
          </label>
          <label>Compute value <input data-field="compute_value" value="${escapeHtml(row.compute_value)}"></label>
          <label>Unit <input data-field="compute_unit" value="${escapeHtml(row.compute_unit)}" placeholder="GPU-hours"></label>
          <label>Scope <input data-field="compute_scope" value="${escapeHtml(row.compute_scope)}" placeholder="training / experiments"></label>
          <label>Notes <textarea data-field="notes">${escapeHtml(row.notes)}</textarea></label>
        </div>`;
    }

    function render() {
      const rows = filteredRows();
      document.getElementById("count").textContent = `${rows.length} of ${baseRows.length}`;
      if (!rows.length) {
        document.getElementById("tableMount").innerHTML = `<div class="empty">No rows match the current filters.</div>`;
        return;
      }
      document.getElementById("tableMount").innerHTML = `
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th class="review">Review</th>
                <th class="paper">Paper</th>
                <th class="snippet">Snippet</th>
                <th class="links">Links</th>
                <th class="small">Year</th>
                <th class="small">Cites</th>
              </tr>
            </thead>
            <tbody>
              ${rows.map(row => `
                <tr>
                  <td class="review">${reviewCell(row)}</td>
                  <td class="paper">
                    <div class="title">${escapeHtml(row.title)}</div>
                    <div class="authors">${escapeHtml(row.authors)}</div>
                    <div class="subtle">Query: ${escapeHtml(row.matched_query)}</div>
                    <div class="terms">${termPills(row.matched_terms)}</div>
                  </td>
                  <td class="snippet">${escapeHtml(row.snippet)}</td>
                  <td class="links"><div class="link-list">
                    ${link(row.pdf_url, "PDF")}
                    ${link(row.landing_page_url, "Landing")}
                    ${link(row.doi, "DOI")}
                    ${link(row.openalex_id, "OpenAlex")}
                  </div></td>
                  <td>${escapeHtml(row.year)}</td>
                  <td>${escapeHtml(row.cited_by_count)}</td>
                </tr>`).join("")}
            </tbody>
          </table>
        </div>`;
    }

    function persistEdit(event) {
      const input = event.target.closest("[data-field]");
      if (!input) return;
      const wrapper = input.closest("[data-key]");
      const key = wrapper.dataset.key;
      saved[key] = saved[key] || {};
      saved[key][input.dataset.field] = input.value;
      localStorage.setItem(storageKey, JSON.stringify(saved));
    }

    function csvEscape(value) {
      const text = String(value ?? "");
      return /[",\\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    }

    function exportCsv() {
      const rows = mergedRows();
      const csv = [
        exportFields.join(","),
        ...rows.map(row => exportFields.map(field => csvEscape(row[field])).join(","))
      ].join("\\n");
      const blob = new Blob([csv], {type: "text/csv"});
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "openalex_review_export.csv";
      anchor.click();
      URL.revokeObjectURL(url);
    }

    document.getElementById("search").addEventListener("input", render);
    document.getElementById("statusFilter").addEventListener("change", render);
    document.getElementById("sort").addEventListener("change", render);
    document.getElementById("exportCsv").addEventListener("click", exportCsv);
    document.getElementById("tableMount").addEventListener("input", persistEdit);
    document.getElementById("tableMount").addEventListener("change", persistEdit);
    render();
  </script>
</body>
</html>
"""


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Compute Disclosure Review</title>
  <script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f3;
      --ink: #18211d;
      --muted: #5c6861;
      --line: #d8ded7;
      --panel: #ffffff;
      --panel-2: #eef4f0;
      --accent: #0f766e;
      --accent-2: #235789;
      --warn: #9a6700;
      --bad: #b42318;
      --good: #16803c;
      --shadow: 0 12px 30px rgba(24, 33, 29, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 5;
      background: rgba(244, 246, 243, 0.96);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(10px);
    }
    .topbar {
      max-width: 1680px;
      margin: 0 auto;
      padding: 14px 18px 10px;
    }
    .mast {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 16px;
      align-items: end;
    }
    h1 {
      margin: 0;
      font-size: 22px;
      letter-spacing: 0;
    }
    .subtitle {
      margin-top: 4px;
      color: var(--muted);
      font-size: 13px;
    }
    .actions, .filters, .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    .actions { justify-content: flex-end; }
    .filters { margin-top: 12px; }
    .tabs { margin-top: 10px; }
    input, select, textarea, button {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      font: inherit;
    }
    input, select, button {
      min-height: 34px;
      padding: 6px 10px;
    }
    textarea {
      width: 100%;
      min-height: 72px;
      padding: 9px;
      resize: vertical;
    }
    button {
      cursor: pointer;
      font-weight: 650;
    }
    button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
    }
    button.tab {
      background: transparent;
      border-color: transparent;
      color: var(--muted);
    }
    button.tab.active {
      background: var(--panel);
      border-color: var(--line);
      color: var(--ink);
      box-shadow: var(--shadow);
    }
    main {
      max-width: 1680px;
      margin: 0 auto;
      padding: 18px;
    }
    .view { display: none; }
    .view.active { display: block; }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(150px, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }
    .metric {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }
    .metric .label {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .metric .value {
      margin-top: 5px;
      font-size: 24px;
      font-weight: 750;
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(360px, 0.78fr) minmax(640px, 1.22fr);
      gap: 14px;
      align-items: start;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    .panel-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfa;
    }
    .panel-title {
      font-weight: 750;
    }
    .panel-meta {
      color: var(--muted);
      font-size: 12px;
    }
    .queue {
      max-height: calc(100vh - 255px);
      overflow: auto;
    }
    .queue-item {
      width: 100%;
      display: block;
      padding: 12px 14px;
      border: 0;
      border-bottom: 1px solid var(--line);
      border-radius: 0;
      background: #fff;
      text-align: left;
    }
    .queue-item:hover, .queue-item.active { background: #eef7f3; }
    .queue-title {
      font-weight: 720;
      line-height: 1.25;
    }
    .queue-meta {
      margin-top: 6px;
      color: var(--muted);
      font-size: 12px;
    }
    .pills {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      margin-top: 8px;
    }
    .pill {
      border-radius: 999px;
      background: var(--panel-2);
      color: #245247;
      padding: 2px 7px;
      font-size: 12px;
    }
    .detail-body {
      padding: 14px;
    }
    .paper-title {
      margin: 0 0 6px;
      font-size: 20px;
      letter-spacing: 0;
    }
    .muted { color: var(--muted); }
    .snippet {
      margin: 14px 0;
      padding: 12px;
      border-left: 4px solid var(--accent);
      background: #f7fbf8;
      border-radius: 4px;
    }
    .links {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 12px 0 4px;
    }
    a.link-button {
      display: inline-flex;
      align-items: center;
      min-height: 32px;
      padding: 5px 9px;
      border-radius: 6px;
      border: 1px solid var(--line);
      color: var(--accent-2);
      text-decoration: none;
      font-weight: 650;
      background: #fff;
    }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(130px, 1fr));
      gap: 10px;
      margin-top: 14px;
    }
    .wide { grid-column: span 2; }
    .full { grid-column: 1 / -1; }
    label {
      display: grid;
      gap: 4px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0;
    }
    label input, label select, label textarea {
      color: var(--ink);
      font-weight: 400;
      text-transform: none;
    }
    .dashboard-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(320px, 1fr));
      gap: 14px;
    }
    .chart {
      min-height: 310px;
      padding: 12px;
    }
    .chart svg {
      width: 100%;
      height: 260px;
      display: block;
    }
    .chart-title {
      font-weight: 750;
      margin-bottom: 8px;
    }
    .draft-layout {
      display: grid;
      grid-template-columns: minmax(360px, 0.9fr) minmax(460px, 1.1fr);
      gap: 14px;
    }
    .draft-box {
      padding: 14px;
    }
    .draft-box textarea {
      min-height: 170px;
      font-size: 14px;
    }
    .outline {
      display: grid;
      gap: 10px;
      padding: 14px;
    }
    .outline-item {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fff;
    }
    .outline-item strong { display: block; margin-bottom: 4px; }
    .empty {
      padding: 30px;
      color: var(--muted);
      text-align: center;
    }
    @media (max-width: 1080px) {
      .mast, .layout, .draft-layout { grid-template-columns: 1fr; }
      .metric-grid, .dashboard-grid { grid-template-columns: repeat(2, minmax(150px, 1fr)); }
      .queue { max-height: 360px; }
      .form-grid { grid-template-columns: repeat(2, minmax(130px, 1fr)); }
    }
    @media (max-width: 640px) {
      .metric-grid, .dashboard-grid, .form-grid { grid-template-columns: 1fr; }
      .wide { grid-column: auto; }
      .actions, .filters { align-items: stretch; }
      .actions > *, .filters > * { width: 100%; }
    }
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <div class="mast">
        <div>
          <h1>Compute Disclosure Review</h1>
          <div class="subtitle">Paper-level evidence for tokens, accelerators, GPU-hours, FLOPs, cost, and disclosure quality.</div>
        </div>
        <div class="actions">
          <button id="exportCsv" class="primary">Export CSV</button>
          <button id="exportJson">Export JSON</button>
        </div>
      </div>
      <div class="filters">
        <input id="search" type="search" placeholder="Search title, model, org, snippet">
        <select id="statusFilter" aria-label="Status">
          <option value="">All statuses</option>
          <option value="candidate">Candidate</option>
          <option value="verified">Verified</option>
          <option value="maybe">Maybe</option>
          <option value="reject">Reject</option>
        </select>
        <select id="confidenceFilter" aria-label="Confidence">
          <option value="">All confidence</option>
          <option value="exact">Exact</option>
          <option value="derived">Derived</option>
          <option value="estimated">Estimated</option>
          <option value="partial">Partial</option>
          <option value="ambiguous">Ambiguous</option>
          <option value="missing">Missing</option>
        </select>
        <select id="scopeFilter" aria-label="Compute type">
          <option value="">All compute types</option>
          <option value="pretrain">Pretrain</option>
          <option value="post-train">Post-train</option>
          <option value="ablation">Ablation</option>
          <option value="eval">Eval</option>
          <option value="inference">Inference</option>
          <option value="r&d">R&D</option>
          <option value="unclear">Unclear</option>
        </select>
        <select id="yearFilter" aria-label="Year">
          <option value="">All years</option>
        </select>
        <select id="sort" aria-label="Sort">
          <option value="cited_by_count:desc">Citations high</option>
          <option value="year:desc">Year new</option>
          <option value="year:asc">Year old</option>
          <option value="title:asc">Title A-Z</option>
        </select>
      </div>
      <div class="tabs">
        <button class="tab active" data-view="review">Review</button>
        <button class="tab" data-view="dashboard">Dashboard</button>
        <button class="tab" data-view="thesis">Thesis</button>
      </div>
    </div>
  </header>
  <main>
    <section id="review" class="view active">
      <div class="metric-grid" id="metrics"></div>
      <div class="layout">
        <section class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">Candidate Queue</div>
              <div class="panel-meta"><span id="count">0</span> visible</div>
            </div>
          </div>
          <div class="queue" id="queue"></div>
        </section>
        <section class="panel" id="detail"></section>
      </div>
    </section>
    <section id="dashboard" class="view">
      <div class="metric-grid" id="dashboardMetrics"></div>
      <div class="dashboard-grid">
        <section class="panel chart"><div class="chart-title">Disclosure Fields By Year</div><svg id="yearChart"></svg></section>
        <section class="panel chart"><div class="chart-title">Confidence Mix</div><svg id="confidenceChart"></svg></section>
        <section class="panel chart"><div class="chart-title">Compute Type Mix</div><svg id="scopeChart"></svg></section>
        <section class="panel chart"><div class="chart-title">Most Common Evidence Terms</div><svg id="termChart"></svg></section>
      </div>
    </section>
    <section id="thesis" class="view">
      <div class="draft-layout">
        <section class="panel draft-box">
          <div class="panel-title">Working Thesis</div>
          <textarea id="thesisText"></textarea>
          <div class="panel-title" style="margin-top:14px;">Research Notes</div>
          <textarea id="notesText"></textarea>
        </section>
        <section class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">Article Shape</div>
              <div class="panel-meta">Keep this as the spine while the evidence table improves.</div>
            </div>
          </div>
          <div class="outline">
            <div class="outline-item"><strong>Claim</strong><span>Epoch tracks notable models well, but paper-level compute disclosure remains uneven and under-measured.</span></div>
            <div class="outline-item"><strong>Dataset</strong><span>2023-2026 large-model papers, technical reports, and selected cost/inference disclosures.</span></div>
            <div class="outline-item"><strong>Measures</strong><span>Tokens, dataset size, accelerator, GPU count, GPU-hours, FLOPs, reported cost, estimated cost, compute type, and confidence.</span></div>
            <div class="outline-item"><strong>Main Charts</strong><span>Disclosure rates by year, confidence mix, compute type mix, and term coverage.</span></div>
            <div class="outline-item"><strong>Output</strong><span>A disclosure intelligence layer that complements Epoch rather than duplicating it.</span></div>
          </div>
        </section>
      </div>
    </section>
  </main>
  <script id="paper-data" type="application/json">__DATA__</script>
  <script>
    const baseRows = JSON.parse(document.getElementById("paper-data").textContent).rows;
    const storageKey = "compute-bazaar-review:" + location.pathname;
    const draftKey = storageKey + ":draft";
    const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
    const draft = JSON.parse(localStorage.getItem(draftKey) || "{}");
    const reviewFields = [
      "status", "confidence", "compute_type", "model_name", "organization", "model_size",
      "training_tokens", "dataset_size", "accelerator", "gpu_count", "training_duration",
      "gpu_hours", "training_flops", "reported_cost", "estimated_cost", "evidence_quote", "notes"
    ];
    const exportFields = [
      "status", "confidence", "compute_type", "model_name", "organization", "model_size",
      "training_tokens", "dataset_size", "accelerator", "gpu_count", "training_duration",
      "gpu_hours", "training_flops", "reported_cost", "estimated_cost", "evidence_quote",
      "title", "year", "matched_terms", "snippet", "pdf_url", "landing_page_url", "doi",
      "cited_by_count", "authors", "matched_query", "openalex_id", "is_open_access",
      "publication_date", "notes"
    ];
    const defaults = {
      thesisText: "Working thesis: AI labs increasingly disclose tokens, model size, and broad training setup, but paper-level disclosure of GPU-hours, full project compute, and dollar cost remains inconsistent. A paper-disclosure dataset can complement model-centric databases such as Epoch AI by measuring what papers make auditable.",
      notesText: "Batch 1: famous open technical reports from 2023-2026.\\nBatch 2: OpenAlex/arXiv candidates with GPU-hours, tokens, FLOPs, A100/H100/H800, TPU, cost terms.\\nMark each number as exact, derived, estimated, partial, ambiguous, missing."
    };
    let selectedKey = null;

    function rowKey(row, index) {
      return row.openalex_id || row.doi || String(index);
    }

    function mergedRows() {
      return baseRows.map((row, index) => ({...row, ...(saved[rowKey(row, index)] || {}), _index: index, _key: rowKey(row, index)}));
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[char]));
    }

    function asNumber(value) {
      const parsed = Number(String(value || "").replace(/[^0-9.eE+-]/g, ""));
      return Number.isFinite(parsed) ? parsed : 0;
    }

    function uniqueValues(field) {
      return Array.from(new Set(mergedRows().map(row => row[field]).filter(Boolean))).sort();
    }

    function fillYearFilter() {
      const select = document.getElementById("yearFilter");
      uniqueValues("year").forEach(year => {
        const option = document.createElement("option");
        option.value = year;
        option.textContent = year;
        select.appendChild(option);
      });
    }

    function filteredRows() {
      const query = document.getElementById("search").value.trim().toLowerCase();
      const status = document.getElementById("statusFilter").value;
      const confidence = document.getElementById("confidenceFilter").value;
      const scope = document.getElementById("scopeFilter").value;
      const year = document.getElementById("yearFilter").value;
      const [sortField, sortDir] = document.getElementById("sort").value.split(":");
      const rows = mergedRows().filter(row => {
        const text = [
          row.title, row.model_name, row.organization, row.snippet, row.authors,
          row.matched_terms, row.evidence_quote, row.notes
        ].join(" ").toLowerCase();
        return (!query || text.includes(query))
          && (!status || row.status === status)
          && (!confidence || row.confidence === confidence)
          && (!scope || row.compute_type === scope)
          && (!year || row.year === year);
      });
      rows.sort((a, b) => {
        const left = sortField === "title" ? String(a[sortField] || "") : asNumber(a[sortField]);
        const right = sortField === "title" ? String(b[sortField] || "") : asNumber(b[sortField]);
        const result = left > right ? 1 : left < right ? -1 : 0;
        return sortDir === "desc" ? -result : result;
      });
      return rows;
    }

    function saveReview(key, field, value) {
      saved[key] = saved[key] || {};
      saved[key][field] = value;
      localStorage.setItem(storageKey, JSON.stringify(saved));
    }

    function selectOptions(values, selected, blankLabel) {
      return [`<option value="">${blankLabel}</option>`, ...values.map(value =>
        `<option value="${escapeHtml(value)}" ${selected === value ? "selected" : ""}>${escapeHtml(value)}</option>`
      )].join("");
    }

    function fieldInput(row, field, label, attrs = "") {
      return `<label>${label}<input data-field="${field}" value="${escapeHtml(row[field])}" ${attrs}></label>`;
    }

    function link(url, label) {
      if (!url) return "";
      return `<a class="link-button" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
    }

    function pills(value) {
      return String(value || "").split(";").map(v => v.trim()).filter(Boolean)
        .map(v => `<span class="pill">${escapeHtml(v)}</span>`).join("");
    }

    function renderMetrics(rows = mergedRows(), mountId = "metrics") {
      const reviewed = rows.filter(row => row.status && row.status !== "candidate").length;
      const verified = rows.filter(row => row.status === "verified").length;
      const tokenRows = rows.filter(row => row.training_tokens).length;
      const gpuRows = rows.filter(row => row.gpu_hours || row.gpu_count || row.accelerator).length;
      const costRows = rows.filter(row => row.reported_cost || row.estimated_cost).length;
      const metrics = [
        ["Candidates", rows.length],
        ["Reviewed", reviewed],
        ["Verified", verified],
        ["Token Evidence", tokenRows],
        ["GPU/Cost Evidence", gpuRows + costRows],
      ];
      document.getElementById(mountId).innerHTML = metrics.map(([label, value]) =>
        `<div class="metric"><div class="label">${label}</div><div class="value">${value}</div></div>`
      ).join("");
    }

    function renderQueue() {
      const rows = filteredRows();
      document.getElementById("count").textContent = `${rows.length} of ${baseRows.length}`;
      if (!rows.length) {
        document.getElementById("queue").innerHTML = `<div class="empty">No candidates match the filters.</div>`;
        document.getElementById("detail").innerHTML = `<div class="empty">No paper selected.</div>`;
        renderMetrics(rows);
        return;
      }
      if (!selectedKey || !rows.some(row => row._key === selectedKey)) selectedKey = rows[0]._key;
      document.getElementById("queue").innerHTML = rows.map(row => `
        <button class="queue-item ${row._key === selectedKey ? "active" : ""}" data-key="${escapeHtml(row._key)}">
          <div class="queue-title">${escapeHtml(row.title)}</div>
          <div class="queue-meta">${escapeHtml(row.year)} · ${escapeHtml(row.authors)} · ${escapeHtml(row.cited_by_count)} cites</div>
          <div class="pills">${pills(row.matched_terms)}${row.confidence ? `<span class="pill">${escapeHtml(row.confidence)}</span>` : ""}</div>
        </button>
      `).join("");
      renderDetail(rows.find(row => row._key === selectedKey));
      renderMetrics(rows);
    }

    function renderDetail(row) {
      if (!row) return;
      document.getElementById("detail").innerHTML = `
        <div class="panel-head">
          <div>
            <div class="panel-title">Evidence Review</div>
            <div class="panel-meta">${escapeHtml(row.publication_date || row.year)} · ${escapeHtml(row.matched_query)}</div>
          </div>
        </div>
        <div class="detail-body" data-key="${escapeHtml(row._key)}">
          <h2 class="paper-title">${escapeHtml(row.title)}</h2>
          <div class="muted">${escapeHtml(row.authors)}</div>
          <div class="links">
            ${link(row.pdf_url, "PDF")}
            ${link(row.landing_page_url, "Landing")}
            ${link(row.doi, "DOI")}
            ${link(row.openalex_id, "OpenAlex")}
          </div>
          <div class="snippet">${escapeHtml(row.snippet)}</div>
          <div class="pills">${pills(row.matched_terms)}</div>
          <div class="form-grid">
            <label>Status<select data-field="status">${selectOptions(["candidate", "verified", "maybe", "reject"], row.status, "blank")}</select></label>
            <label>Confidence<select data-field="confidence">${selectOptions(["exact", "derived", "estimated", "partial", "ambiguous", "missing"], row.confidence, "blank")}</select></label>
            <label>Compute type<select data-field="compute_type">${selectOptions(["pretrain", "post-train", "ablation", "eval", "inference", "r&d", "unclear"], row.compute_type, "blank")}</select></label>
            ${fieldInput(row, "model_name", "Model name")}
            ${fieldInput(row, "organization", "Organization")}
            ${fieldInput(row, "model_size", "Model size", 'placeholder="70B"')}
            ${fieldInput(row, "training_tokens", "Training tokens", 'placeholder="2T"')}
            ${fieldInput(row, "dataset_size", "Dataset size")}
            ${fieldInput(row, "accelerator", "Accelerator", 'placeholder="A100 / H100 / H800"')}
            ${fieldInput(row, "gpu_count", "GPU count")}
            ${fieldInput(row, "training_duration", "Duration", 'placeholder="21 days"')}
            ${fieldInput(row, "gpu_hours", "GPU-hours")}
            ${fieldInput(row, "training_flops", "FLOPs")}
            ${fieldInput(row, "reported_cost", "Reported cost")}
            ${fieldInput(row, "estimated_cost", "Estimated cost")}
            <label class="full">Evidence quote<textarea data-field="evidence_quote">${escapeHtml(row.evidence_quote)}</textarea></label>
            <label class="full">Notes<textarea data-field="notes">${escapeHtml(row.notes)}</textarea></label>
          </div>
        </div>`;
    }

    function countBy(rows, field) {
      const counts = new Map();
      rows.forEach(row => {
        const value = row[field] || "blank";
        counts.set(value, (counts.get(value) || 0) + 1);
      });
      return Array.from(counts, ([key, value]) => ({key, value})).sort((a, b) => b.value - a.value);
    }

    function termCounts(rows) {
      const counts = new Map();
      rows.forEach(row => String(row.matched_terms || "").split(";").map(v => v.trim()).filter(Boolean)
        .forEach(term => counts.set(term, (counts.get(term) || 0) + 1)));
      return Array.from(counts, ([key, value]) => ({key, value})).sort((a, b) => b.value - a.value).slice(0, 12);
    }

    function disclosureByYear(rows) {
      const fields = ["training_tokens", "accelerator", "gpu_hours", "training_flops", "reported_cost"];
      const years = Array.from(new Set(rows.map(row => row.year).filter(Boolean))).sort();
      return years.map(year => {
        const yearRows = rows.filter(row => row.year === year);
        const result = {year};
        fields.forEach(field => result[field] = yearRows.filter(row => row[field]).length);
        return result;
      });
    }

    function drawBarChart(selector, data, color = "#0f766e") {
      if (!window.d3) {
        drawPlainBarChart(selector, data, color);
        return;
      }
      const svg = d3.select(selector);
      svg.selectAll("*").remove();
      const node = svg.node();
      const width = node.clientWidth || 520;
      const height = 250;
      const margin = {top: 12, right: 16, bottom: 54, left: 42};
      svg.attr("viewBox", `0 0 ${width} ${height}`);
      const x = d3.scaleBand().domain(data.map(d => d.key)).range([margin.left, width - margin.right]).padding(0.22);
      const y = d3.scaleLinear().domain([0, d3.max(data, d => d.value) || 1]).nice().range([height - margin.bottom, margin.top]);
      svg.append("g").attr("transform", `translate(0,${height - margin.bottom})`).call(d3.axisBottom(x)).selectAll("text")
        .attr("transform", "rotate(-32)").style("text-anchor", "end");
      svg.append("g").attr("transform", `translate(${margin.left},0)`).call(d3.axisLeft(y).ticks(5));
      svg.append("g").selectAll("rect").data(data).join("rect")
        .attr("x", d => x(d.key)).attr("y", d => y(d.value))
        .attr("width", x.bandwidth()).attr("height", d => y(0) - y(d.value))
        .attr("fill", color).attr("rx", 3);
      svg.append("g").selectAll("text.value").data(data).join("text")
        .attr("x", d => x(d.key) + x.bandwidth() / 2).attr("y", d => y(d.value) - 5)
        .attr("text-anchor", "middle").attr("font-size", 11).text(d => d.value);
    }

    function drawDisclosureChart(selector, data) {
      if (!window.d3) {
        drawPlainDisclosureChart(selector, data);
        return;
      }
      const keys = ["training_tokens", "accelerator", "gpu_hours", "training_flops", "reported_cost"];
      const colors = ["#0f766e", "#235789", "#9a6700", "#6b5ca5", "#b42318"];
      const svg = d3.select(selector);
      svg.selectAll("*").remove();
      const node = svg.node();
      const width = node.clientWidth || 560;
      const height = 250;
      const margin = {top: 12, right: 92, bottom: 38, left: 36};
      svg.attr("viewBox", `0 0 ${width} ${height}`);
      const x = d3.scaleBand().domain(data.map(d => d.year)).range([margin.left, width - margin.right]).padding(0.18);
      const y = d3.scaleLinear().domain([0, d3.max(data, d => d3.max(keys, key => d[key])) || 1]).nice().range([height - margin.bottom, margin.top]);
      const inner = x.bandwidth() / keys.length;
      svg.append("g").attr("transform", `translate(0,${height - margin.bottom})`).call(d3.axisBottom(x));
      svg.append("g").attr("transform", `translate(${margin.left},0)`).call(d3.axisLeft(y).ticks(5));
      keys.forEach((key, index) => {
        svg.append("g").selectAll(`rect.${key}`).data(data).join("rect")
          .attr("x", d => x(d.year) + index * inner)
          .attr("y", d => y(d[key]))
          .attr("width", Math.max(2, inner - 1))
          .attr("height", d => y(0) - y(d[key]))
          .attr("fill", colors[index]);
        svg.append("text").attr("x", width - margin.right + 12).attr("y", 20 + index * 18)
          .attr("fill", colors[index]).attr("font-size", 11).text(key.replace("_", " "));
      });
    }

    function svgEl(name) {
      return document.createElementNS("http://www.w3.org/2000/svg", name);
    }

    function drawPlainBarChart(selector, data, color = "#0f766e") {
      const svg = document.querySelector(selector);
      svg.innerHTML = "";
      const width = svg.clientWidth || 520;
      const height = 250;
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      const margin = {top: 16, right: 18, bottom: 58, left: 40};
      const maxValue = Math.max(1, ...data.map(d => d.value));
      const step = (width - margin.left - margin.right) / Math.max(1, data.length);
      data.forEach((d, index) => {
        const barWidth = Math.max(8, step * 0.64);
        const x = margin.left + index * step + (step - barWidth) / 2;
        const barHeight = (height - margin.top - margin.bottom) * (d.value / maxValue);
        const y = height - margin.bottom - barHeight;
        const rect = svgEl("rect");
        rect.setAttribute("x", x);
        rect.setAttribute("y", y);
        rect.setAttribute("width", barWidth);
        rect.setAttribute("height", barHeight);
        rect.setAttribute("rx", 3);
        rect.setAttribute("fill", color);
        svg.appendChild(rect);
        const value = svgEl("text");
        value.setAttribute("x", x + barWidth / 2);
        value.setAttribute("y", y - 5);
        value.setAttribute("text-anchor", "middle");
        value.setAttribute("font-size", "11");
        value.textContent = d.value;
        svg.appendChild(value);
        const label = svgEl("text");
        label.setAttribute("x", x + barWidth / 2);
        label.setAttribute("y", height - 30);
        label.setAttribute("text-anchor", "end");
        label.setAttribute("font-size", "10");
        label.setAttribute("transform", `rotate(-32 ${x + barWidth / 2} ${height - 30})`);
        label.textContent = d.key;
        svg.appendChild(label);
      });
      drawPlainAxis(svg, margin, width, height);
    }

    function drawPlainDisclosureChart(selector, data) {
      const svg = document.querySelector(selector);
      svg.innerHTML = "";
      const width = svg.clientWidth || 560;
      const height = 250;
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      const margin = {top: 16, right: 100, bottom: 38, left: 36};
      const keys = ["training_tokens", "accelerator", "gpu_hours", "training_flops", "reported_cost"];
      const colors = ["#0f766e", "#235789", "#9a6700", "#6b5ca5", "#b42318"];
      const maxValue = Math.max(1, ...data.flatMap(d => keys.map(key => d[key] || 0)));
      const groupStep = (width - margin.left - margin.right) / Math.max(1, data.length);
      const barWidth = Math.max(2, (groupStep * 0.72) / keys.length);
      data.forEach((d, groupIndex) => {
        keys.forEach((key, keyIndex) => {
          const value = d[key] || 0;
          const x = margin.left + groupIndex * groupStep + keyIndex * barWidth;
          const barHeight = (height - margin.top - margin.bottom) * (value / maxValue);
          const y = height - margin.bottom - barHeight;
          const rect = svgEl("rect");
          rect.setAttribute("x", x);
          rect.setAttribute("y", y);
          rect.setAttribute("width", Math.max(2, barWidth - 1));
          rect.setAttribute("height", barHeight);
          rect.setAttribute("fill", colors[keyIndex]);
          svg.appendChild(rect);
        });
        const label = svgEl("text");
        label.setAttribute("x", margin.left + groupIndex * groupStep + groupStep * 0.34);
        label.setAttribute("y", height - 14);
        label.setAttribute("text-anchor", "middle");
        label.setAttribute("font-size", "11");
        label.textContent = d.year;
        svg.appendChild(label);
      });
      keys.forEach((key, index) => {
        const label = svgEl("text");
        label.setAttribute("x", width - margin.right + 12);
        label.setAttribute("y", 22 + index * 18);
        label.setAttribute("fill", colors[index]);
        label.setAttribute("font-size", "11");
        label.textContent = key.replace("_", " ");
        svg.appendChild(label);
      });
      drawPlainAxis(svg, margin, width, height);
    }

    function drawPlainAxis(svg, margin, width, height) {
      const xAxis = svgEl("line");
      xAxis.setAttribute("x1", margin.left);
      xAxis.setAttribute("x2", width - margin.right);
      xAxis.setAttribute("y1", height - margin.bottom);
      xAxis.setAttribute("y2", height - margin.bottom);
      xAxis.setAttribute("stroke", "#9aa59f");
      svg.appendChild(xAxis);
      const yAxis = svgEl("line");
      yAxis.setAttribute("x1", margin.left);
      yAxis.setAttribute("x2", margin.left);
      yAxis.setAttribute("y1", margin.top);
      yAxis.setAttribute("y2", height - margin.bottom);
      yAxis.setAttribute("stroke", "#9aa59f");
      svg.appendChild(yAxis);
    }

    function renderDashboard() {
      const rows = mergedRows();
      renderMetrics(rows, "dashboardMetrics");
      drawDisclosureChart("#yearChart", disclosureByYear(rows));
      drawBarChart("#confidenceChart", countBy(rows, "confidence"), "#235789");
      drawBarChart("#scopeChart", countBy(rows, "compute_type"), "#9a6700");
      drawBarChart("#termChart", termCounts(rows), "#0f766e");
    }

    function csvEscape(value) {
      const text = String(value ?? "");
      return /[",\\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    }

    function exportCsv() {
      const rows = mergedRows();
      const csv = [
        exportFields.join(","),
        ...rows.map(row => exportFields.map(field => csvEscape(row[field])).join(","))
      ].join("\\n");
      download("compute_disclosure_review.csv", csv, "text/csv");
    }

    function exportJson() {
      download("compute_disclosure_review.json", JSON.stringify({rows: mergedRows(), draft: readDraft()}, null, 2), "application/json");
    }

    function download(filename, content, type) {
      const blob = new Blob([content], {type});
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    }

    function readDraft() {
      return {
        thesisText: document.getElementById("thesisText").value,
        notesText: document.getElementById("notesText").value,
      };
    }

    function saveDraft() {
      localStorage.setItem(draftKey, JSON.stringify(readDraft()));
    }

    function renderAll() {
      renderQueue();
      renderDashboard();
    }

    fillYearFilter();
    document.getElementById("thesisText").value = draft.thesisText || defaults.thesisText;
    document.getElementById("notesText").value = draft.notesText || defaults.notesText;
    document.getElementById("queue").addEventListener("click", event => {
      const item = event.target.closest("[data-key]");
      if (!item) return;
      selectedKey = item.dataset.key;
      renderQueue();
    });
    document.getElementById("detail").addEventListener("input", event => {
      const input = event.target.closest("[data-field]");
      if (!input) return;
      const wrapper = input.closest("[data-key]");
      saveReview(wrapper.dataset.key, input.dataset.field, input.value);
      renderDashboard();
    });
    document.getElementById("detail").addEventListener("change", event => {
      const input = event.target.closest("[data-field]");
      if (!input) return;
      const wrapper = input.closest("[data-key]");
      saveReview(wrapper.dataset.key, input.dataset.field, input.value);
      renderQueue();
    });
    ["search", "statusFilter", "confidenceFilter", "scopeFilter", "yearFilter", "sort"].forEach(id => {
      document.getElementById(id).addEventListener("input", renderAll);
      document.getElementById(id).addEventListener("change", renderAll);
    });
    document.querySelectorAll("button.tab").forEach(button => button.addEventListener("click", () => {
      document.querySelectorAll("button.tab").forEach(tab => tab.classList.toggle("active", tab === button));
      document.querySelectorAll(".view").forEach(view => view.classList.toggle("active", view.id === button.dataset.view));
      if (button.dataset.view === "dashboard") renderDashboard();
    }));
    document.getElementById("exportCsv").addEventListener("click", exportCsv);
    document.getElementById("exportJson").addEventListener("click", exportJson);
    document.getElementById("thesisText").addEventListener("input", saveDraft);
    document.getElementById("notesText").addEventListener("input", saveDraft);
    renderAll();
  </script>
</body>
</html>
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="openalex-papers",
        description="Find candidate papers that may report AI training compute.",
    )
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="OpenAlex search query. Repeat for multiple queries. Defaults to compute-related seeds.",
    )
    parser.add_argument(
        "--term",
        action="append",
        dest="terms",
        help="Local term to mark in title/abstract snippets. Repeat for multiple terms.",
    )
    parser.add_argument("--from-date", default="2023-01-01")
    parser.add_argument("--to-date", default="2026-12-31")
    parser.add_argument("--max-per-query", type=int, default=50)
    parser.add_argument("--out", default="data/papers/openalex_candidates.csv")
    parser.add_argument("--html", help="Optional standalone HTML review table output path.")
    parser.add_argument("--from-csv", help="Render an existing candidate CSV to HTML without calling OpenAlex.")
    parser.add_argument(
        "--include-abstract",
        action="store_true",
        help="Include full abstracts in the CSV. JSONL always includes abstracts.",
    )
    parser.add_argument("--jsonl", help="Optional JSONL output path for raw-ish candidate rows.")
    parser.add_argument(
        "--api-key",
        default=os.getenv("OPENALEX_API_KEY"),
        help="OpenAlex API key. Can also use OPENALEX_API_KEY.",
    )
    parser.add_argument(
        "--mailto",
        default=os.getenv("OPENALEX_MAILTO"),
        help="Optional email to identify your client. Can also use OPENALEX_MAILTO.",
    )
    parser.add_argument(
        "--only-with-term-hit",
        action="store_true",
        help="Drop rows where OpenAlex found the query but title/abstract did not include a local term.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.from_csv:
        if not args.html:
            raise SystemExit("--from-csv requires --html")
        html_count = write_html(args.html, read_csv_rows(args.from_csv))
        print(f"Wrote {html_count} OpenAlex candidates to {args.html}", file=sys.stderr)
        return

    queries = args.queries or DEFAULT_QUERIES
    terms = args.terms or DEFAULT_COMPUTE_TERMS
    if not args.api_key:
        raise SystemExit(
            "Missing OpenAlex API key. Set OPENALEX_API_KEY or pass --api-key. "
            "Create a free key at https://openalex.org/settings/api"
        )

    rows = list(
        candidates_from_openalex(
            queries=queries,
            terms=terms,
            from_date=args.from_date,
            to_date=args.to_date,
            max_per_query=args.max_per_query,
            api_key=args.api_key,
            mailto=args.mailto,
            include_empty_matches=not args.only_with_term_hit,
        )
    )

    csv_count = write_csv(args.out, rows, include_abstract=args.include_abstract)
    message = f"Wrote {csv_count} OpenAlex candidates to {args.out}"

    if args.html:
        html_count = write_html(args.html, (candidate_html_row(row) for row in rows))
        message += f" and {html_count} rows to {args.html}"

    if args.jsonl:
        jsonl_count = write_jsonl(args.jsonl, rows)
        message += f" and {jsonl_count} rows to {args.jsonl}"

    print(message, file=sys.stderr)


if __name__ == "__main__":
    main()
