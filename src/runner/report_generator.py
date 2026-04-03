import html
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, Tuple


PDF_MAX_ROWS_PER_SERVICE = 50
REPORT_STYLES = """
  :root {
    --bg: #0b0f17;
    --panel: rgba(255,255,255,0.06);
    --panel2: rgba(255,255,255,0.04);
    --text: rgba(255,255,255,0.92);
    --muted: rgba(255,255,255,0.65);
    --border: rgba(255,255,255,0.10);
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, Arial, sans-serif;
    background: radial-gradient(1200px 800px at 20% 0%, rgba(80,120,255,0.22), transparent 55%),
                radial-gradient(900px 600px at 80% 20%, rgba(0,200,170,0.18), transparent 55%),
                var(--bg);
    color: var(--text);
  }

  .wrap { max-width: 1180px; margin: 0 auto; padding: 28px 18px 60px; }

  .top {
    display: grid;
    gap: 12px;
    padding: 18px;
    border: 1px solid var(--border);
    background: var(--panel);
    border-radius: 16px;
  }

  .title {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
    flex-wrap: wrap;
  }

  h1 { font-size: 22px; margin: 0; }
  .sub { color: var(--muted); font-size: 13px; }

  .kpis {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px;
  }

  .kpi {
    background: var(--panel2);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 12px 14px;
  }

  .kpi .label { color: var(--muted); font-size: 12px; }
  .kpi .val { font-size: 22px; margin-top: 6px; }
  .kpi-note { font-size: 14px; }

  .cards {
    margin-top: 14px;
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 12px;
  }

  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 14px;
  }

  .card-title { color: var(--muted); font-size: 12px; }
  .big { font-size: 20px; margin: 8px 0 6px; }
  .meta { color: var(--muted); font-size: 12px; }

  .section {
    margin-top: 18px;
    border: 1px solid var(--border);
    background: var(--panel);
    border-radius: 16px;
    padding: 14px;
    break-inside: avoid;
    page-break-inside: avoid;
  }

  .section--compact { margin-top: 10px; }

  .section-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 10px;
  }

  h2 { margin: 0; font-size: 16px; }

  table {
    width: 100%;
    border-collapse: collapse;
    table-layout: auto;
  }

  th, td {
    border-bottom: 1px solid var(--border);
    padding: 10px 10px;
    text-align: left;
    vertical-align: top;
    font-size: 13px;
    overflow-wrap: anywhere;
  }

  th {
    color: rgba(255,255,255,0.70);
    font-weight: 650;
    background: rgba(255,255,255,0.04);
    white-space: nowrap;
  }

  .muted { color: var(--muted); }

  .empty-state {
    display: grid;
    gap: 6px;
    padding: 2px 0 0;
  }

  .empty-title {
    font-size: 15px;
    font-weight: 650;
  }

  .empty-reason {
    color: var(--muted);
    font-size: 13px;
    line-height: 1.5;
  }

  .empty-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 10px 18px;
    color: var(--muted);
    font-size: 13px;
    line-height: 1.5;
  }

  .detail-label {
    color: var(--text);
    font-weight: 600;
  }

  .risk {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 999px;
    border: 1px solid var(--border);
    font-size: 12px;
    color: var(--text);
    background: rgba(255,255,255,0.04);
    white-space: nowrap;
  }

  .risk-low { background: rgba(0,200,170,0.15); }
  .risk-medium { background: rgba(255,180,0,0.16); }
  .risk-high { background: rgba(255,70,70,0.18); }
  .risk-unknown { background: rgba(160,160,160,0.10); }

  @media (max-width: 920px) {
    .kpis,
    .cards {
      grid-template-columns: 1fr;
    }
  }
"""


def esc(s) -> str:
    return html.escape("" if s is None else str(s))


def get(d, key, default=""):
    return d.get(key, default) if isinstance(d, dict) else default


def money(x) -> str:
    try:
        return f"{float(x):.2f}"
    except Exception:
        return "0.00"


