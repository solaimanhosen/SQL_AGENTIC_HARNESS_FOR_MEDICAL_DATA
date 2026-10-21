"""One answer as a self-contained HTML report.

The report is rendered from the same answer the service sends and the conversation stores,
so a report made from the command line, from a live answer or from a conversation reopened
a week later reads the same. It holds the narrative, the charts, the definitions and their
status, and the SQL with the rows behind every finding.

It needs nothing else to open. The styles are inline, the charts are inline SVG, and there
is no script and no external reference. A Content-Security-Policy forbids loading anything
at all, so a reference that slipped in could not reach the network. Every value is escaped:
answers, labels and rows are data, and a stored row may hold text written to look like
markup or instructions.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from html import escape
from typing import Any

from .charts import chart_svg, format_value
from .payload import AnswerOut, QueryOut

CONTENT_SECURITY_POLICY = "default-src 'none'; style-src 'unsafe-inline'"
CONVERSATION_ID = re.compile(r"^[0-9a-f]{32}$")
STATUS_LABELS = {
    "confirmed": "Confirmed",
    "assumed": "Assumed, not yet confirmed",
    "unknown": "Not a shared definition",
}


def report_filename(answer: AnswerOut) -> str:
    """Matches the interface's other downloads: the conversation, the question, the kind."""
    return f"{answer.conversation_id[:8]}-turn{answer.turn}-report.html"


