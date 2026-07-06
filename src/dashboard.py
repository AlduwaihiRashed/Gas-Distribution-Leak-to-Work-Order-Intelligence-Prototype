"""
M10 — Non-technical monitoring dashboard (blueprint B.2[6], R6; actuator
indicator added R8).

Audience is explicitly non-technical (a supervisor/dispatcher, not an
engineer reading raw telemetry). Reads directly off the API's work-order
queue — never re-derives a grade, never recomputes anything the pipeline
already decided. If it's not in the queue payload, it doesn't belong on
this screen.

Run with: streamlit run src/dashboard.py
"""

import time
from datetime import datetime

import requests
import streamlit as st

API_BASE = "http://localhost:8000"
N8N_APPROVE_WEBHOOK = "http://localhost:5678/webhook/approve-dispatch"

GRADE_STYLE = {
    1: {"color": "#b3261e", "bg": "#fdecea", "label": "Urgent", "plain": "High gas level, needs immediate action"},
    2: {"color": "#b7791f", "bg": "#fef5e7", "label": "Scheduled", "plain": "Gas detected, repair scheduled"},
    3: {"color": "#1e7d47", "bg": "#eafaf1", "label": "Monitor", "plain": "Minor reading, being watched"},
}

STATUS_LABEL = {
    "IN_PROGRESS": "Preparing work order…",
    "AWAITING_APPROVAL": "Awaiting dispatch approval",
    "APPROVED_DISPATCHED": "Crew dispatched",
}

# CSS-only responsive grid: Streamlit's own column flex containers are
# overridden to wrap, so the number of tiles per row adapts to the actual
# browser width (narrow laptop vs. wide desktop) with no JS viewport bridge —
# keeps the stack Streamlit-only per house guidance.
APP_CSS = """
<style>
:root {
    --l2wo-navy: #101828;
    --l2wo-navy-soft: #1d2939;
    --l2wo-border: #e4e7ec;
    --l2wo-muted: #667085;
    --l2wo-red: #b3261e;
    --l2wo-amber: #b7791f;
    --l2wo-green: #1e7d47;
}

html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, Arial, sans-serif;
}

.block-container {
    max-width: 1800px;
    padding-top: 1.25rem;
    overflow-x: hidden;
}

/* Header bar */
.l2wo-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
    background: linear-gradient(135deg, var(--l2wo-navy) 0%, var(--l2wo-navy-soft) 100%);
    color: #ffffff;
    padding: 20px 28px;
    border-radius: 12px;
    margin-bottom: 1.25rem;
}
.l2wo-header-title {
    font-size: 1.5rem;
    font-weight: 700;
    text-wrap: balance;
    margin: 0;
}
.l2wo-header-subtitle {
    font-size: 0.9rem;
    color: #cbd5e1;
    margin-top: 4px;
}
.l2wo-header-meta {
    text-align: right;
    font-size: 0.85rem;
    color: #cbd5e1;
    font-variant-numeric: tabular-nums;
}
.l2wo-status-dot {
    position: relative;
    display: inline-block;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    margin-right: 6px;
    vertical-align: middle;
}
.l2wo-status-dot.ok { background: #22c55e; }
.l2wo-status-dot.down { background: #ef4444; }
.l2wo-status-dot.ok::after {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: #22c55e;
    animation: l2wo-pulse 2s infinite;
}

@keyframes l2wo-pulse {
    0% { transform: scale(1); opacity: 0.55; }
    70% { transform: scale(2.6); opacity: 0; }
    100% { transform: scale(2.6); opacity: 0; }
}
@media (prefers-reduced-motion: reduce) {
    .l2wo-status-dot.ok::after { animation: none; }
}

/* KPI cards */
.l2wo-kpi-row {
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
    margin-bottom: 1.25rem;
}
.l2wo-kpi-card {
    flex: 1 1 220px;
    background: #ffffff;
    border: 1px solid var(--l2wo-border);
    border-left: 4px solid var(--kpi-color, var(--l2wo-muted));
    border-radius: 10px;
    padding: 14px 18px;
    box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
}
.l2wo-kpi-label {
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--l2wo-muted);
}
.l2wo-kpi-value {
    font-size: 2.1rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: #101828;
    line-height: 1.2;
}

/* Segment tiles — real Streamlit columns, made responsive via flex-wrap */
div[data-testid="stHorizontalBlock"] {
    flex-wrap: wrap;
    gap: 1rem;
    row-gap: 1rem;
}
div[data-testid="column"] {
    min-width: 320px;
    flex: 1 1 320px;
}

.l2wo-tile-head {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
    min-width: 0;
}
.l2wo-tile-segment {
    font-size: 1.05rem;
    font-weight: 700;
    color: #101828;
    word-break: break-word;
    min-width: 0;
}
.l2wo-badge {
    flex-shrink: 0;
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    white-space: nowrap;
    color: #ffffff;
    background: var(--badge-color, var(--l2wo-muted));
}
.l2wo-tile-plain {
    font-size: 0.92rem;
    color: #344054;
    margin-top: 4px;
}
.l2wo-summary {
    font-size: 0.92rem;
    color: #344054;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-word;
}
</style>
"""