def money_or_dash(x) -> str:
    try:
        if x is None:
            return "—"
        return f"£{float(x):.2f}"
    except Exception:
        return "—"


def fmt_num(x) -> str:
    try:
        f = float(x)
        if f.is_integer():
            return str(int(f))
        return f"{f:.2f}".rstrip("0").rstrip(".")
    except Exception:
        return "" if x is None else str(x)


def trunc(s: str, n: int = 140) -> str:
    s = "" if s is None else str(s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def pct_display(x) -> str:
    try:
        return f"{float(x):.2f}%"
    except Exception:
        return "0.00%"


def format_timestamp(ts: str) -> str:
    if not ts:
        return ""

    s = str(ts).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return s

    tz = dt.tzinfo
    if tz is not None and dt.utcoffset() == timezone.utc.utcoffset(dt):
        tz_label = "UTC"
    elif tz is not None:
        tz_label = dt.strftime("%z")
    else:
        tz_label = ""

    out = dt.strftime("%d %b %Y • %H:%M:%S")
    return f"{out} ({tz_label})" if tz_label else out


def sanitize_filename(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return "run"
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s)
    return s[:80] or "run"


def risk_badge(level):
    lvl = (level or "unknown").lower()
    cls = "risk-unknown"
    if "low" in lvl:
        cls = "risk-low"
    elif "medium" in lvl:
        cls = "risk-medium"
    elif "high" in lvl:
        cls = "risk-high"
    return f'<span class="risk {cls}">{esc(level or "unknown")}</span>'


def table(headers, rows):
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    trs = []
    for row in rows:
        tds = "".join(f"<td>{cell}</td>" for cell in row)
        trs.append(f"<tr>{tds}</tr>")
    return f"""
    <table>
      <thead><tr>{th}</tr></thead>
      <tbody>
        {''.join(trs) if trs else '<tr><td colspan="99" class="muted">No recommendations</td></tr>'}
      </tbody>
    </table>
    """


def build_empty_state(details: Dict[str, Any]) -> str:
    details = details if isinstance(details, dict) else {}
    reason = get(details, "reason", "")
    detail_items = []
    for key, value in details.items():
        if key == "reason" or value in (None, "", [], {}):
            continue
        label = esc(str(key).replace("_", " ").capitalize())
        rendered = esc(", ".join(str(item) for item in value)) if isinstance(value, list) else esc(value)
        detail_items.append(f"<span><span class='detail-label'>{label}:</span> {rendered}</span>")

    detail_html = f"<div class='empty-meta'>{''.join(detail_items)}</div>" if detail_items else ""
    reason_html = (
        "<div class='empty-reason'><span class='detail-label'>Reason:</span> "
        + esc(reason)
        + "</div>"
        if reason
        else ""
    )

    return f"""
    <div class="empty-state">
      <div class="empty-title">No recommendations</div>
      {reason_html}
      {detail_html}
    </div>
    """


def build_service_card(name, service_payload):
    recs = get(service_payload, "recommendations", []) or []
    return f"""
    <div class="card">
      <div class="card-title">{esc(name.upper())}</div>
      <div class="big">£{money(get(service_payload, "total_monthly_savings", 0))}/mo</div>
      <div class="meta">
        Baseline: £{money(get(service_payload, "baseline_monthly_cost", 0))}
        &nbsp;→&nbsp;
        Optimised: £{money(get(service_payload, "optimised_monthly_cost", 0))}
      </div>
      <div class="meta">Recommendations: {len(recs)}</div>
    </div>
    """


def build_top_actions(payload: Dict[str, Any], limit: int = 5) -> str:
    top = ((payload.get("summary") or {}).get("top_actions")) or []
    if not isinstance(top, list) or not top:
        return "<div class='muted'>No top actions available.</div>"

    rows = []
    for action in top[:limit]:
        rows.append([
            esc(get(action, "service")),
            esc(get(action, "resource_id")),
            esc(get(action, "action")),
            risk_badge(get(action, "risk_level")),
            money_or_dash(get(action, "estimated_monthly_savings")),
        ])

    return table(["Service", "Resource", "Action", "Risk", "Save £/mo"], rows)


def render_generic(service_payload):
    recs = get(service_payload, "recommendations", []) or []
    if not recs:
        return build_empty_state(get(service_payload, "details", {}) or {})

    rows = []

    for rec in recs[:PDF_MAX_ROWS_PER_SERVICE]:
        rows.append([
            esc(get(rec, "resource_id") or get(rec, "db_instance") or get(rec, "bucket") or "unknown"),
            esc(get(rec, "action") or get(rec, "recommended_action") or get(rec, "recommended_storage_class") or ""),
            money_or_dash(get(rec, "baseline_monthly_cost")),
            money_or_dash(get(rec, "optimised_monthly_cost")),
            money_or_dash(get(rec, "estimated_monthly_savings")),
            risk_badge(get(rec, "risk_level")),
            esc(trunc(get(rec, "rationale"), 140)),
        ])

    return table(
        ["Resource", "Action", "Now £/mo", "Could £/mo", "Save £/mo", "Risk", "Rationale"],
        rows,
    )


def build_html(payload: Dict[str, Any]) -> str:
    payload = payload if isinstance(payload, dict) else {}
    totals = payload.get("totals", {}) if isinstance(payload.get("totals"), dict) else {}
    services = payload.get("services", {}) if isinstance(payload.get("services"), dict) else {}
    ts = format_timestamp(payload.get("timestamp") or "")
    run_id = payload.get("run_id") or ""
    customer = payload.get("customer") or "unknown"

    cards_html = "".join(build_service_card(name, svc) for name, svc in services.items())
    top_actions_html = build_top_actions(payload, limit=5)
    savings_percent = pct_display((payload.get("summary") or {}).get("savings_percent", 0))

    sections = []
    for service_name, service_payload in services.items():
        sections.append(
            f"""
            <section class="section">
              <div class="section-head">
                <h2>{esc(service_name.upper())}</h2>
              </div>
              {render_generic(service_payload)}
            </section>
            """
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>FinOps Automation Report - {esc(customer)}</title>
<style>
  {REPORT_STYLES}
</style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div class="title">
        <h1>FinOps Automation Report</h1>
        <div class="sub">
          Customer: <b>{esc(customer)}</b>
          &nbsp;•&nbsp; Run ID: {esc(run_id)}
          &nbsp;•&nbsp; Timestamp: {esc(ts)}
        </div>
      </div>

      <div class="kpis">
        <div class="kpi">
          <div class="label">Baseline monthly cost</div>
          <div class="val">£{money(totals.get("baseline_monthly_cost", 0))}</div>
        </div>
        <div class="kpi">
          <div class="label">Optimised monthly cost</div>
          <div class="val">£{money(totals.get("optimised_monthly_cost", 0))}</div>
        </div>
        <div class="kpi">
          <div class="label">Estimated monthly savings</div>
          <div class="val">£{money(totals.get("total_monthly_savings", 0))} <span class="muted kpi-note">({savings_percent})</span></div>
        </div>
      </div>

      <section class="section section--compact">
        <div class="section-head">
          <h2>Top actions</h2>
        </div>
        {top_actions_html}
      </section>

      <div class="cards">
        {cards_html}
      </div>
    </div>

    {''.join(sections)}
  </div>
</body>
</html>
"""


def generate_report_files(payload: Dict[str, Any], output_dir: Path, filename_prefix: str) -> Tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = payload if isinstance(payload, dict) else {}

    safe_prefix = sanitize_filename(filename_prefix)
    html_path = output_dir / f"{safe_prefix}.html"
    json_path = output_dir / f"{safe_prefix}.json"

    html_content = build_html(payload)
    html_path.write_text(html_content, encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return html_path, json_path