def render_report(answer: AnswerOut, *, generated_at: datetime, earlier_questions: Sequence[str] = ()) -> str:
    body = "\n".join(
        [
            _header(answer, earlier_questions),
            _answer(answer),
            _evidence(answer),
            _footer(answer, generated_at),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CONTENT_SECURITY_POLICY}">
<meta name="generator" content="SQL agent">
<title>{_e(_shorten(answer.question, 80))} | SQL agent report</title>
<style>{STYLE}</style>
</head>
<body>
<main>
{body}
</main>
</body>
</html>
"""


def _header(answer: AnswerOut, earlier_questions: Sequence[str]) -> str:
    meta = [f"Data as of {answer.as_of.isoformat()}", answer.model]
    if CONVERSATION_ID.match(answer.conversation_id):
        meta.append(f"conversation {answer.conversation_id[:8]}, question {answer.turn}")
    parts = [
        "<header>",
        '<p class="kicker">SQL agent report · synthetic Synthea data</p>',
        f"<h1>{_e(answer.question)}</h1>",
        f'<p class="meta">{_e(" · ".join(meta))}</p>',
    ]
    if earlier_questions:
        parts.append('<div class="context"><p>A follow-up. The questions asked before it, as context:</p><ol>')
        parts += [f"<li>{_e(question)}</li>" for question in earlier_questions]
        parts.append("</ol></div>")
    parts.append("</header>")
    return "\n".join(parts)


def _answer(answer: AnswerOut) -> str:
    ran = {query.number for query in answer.queries if query.ok and query.number is not None}
    parts = ['<section class="answer">']
    if not answer.structured:
        parts.append(f'<pre class="prose">{_e(answer.answer)}</pre>')
        parts.append(
            '<p class="warning">This answer came back as plain text, so its figures are not linked to queries.</p>'
        )
    else:
        parts.append(f'<p class="headline">{_e(answer.headline or "")}</p>')
        if answer.findings:
            parts.append("<h2>Findings</h2><ul class=\"findings\">")
            for finding in answer.findings:
                cites = "".join(
                    f' <a class="cite" href="#q{number}">Query {number}</a>'
                    if number in ran
                    else f' <span class="cite uncited">Query {number} did not run</span>'
                    for number in finding.query_numbers
                ) or ' <span class="cite uncited">No query cited</span>'
                parts.append(f"<li>{_e(finding.statement)}{cites}</li>")
            parts.append("</ul>")
        parts += [_chart(chart) for chart in answer.charts]
        window = answer.time_window.description if answer.time_window else "not stated"
        parts.append(
            '<dl class="facts">'
            f"<div><dt>Time window</dt><dd>{_e(window)}</dd></div>"
            f"<div><dt>As-of date</dt><dd>{answer.as_of.isoformat()}</dd></div>"
            "</dl>"
        )
        if answer.definitions_used:
            parts.append('<h2>Definitions used</h2><ul class="definitions">')
            for definition in answer.definitions_used:
                code = f" <code>{_e(definition.name)}</code>" if definition.status != "unknown" else ""
                summary = (
                    definition.summary if definition.status != "unknown" else "The agent chose its own meaning for this term."
                )
                parts.append(
                    f'<li><span class="label">{_e(definition.label)}</span>{code} '
                    f'<span class="badge {definition.status}">{STATUS_LABELS[definition.status]}</span>'
                    f"<p>{_e(summary)}</p></li>"
                )
            parts.append("</ul>")
        for title, items in (("Assumptions", answer.assumptions), ("Caveats", answer.caveats)):
            if items:
                parts.append(f"<h2>{title}</h2><ul>" + "".join(f"<li>{_e(item)}</li>" for item in items) + "</ul>")
    parts.append(_warnings(answer))
    parts.append("</section>")
    return "\n".join(part for part in parts if part)


def _chart(chart: Any) -> str:
    legend = ""
    if len(chart.series) > 1:
        legend = f'<ul class="legend {chart.kind}">' + "".join(
            f'<li><span class="key s{index % 8 + 1}"></span>{_e(series.name)}</li>'
            for index, series in enumerate(chart.series)
        ) + "</ul>"
    axis = _e(chart.x_label) + (f" · {_e(chart.y_label)}" if chart.y_label else "")
    return (
        '<figure class="chart">'
        f'<figcaption><span class="title">{_e(chart.title)}</span> '
        f'<a class="cite" href="#q{chart.query_number}">Query {chart.query_number}</a></figcaption>'
        f'{legend}<div class="plot">{chart_svg(chart)}</div><p class="axis">{axis}</p>'
        "</figure>"
    )


def _warnings(answer: AnswerOut) -> str:
    issues = answer.issues
    if not issues.any:
        return ""
    items = []
    if issues.unknown_definitions:
        items.append(f"Named definitions that do not exist: {', '.join(issues.unknown_definitions)}")
    if issues.missing_query_numbers:
        items.append(f"Cited query numbers that did not run: {', '.join(map(str, issues.missing_query_numbers))}")
    if issues.window_not_in_sql:
        items.append(f"Time window not backed by SQL: {issues.window_not_in_sql}")
    items += [f"No query cited for: {statement}" for statement in issues.unsupported_findings]
    items += [f"Chart not drawn, {problem}" for problem in issues.chart_problems]
    return (
        '<div class="warning" role="note"><h2>Traceability warnings</h2><ul>'
        + "".join(f"<li>{_e(item)}</li>" for item in items)
        + "</ul></div>"
    )


def _evidence(answer: AnswerOut) -> str:
    ran = [query for query in answer.queries if query.ok]
    failed = [query for query in answer.queries if not query.ok]
    parts = ['<section class="evidence">', "<h2>How the answer was reached</h2>"]
    if ran:
        parts.append(
            "<p class=\"note\">Every query below ran, read-only, against the database. A finding's "
            "query number points at the SQL and the rows it came from.</p>"
        )
    parts += [_query(query) for query in ran]
    if failed:
        parts.append(
            f'<h3 class="failed-title">{len(failed)} failed {"attempt" if len(failed) == 1 else "attempts"}</h3>'
            '<p class="note">No figure in the answer comes from these.</p>'
        )
        parts += [
            f'<div class="query bad"><pre><code>{_e(query.sql)}</code></pre><p class="error">{_e(query.error or "")}</p></div>'
            for query in failed
        ]
    parts.append("</section>")
    return "\n".join(parts)


def _query(query: QueryOut) -> str:
    if query.analysis:
        head = f"computed a {query.analysis.label}"
    else:
        rows = query.row_count or 0
        head = f"{rows:,} {'row' if rows == 1 else 'rows'}"
    if query.elapsed_ms is not None:
        head += f" in {round(query.elapsed_ms)} ms"
    parts = [
        f'<article class="query" id="q{query.number}">',
        f"<h3>Query {query.number} <span>· {_e(head)}</span></h3>",
        f"<pre><code>{_e(query.sql)}</code></pre>",
    ]
    if query.analysis:
        parts.append(
            '<ul class="analysis">' + "".join(f"<li>{_e(line)}</li>" for line in query.analysis.summary) + "</ul>"
        )
    if query.truncated:
        parts.append('<p class="note cut">More rows matched, and only these were kept.</p>')
    if not query.rows and (query.row_count or 0) > 0:
        parts.append('<p class="note">The rows were not kept with this conversation, by the service\'s setting.</p>')
    elif query.columns:
        parts.append(_table(query.columns, query.rows))
    parts.append("</article>")
    return "\n".join(parts)


def _table(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    numeric = [
        all(isinstance(row[index], (int, float)) and not isinstance(row[index], bool) for row in rows if row[index] is not None)
        and any(row[index] is not None for row in rows)
        for index in range(len(columns))
    ]
    head = "".join(f'<th scope="col"{_num(numeric[index])}>{_e(column)}</th>' for index, column in enumerate(columns))
    body = "".join(
        "<tr>" + "".join(_cell(value, numeric[index]) for index, value in enumerate(row)) + "</tr>" for row in rows
    )
    return f'<div class="table"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _cell(value: Any, numeric: bool) -> str:
    if value is None:
        return '<td class="null">null</td>'
    if isinstance(value, float):
        text = format_value(value)
    elif isinstance(value, int) and not isinstance(value, bool):
        text = f"{value:,}" if abs(value) >= 10_000 else str(value)
    else:
        text = str(value)
    return f"<td{_num(numeric)}>{_e(text)}</td>"


def _num(numeric: bool) -> str:
    return ' class="num"' if numeric else ""


def _footer(answer: AnswerOut, generated_at: datetime) -> str:
    tokens = f"{answer.input_tokens:,} in and {answer.output_tokens:,} out tokens"
    return (
        "<footer>"
        f"<p>Answered in {answer.elapsed_s:g} s with {_e(answer.model)}, using {tokens}. "
        f"Report generated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}.</p>"
        "<p>The definitions, their status, the time window's dates and every query and row above come "
        "from the agent's own records of the run, not from the model's text. The data is synthetic "
        "(Synthea), and query results were sent to the Anthropic API to write the answer.</p>"
        "</footer>"
    )


def _e(text: object) -> str:
    return escape(str(text), quote=True)


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


STYLE = """
:root {
  color-scheme: light dark;
  --bg: #f7f7f5; --surface: #ffffff; --text: #1d1f23; --muted: #5f6570; --border: #dcdde0;
  --accent: #2f5bd3; --chip: #eef0f4; --code-bg: #f1f2f4;
  --warning-bg: #fff4d6; --warning-text: #6b4e00; --ok-bg: #dff3e4; --ok-text: #14532d;
  --grid: #ebebe8; --axis: #c3c2b7;
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a; --series-4: #eda100;
  --series-5: #e87ba4; --series-6: #008300; --series-7: #4a3aa7; --series-8: #e34948;
}
@media screen and (prefers-color-scheme: dark) {
  :root {
    --bg: #15171a; --surface: #1e2125; --text: #e6e7ea; --muted: #9aa0aa; --border: #33373d;
    --accent: #7b9cff; --chip: #2a2e34; --code-bg: #15171a;
    --warning-bg: #3a3018; --warning-text: #f3d68a; --ok-bg: #173524; --ok-text: #9be3b4;
    --grid: #2c2f34; --axis: #474b52;
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --series-4: #c98500;
    --series-5: #d55181; --series-6: #008300; --series-7: #9085e9; --series-8: #e66767;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 820px; margin: 0 auto; padding: 2rem 1rem 3rem; }
header, section, footer {
  margin-bottom: 1rem; padding: 1.25rem 1.4rem; border: 1px solid var(--border);
  border-radius: 0.6rem; background: var(--surface);
}
.kicker { margin: 0; color: var(--muted); font-size: 0.8rem; letter-spacing: 0.02em; }
h1 { margin: 0.3rem 0 0.4rem; font-size: 1.45rem; line-height: 1.3; }
h2 { margin: 1.2rem 0 0.35rem; color: var(--muted); font-size: 0.9rem; }
h3 { margin: 0 0 0.35rem; font-size: 0.92rem; }
h3 span { color: var(--muted); font-weight: 400; }
.meta, .note, .axis { margin: 0; color: var(--muted); font-size: 0.85rem; }
.context { margin-top: 0.8rem; color: var(--muted); font-size: 0.88rem; }
.context p { margin: 0; }
.context ol { margin: 0.2rem 0 0; }
.headline { margin: 0; font-size: 1.08rem; font-weight: 600; }
ul, ol { margin: 0; padding-left: 1.2rem; }
li + li { margin-top: 0.3rem; }
.cite {
  display: inline-block; margin-left: 0.3rem; padding: 0 0.4rem; border-radius: 0.3rem;
  background: var(--chip); color: var(--muted); font-size: 0.78rem; text-decoration: none;
}
a.cite:hover { color: var(--accent); text-decoration: underline; }
.cite.uncited { background: var(--warning-bg); color: var(--warning-text); }
.facts { display: flex; flex-wrap: wrap; gap: 0.3rem 1.5rem; margin: 1rem 0 0; font-size: 0.9rem; }
.facts div { display: flex; gap: 0.4rem; }
dt { color: var(--muted); }
dd { margin: 0; }
.definitions .label { font-weight: 600; }
.definitions code { margin-left: 0.3rem; color: var(--muted); }
.definitions p { margin: 0.1rem 0 0; color: var(--muted); font-size: 0.9rem; }
.badge {
  display: inline-block; margin-left: 0.3rem; padding: 0 0.45rem; border-radius: 0.3rem;
  font-size: 0.75rem; background: var(--warning-bg); color: var(--warning-text);
}
.badge.confirmed { background: var(--ok-bg); color: var(--ok-text); }
.warning {
  margin-top: 1rem; padding: 0.6rem 0.9rem; border-radius: 0.4rem;
  background: var(--warning-bg); color: var(--warning-text);
}
.warning h2 { margin-top: 0; color: inherit; }
.prose { white-space: pre-wrap; font: inherit; margin: 0; }
.chart { margin: 1.2rem 0 0; break-inside: avoid; }
.chart figcaption { margin-bottom: 0.35rem; }
.chart .title { font-weight: 600; font-size: 0.92rem; }
.plot { overflow-x: auto; }
.chart-svg { display: block; max-width: 100%; height: auto; font: 11px system-ui, -apple-system, "Segoe UI", sans-serif; }
.chart-svg .grid { stroke: var(--grid); }
.chart-svg .baseline { stroke: var(--axis); }
.chart-svg .tick { fill: var(--muted); font-variant-numeric: tabular-nums; }
.chart-svg .value { fill: var(--text); font-variant-numeric: tabular-nums; }
.chart-svg .bar { fill: var(--c); }
.chart-svg .line { fill: none; stroke: var(--c); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.chart-svg .dot { fill: var(--c); stroke: var(--surface); stroke-width: 2; }
.chart-svg .hit { fill: transparent; }
.legend { display: flex; flex-wrap: wrap; gap: 0.2rem 0.9rem; margin: 0 0 0.3rem; padding: 0; list-style: none; font-size: 0.8rem; color: var(--muted); }
.legend li { display: flex; align-items: center; gap: 0.35rem; margin: 0; }
.key { display: inline-block; width: 10px; height: 10px; border-radius: 2px; background: var(--c); }
.legend.line .key { width: 14px; height: 2px; }
.s1 { --c: var(--series-1); } .s2 { --c: var(--series-2); } .s3 { --c: var(--series-3); }
.s4 { --c: var(--series-4); } .s5 { --c: var(--series-5); } .s6 { --c: var(--series-6); }
.s7 { --c: var(--series-7); } .s8 { --c: var(--series-8); }
.query { margin-top: 1.1rem; }
.query:target { outline: 2px solid var(--accent); outline-offset: 6px; border-radius: 0.3rem; }
pre {
  margin: 0; padding: 0.6rem 0.8rem; overflow-x: auto; border-radius: 0.4rem;
  background: var(--code-bg); font: 12.5px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace;
  white-space: pre-wrap; word-break: break-word;
}
.analysis { margin-top: 0.45rem; font-size: 0.88rem; }
.table { margin-top: 0.5rem; overflow-x: auto; border: 1px solid var(--border); border-radius: 0.4rem; }
table { width: 100%; border-collapse: collapse; font-size: 0.84rem; }
th, td { padding: 0.3rem 0.6rem; border-bottom: 1px solid var(--border); text-align: left; white-space: nowrap; }
th { background: var(--chip); font-weight: 600; }
tbody tr:last-child td { border-bottom: 0; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.null { color: var(--muted); font-style: italic; }
.failed-title { margin-top: 1.4rem; }
.bad { margin-top: 0.6rem; }
.error, .cut { color: var(--warning-text); }
.error { margin: 0.3rem 0 0; font-size: 0.85rem; }
footer p { margin: 0; color: var(--muted); font-size: 0.82rem; }
footer p + p { margin-top: 0.4rem; }
@media print {
  :root { color-scheme: light; }
  body { background: #fff; }
  main { max-width: none; padding: 0; }
  header, section, footer { border: 0; padding: 0.5rem 0; }
  a.cite { color: inherit; }
  .query, .chart, tr { break-inside: avoid; }
  .plot, .table, pre { overflow: visible; }
}
"""