def format_timestamp(raw: str | None) -> str:
    """Plain-language timestamp for a non-technical viewer — never raw ISO-8601 with microseconds."""
    if not raw:
        return "—"
    try:
        return datetime.fromisoformat(raw).strftime("%b %d, %Y · %H:%M UTC")
    except ValueError:
        return raw


def fetch_work_orders() -> tuple[bool, list[dict]]:
    try:
        resp = requests.get(f"{API_BASE}/work-orders", timeout=5)
        resp.raise_for_status()
        return True, resp.json()
    except requests.RequestException as exc:
        st.error(f"Can't reach the pipeline API at {API_BASE} — is it running? ({exc})")
        return False, []


def approve_dispatch(incident_id: str) -> tuple[bool, str]:
    try:
        resp = requests.post(N8N_APPROVE_WEBHOOK, json={"incident_id": incident_id}, timeout=10)
        if resp.status_code == 200:
            return True, "Dispatch approved."
        return False, f"Approval failed ({resp.status_code}): {resp.text}"
    except requests.RequestException as exc:
        return False, f"Could not reach the approval webhook: {exc}"


def render_tile(entry: dict) -> None:
    grade = entry.get("grade")
    style = GRADE_STYLE.get(grade, {"color": "#667085", "bg": "#f4f4f4", "label": "Unknown", "plain": ""})
    status = entry.get("status", "IN_PROGRESS")
    wo = entry.get("work_order", {})
    degraded = wo.get("degraded_mode", False)

    with st.container(border=True):
        st.markdown(
            f"""
            <div style="background:{style['bg']}; border-left: 6px solid {style['color']};
                        padding: 12px 16px; border-radius: 8px; min-width: 0;">
                <div class="l2wo-tile-head">
                    <div class="l2wo-tile-segment" title="{entry.get('segment_id', '')}">{entry.get('segment_id', '')}</div>
                    <span class="l2wo-badge" style="--badge-color: {style['color']};">{style['label']}</span>
                </div>
                <div class="l2wo-tile-plain">{style['plain']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if degraded:
            st.warning("⚠️ Degraded mode — AI summary unavailable, template-only work order. Grade and safety data are still accurate.")

        summary = wo.get("situation_summary") or "Work order still being prepared…"
        st.markdown(f'<div class="l2wo-summary">{summary}</div>', unsafe_allow_html=True)

        st.caption(STATUS_LABEL.get(status, status))

        if grade == 1:
            actuator_state = entry.get("actuator_confirmed_state")
            if entry.get("actuator_commanded"):
                if actuator_state == "isolated":
                    latency = entry.get("actuator_command_latency_s")
                    latency_txt = f" in {latency:.1f}s" if latency is not None else ""
                    st.success(f"🔒 Segment isolated automatically — confirmed{latency_txt}")
                else:
                    st.warning("⚠️ Isolation commanded — confirmation still pending")
            # else: no actuator on this segment (e.g. batch/demo incident with no hardware) — nothing to show

        if status == "AWAITING_APPROVAL":
            if st.button(
                "✅ Approve Dispatch",
                key=f"approve_{entry['incident_id']}",
                help=f"Approve crew/vehicle dispatch for {entry.get('segment_id', 'this segment')}",
                use_container_width=True,
            ):
                ok, msg = approve_dispatch(entry["incident_id"])
                if ok:
                    st.success(msg)
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(msg)
        elif status == "APPROVED_DISPATCHED":
            st.caption(f"Approved at {format_timestamp(entry.get('approved_at'))}")


def render_header(connected: bool) -> None:
    dot_class = "ok" if connected else "down"
    status_text = "Live" if connected else "Disconnected"
    now = time.strftime("%H:%M:%S")
    st.markdown(
        f"""
        <div class="l2wo-header">
            <div>
                <h1 class="l2wo-header-title">Gas Distribution — Live Monitoring</h1>
                <div class="l2wo-header-subtitle">🔴 Urgent · 🟠 Scheduled repair · 🟢 Monitoring only</div>
            </div>
            <div class="l2wo-header-meta">
                <span class="l2wo-status-dot {dot_class}"></span>{status_text}<br/>
                Updated {now}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpis(counts: dict) -> None:
    cards = [
        ("Urgent · Grade 1", counts[1], GRADE_STYLE[1]["color"]),
        ("Scheduled · Grade 2", counts[2], GRADE_STYLE[2]["color"]),
        ("Monitoring · Grade 3", counts[3], GRADE_STYLE[3]["color"]),
    ]
    # Single-line fragments, joined with no whitespace between them — a blank
    # line here would terminate Streamlit's markdown HTML-block parsing early
    # and the remaining cards would render as escaped text instead of HTML.
    cards_html = "".join(
        f'<div class="l2wo-kpi-card" style="--kpi-color: {color};">'
        f'<div class="l2wo-kpi-label">{label}</div>'
        f'<div class="l2wo-kpi-value">{value}</div>'
        f'</div>'
        for label, value, color in cards
    )
    st.markdown(f'<div class="l2wo-kpi-row">{cards_html}</div>', unsafe_allow_html=True)


def main():
    st.set_page_config(page_title="L2WO Monitoring Dashboard", page_icon="🛢️", layout="wide")
    st.markdown(APP_CSS, unsafe_allow_html=True)

    with st.sidebar:
        st.header("Controls")
        auto_refresh = st.checkbox("Auto-refresh every 5s", value=True)
        if st.button("🔄 Refresh Now", use_container_width=True):
            st.rerun()
        st.divider()
        st.caption(f"API: {API_BASE}")
        st.caption(f"Approval webhook: {N8N_APPROVE_WEBHOOK}")

    connected, entries = fetch_work_orders()
    render_header(connected)

    if not entries:
        st.info("No active incidents. All segments nominal.")
    else:
        counts = {1: 0, 2: 0, 3: 0}
        for e in entries:
            if e.get("grade") in counts:
                counts[e["grade"]] += 1
        render_kpis(counts)

        # Most severe first — a dispatcher's attention should land on Grade 1 tiles first
        entries_sorted = sorted(entries, key=lambda e: (e.get("grade") or 99, e["incident_id"]))
        num_cols = min(4, max(1, len(entries_sorted)))
        cols = st.columns(num_cols)
        for i, entry in enumerate(entries_sorted):
            with cols[i % num_cols]:
                render_tile(entry)

    if auto_refresh:
        time.sleep(5)
        st.rerun()


if __name__ == "__main__":
    main()
