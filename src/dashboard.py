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

import requests
import streamlit as st

API_BASE = "http://localhost:8000"
N8N_APPROVE_WEBHOOK = "http://localhost:5678/webhook/approve-dispatch"

GRADE_STYLE = {
    1: {"color": "#c0392b", "bg": "#fdecea", "label": "URGENT", "plain": "High gas level, needs immediate action"},
    2: {"color": "#d68910", "bg": "#fef5e7", "label": "SCHEDULED", "plain": "Gas detected, repair scheduled"},
    3: {"color": "#1e8449", "bg": "#eafaf1", "label": "MONITOR", "plain": "Minor reading, being watched"},
}

STATUS_LABEL = {
    "IN_PROGRESS": "⏳ Preparing work order…",
    "AWAITING_APPROVAL": "🟡 Awaiting dispatch approval",
    "APPROVED_DISPATCHED": "✅ Crew dispatched",
}


def fetch_work_orders() -> list[dict]:
    try:
        resp = requests.get(f"{API_BASE}/work-orders", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        st.error(f"Can't reach the pipeline API at {API_BASE} — is it running? ({exc})")
        return []


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
    style = GRADE_STYLE.get(grade, {"color": "#7f8c8d", "bg": "#f4f4f4", "label": "UNKNOWN", "plain": ""})
    status = entry.get("status", "IN_PROGRESS")
    wo = entry.get("work_order", {})
    degraded = wo.get("degraded_mode", False)

    with st.container(border=True):
        st.markdown(
            f"""
            <div style="background:{style['bg']}; border-left: 8px solid {style['color']};
                        padding: 12px 16px; border-radius: 6px;">
                <div style="font-size: 1.3em; font-weight: 700; color: {style['color']};">
                    {entry['segment_id']} — {style['label']}
                </div>
                <div style="font-size: 1.0em; margin-top: 4px; color: #1a1a1a;">{style['plain']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if degraded:
            st.warning("⚠️ DEGRADED MODE — AI summary unavailable, template-only work order. Grade and safety data are still accurate.")

        summary = wo.get("situation_summary") or "Work order still being prepared."
        st.write(summary)

        st.caption(STATUS_LABEL.get(status, status))

        if grade == 1:
            actuator_state = entry.get("actuator_confirmed_state")
            if entry.get("actuator_commanded"):
                if actuator_state == "isolated":
                    latency = entry.get("actuator_command_latency_s")
                    latency_txt = f" in {latency}s" if latency is not None else ""
                    st.success(f"🔒 Segment isolated automatically — confirmed{latency_txt}")
                else:
                    st.warning("⚠️ Isolation commanded — confirmation still pending")
            # else: no actuator on this segment (e.g. batch/demo incident with no hardware) — nothing to show

        if status == "AWAITING_APPROVAL":
            if st.button("✅ Approve Dispatch", key=f"approve_{entry['incident_id']}"):
                ok, msg = approve_dispatch(entry["incident_id"])
                if ok:
                    st.success(msg)
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(msg)
        elif status == "APPROVED_DISPATCHED":
            st.caption(f"Approved at {entry.get('approved_at', '—')}")


def main():
    st.set_page_config(page_title="L2WO Monitoring Dashboard", layout="wide")
    st.title("Gas Distribution — Live Monitoring")
    st.caption("🔴 Red = urgent · 🟠 Amber = scheduled repair · 🟢 Green = monitoring only")

    with st.sidebar:
        st.header("Controls")
        auto_refresh = st.checkbox("Auto-refresh every 5s", value=True)
        if st.button("🔄 Refresh now"):
            st.rerun()
        st.divider()
        st.caption(f"API: {API_BASE}")
        st.caption(f"Approval webhook: {N8N_APPROVE_WEBHOOK}")

    entries = fetch_work_orders()

    if not entries:
        st.info("No active incidents. All segments nominal.")
    else:
        counts = {1: 0, 2: 0, 3: 0}
        for e in entries:
            if e.get("grade") in counts:
                counts[e["grade"]] += 1
        c1, c2, c3 = st.columns(3)
        c1.metric("🔴 Urgent (Grade 1)", counts[1])
        c2.metric("🟠 Scheduled (Grade 2)", counts[2])
        c3.metric("🟢 Monitoring (Grade 3)", counts[3])

        st.divider()

        # Most severe first — a dispatcher's attention should land on Grade 1 tiles first
        entries_sorted = sorted(entries, key=lambda e: (e.get("grade") or 99, e["incident_id"]))
        cols = st.columns(2)
        for i, entry in enumerate(entries_sorted):
            with cols[i % 2]:
                render_tile(entry)

    if auto_refresh:
        time.sleep(5)
        st.rerun()


if __name__ == "__main__":
    main()
