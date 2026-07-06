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
    1: {"color": "#BF616A", "bg": "rgba(191, 97, 106, 0.14)", "label": "Urgent", "plain": "High gas level, needs immediate action"},
    2: {"color": "#EBCB8B", "bg": "rgba(235, 203, 139, 0.12)", "label": "Scheduled", "plain": "Gas detected, repair scheduled"},
    3: {"color": "#A3BE8C", "bg": "rgba(163, 190, 140, 0.12)", "label": "Monitor", "plain": "Minor reading, being watched"},
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
#
# Visual language: Nord palette (KDE "Nordic" theme family) laid out as a
# dark control-room console — deep polar-night panels, frost-blue chrome,
# aurora accent colors reserved for grade/status signals, monospace readouts
# on anything numeric/timestamped so it reads like instrumentation rather
# than a web form.
APP_CSS = """
<style>
:root {
    /* Nord — Polar Night */
    --nord0: #2E3440;
    --nord1: #3B4252;
    --nord2: #434C5E;
    --nord3: #4C566A;
    /* Nord — Snow Storm */
    --nord4: #D8DEE9;
    --nord5: #E5E9F0;
    --nord6: #ECEFF4;
    /* Nord — Frost */
    --nord7: #8FBCBB;
    --nord8: #88C0D0;
    --nord9: #81A1C1;
    --nord10: #5E81AC;
    /* Nord — Aurora */
    --nord11: #BF616A;
    --nord12: #D08770;
    --nord13: #EBCB8B;
    --nord14: #A3BE8C;
    --nord15: #B48EAD;

    --l2wo-muted: var(--nord4);
    --l2wo-red: var(--nord11);
    --l2wo-amber: var(--nord13);
    --l2wo-green: var(--nord14);
    --hud-mono: ui-monospace, "SFMono-Regular", "JetBrains Mono", "Cascadia Mono", Consolas, "Liberation Mono", monospace;
}

html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, Arial, sans-serif;
}

/* Console shell: deep polar-night gradient + a faint schematic grid, like a
   wall panel rather than flat web-page white/gray. */
.stApp {
    background:
        radial-gradient(1200px 700px at 15% -10%, rgba(94, 129, 172, 0.16), transparent 60%),
        radial-gradient(900px 600px at 100% 0%, rgba(136, 192, 208, 0.08), transparent 55%),
        repeating-linear-gradient(0deg, rgba(216, 222, 233, 0.035) 0px, rgba(216, 222, 233, 0.035) 1px, transparent 1px, transparent 32px),
        repeating-linear-gradient(90deg, rgba(216, 222, 233, 0.035) 0px, rgba(216, 222, 233, 0.035) 1px, transparent 1px, transparent 32px),
        var(--nord0);
}

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, var(--nord0) 0%, #262b35 100%);
    border-right: 1px solid var(--nord2);
}
[data-testid="stSidebar"] * { color: var(--nord5) !important; }
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] .stMarkdown h2 {
    color: var(--nord8) !important;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    font-size: 0.95rem;
}
[data-testid="stSidebar"] hr { border-color: var(--nord2); }

.block-container {
    max-width: 1800px;
    padding-top: 1.25rem;
    overflow-x: hidden;
}

/* Header bar — instrument-panel strip with a lit frost-cyan top edge */
.l2wo-header {
    position: relative;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
    background: linear-gradient(135deg, var(--nord1) 0%, var(--nord0) 100%);
    color: var(--nord6);
    padding: 20px 28px;
    border-radius: 10px;
    border: 1px solid var(--nord2);
    box-shadow: 0 0 0 1px rgba(136, 192, 208, 0.06), 0 12px 32px -16px rgba(0, 0, 0, 0.6);
    margin-bottom: 1.25rem;
    overflow: hidden;
}
.l2wo-header::before {
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--nord10), var(--nord8), var(--nord10));
}
.l2wo-header-eyebrow {
    font-family: var(--hud-mono);
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--nord9);
    margin-bottom: 4px;
}
.l2wo-header-title {
    font-size: 1.5rem;
    font-weight: 700;
    text-wrap: balance;
    margin: 0;
    color: var(--nord6);
}
.l2wo-header-subtitle {
    font-size: 0.9rem;
    color: var(--nord4);
    margin-top: 4px;
}
.l2wo-header-meta {
    text-align: right;
    font-size: 0.85rem;
    font-family: var(--hud-mono);
    color: var(--nord4);
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
.l2wo-status-dot.ok { background: var(--nord14); box-shadow: 0 0 8px 1px rgba(163, 190, 140, 0.7); }
.l2wo-status-dot.down { background: var(--nord11); box-shadow: 0 0 8px 1px rgba(191, 97, 106, 0.7); }
.l2wo-status-dot.ok::after {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: var(--nord14);
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

/* KPI cards — dark gauges with a glowing accent edge per grade */
.l2wo-kpi-row {
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
    margin-bottom: 1.25rem;
}
.l2wo-kpi-card {
    flex: 1 1 220px;
    background: linear-gradient(180deg, var(--nord1) 0%, var(--nord0) 100%);
    border: 1px solid var(--nord2);
    border-left: 4px solid var(--kpi-color, var(--nord3));
    border-radius: 8px;
    padding: 14px 18px;
    box-shadow: 0 0 24px -12px var(--kpi-color, transparent), inset 0 1px 0 rgba(255, 255, 255, 0.03);
}
.l2wo-kpi-label {
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--nord4);
}
.l2wo-kpi-value {
    font-family: var(--hud-mono);
    font-size: 2.1rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: var(--nord6);
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

/* Bordered st.container() panels — recent + older Streamlit testids both
   targeted so the console-panel look survives a Streamlit version bump. */
div[data-testid="stVerticalBlockBorderWrapper"],
div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"] {
    background: linear-gradient(180deg, var(--nord1) 0%, var(--nord0) 100%);
    border-radius: 10px !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] > div {
    border-color: var(--nord2) !important;
    border-radius: 10px !important;
}

.l2wo-tile-head {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
    min-width: 0;
}
.l2wo-tile-segment {
    font-family: var(--hud-mono);
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--nord6);
    word-break: break-word;
    min-width: 0;
}
.l2wo-badge {
    flex-shrink: 0;
    display: inline-block;
    padding: 2px 10px;
    border-radius: 3px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    white-space: nowrap;
    color: var(--nord0);
    background: var(--badge-color, var(--nord3));
    box-shadow: 0 0 10px -1px var(--badge-color, transparent);
}
.l2wo-tile-plain {
    font-size: 0.92rem;
    color: var(--nord5);
    margin-top: 4px;
}
.l2wo-summary {
    font-size: 0.92rem;
    color: var(--nord4);
    display: -webkit-box;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-word;
}

/* Buttons — frost-blue console switches with a hover glow */
.stButton > button {
    border-radius: 6px !important;
    border: 1px solid var(--nord9) !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em;
    transition: box-shadow 0.15s ease, transform 0.05s ease;
}
.stButton > button:hover {
    box-shadow: 0 0 16px -2px rgba(136, 192, 208, 0.6);
    border-color: var(--nord8) !important;
}
.stButton > button:active { transform: translateY(1px); }

/* Alert boxes (success/warning/error/info) — keep them console-dark, with a
   thin left rail in the alert's own semantic color for at-a-glance triage. */
div[data-testid="stAlertContainer"] {
    border-radius: 8px;
    background: var(--nord1) !important;
    border: 1px solid var(--nord2);
}
div[data-testid="stAlertContainer"]:has(div[data-testid="stAlertContentError"]) { border-left: 3px solid var(--nord11); }
div[data-testid="stAlertContainer"]:has(div[data-testid="stAlertContentWarning"]) { border-left: 3px solid var(--nord13); }
div[data-testid="stAlertContainer"]:has(div[data-testid="stAlertContentSuccess"]) { border-left: 3px solid var(--nord14); }
div[data-testid="stAlertContainer"]:has(div[data-testid="stAlertContentInfo"]) { border-left: 3px solid var(--nord9); }

/* Timestamps / captions read like HUD telemetry, not body copy */
.stCaption, [data-testid="stCaptionContainer"] {
    font-family: var(--hud-mono) !important;
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
                <div class="l2wo-header-eyebrow">L2WO · Segment Monitoring Console</div>
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
