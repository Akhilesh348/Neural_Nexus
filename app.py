"""Enron Insight — review-triage dashboard.

Reads only the precomputed SQLite database (python -m src.pipeline ...).
Email content is displayed as escaped text; it is never executed or interpreted.
"""
import html
import json
import os
import sqlite3

import networkx as nx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DB_PATH = os.environ.get("ENRON_DB", "outputs/enron.db")
RULES_PATH = "config/rules.json"
METRICS_PATH = "outputs/metrics.json"

st.set_page_config(page_title="Enron Insight", layout="wide")


# ---------- data access (cached) ----------

@st.cache_resource
def get_con():
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)


@st.cache_data
def q(sql, params=()):
    return pd.read_sql_query(sql, get_con(), params=params)


@st.cache_data
def load_rules():
    with open(RULES_PATH, encoding="utf-8") as f:
        return json.load(f)


def meta():
    return dict(q("SELECT key, value FROM meta").values.tolist())


def fmt_int(v):
    try:
        return f"{int(float(v)):,}"
    except (TypeError, ValueError):
        return "—"


# ---------- evidence view (shared by all tabs) ----------

def highlight(text, needle):
    """Escape email text, then mark the matched phrase."""
    safe = html.escape(text or "")
    if needle:
        n = html.escape(needle)
        i = safe.lower().find(n.lower())
        if i >= 0:
            safe = safe[:i] + "<mark>" + safe[i:i + len(n)] + "</mark>" + safe[i + len(n):]
    return safe


def render_evidence(email_id):
    e = q("SELECT * FROM emails WHERE email_id = ?", (email_id,))
    if e.empty:
        st.warning("Email not found.")
        return
    e = e.iloc[0]
    risk = q("SELECT * FROM risk_results WHERE email_id = ?", (email_id,))
    recips = q("SELECT recipient, recipient_type FROM recipients WHERE email_id = ? "
               "ORDER BY recipient_type, recipient", (email_id,))
    sources = q("SELECT source_file FROM source_occurrences WHERE email_id = ? ORDER BY source_file", (email_id,))

    st.markdown(f"#### {html.escape(e.subject or '(no subject)')}")
    st.caption(f"email_id `{email_id}` · {e.sent_at_utc or 'no valid date'} UTC · header date: {e.original_date}")
    st.markdown(f"**From:** `{e.sender or ''}` ({html.escape(e.sender_name or '')}) · "
                f"**{len(recips)} recipient(s):** "
                + (", ".join(f"`{r}` ({t})" for r, t in recips.values[:6]) or "none")
                + (" …" if len(recips) > 6 else ""))
    if len(recips) > 6:
        with st.expander(f"All {len(recips)} recipients"):
            st.dataframe(recips, hide_index=True, use_container_width=True)

    if not risk.empty:
        r = risk.iloc[0]
        st.markdown(f"**Flagged for review** — score **{r.score:.0f}/100** ({r.priority} priority) · rules v{r.rule_version}")
        m1, m2, m3, _ = st.columns([1, 1, 1, 2])
        m1.metric("K language", f"{r.k_points:.0f} / 60")
        m2.metric("C communication", f"{r.c_points:.0f} / 30")
        m3.metric("T timing", f"{r.t_points:.0f} / 10")
        st.markdown("**Why it was flagged**")
        for reason in json.loads(r.reasons_json):
            line = f"- **{reason['rule_id']}** (+{reason['points']:.0f}) — {html.escape(reason['explanation'])}"
            if reason.get("supporting_value") and not reason.get("evidence_excerpt"):
                line += f" · `{html.escape(reason['supporting_value'])}`"
            st.markdown(line, unsafe_allow_html=True)
            if reason.get("evidence_excerpt"):
                st.markdown(f"<blockquote>{highlight(reason['evidence_excerpt'], reason['supporting_value'])}</blockquote>",
                            unsafe_allow_html=True)
        ne = json.loads(r.not_evaluated_json or "[]")
        if ne:
            st.markdown("**Not evaluated** (missing or unreliable data — not counted as zero risk)")
            for reason in ne:
                st.markdown(f"- {reason['rule_id']}: {html.escape(reason['explanation'])}")
    else:
        st.info("Not flagged: no strong language rule fired on this email.")

    with st.expander(f"Original message · found in {len(sources)} mailbox file(s)", expanded=False):
        st.markdown("**Source files:** " + ", ".join(f"`{s}`" for s in sources.source_file))
        st.text(e.raw_email)


# ---------- page ----------

st.title("Enron Insight — email review triage")
st.caption("Results are **flagged for review** using stated rules. A flag is an investigation lead, "
           "not an accusation and not a probability of wrongdoing.")

if not os.path.exists(DB_PATH):
    st.error(f"No processed database found at `{DB_PATH}`. Run:\n\n"
             "`python -m src.pipeline --input enron_mail_20150507.tar.gz`")
    st.stop()

M = meta()
if M.get("limit", "none") != "none":
    st.warning(f"Subset run: only the first {M['limit']} source files were processed.")

tab_over, tab_flag, tab_net, tab_method = st.tabs(
    ["📊 Overview", "🚩 Flagged emails", "🕸️ Network & people", "📐 Method & precision"])

# ----- Overview (R1) -----
with tab_over:
    k = st.columns(5)
    k[0].metric("Source files", fmt_int(M.get("source_files")))
    k[1].metric("Unique emails", fmt_int(M.get("unique_emails")))
    k[2].metric("Duplicate copies removed", fmt_int(M.get("duplicate_copies")))
    k[3].metric("Dated 1998–2002", fmt_int(M.get("valid_dated_emails")))
    k[4].metric("Flagged for review", fmt_int(M.get("flagged_emails")))

    st.subheader("How does email volume change over time?")
    vol = q("""SELECT substr(e.sent_at_utc, 1, 7) AS month, COUNT(*) AS emails,
                      COUNT(r.email_id) AS flagged
               FROM emails e LEFT JOIN risk_results r USING(email_id)
               WHERE e.date_valid = 1 GROUP BY month ORDER BY month""")
    vol["month"] = pd.to_datetime(vol["month"])
    fig = px.area(vol, x="month", y="emails", labels={"month": "Month", "emails": "Unique emails sent"})
    for d, label, anchor in [("2001-10-16", "Q3 loss disclosed ", "right"), ("2001-12-02", " Bankruptcy filing", "left")]:
        fig.add_vline(x=pd.Timestamp(d).value / 1e6, line_dash="dot", line_color="gray")
        fig.add_annotation(x=d, y=vol.emails.max(), text=label, showarrow=False, yanchor="bottom",
                           xanchor=anchor, font_size=11)
    fig.update_layout(height=360, margin=dict(t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Each unique email counted once (duplicates across folders removed). Dates from the email header. "
               "Dotted lines: publicly known events, for orientation only.")

    st.subheader("Who sends the most email?")
    top = q("""SELECT sender, sender_name, n_sent, n_flagged FROM people
               ORDER BY n_sent DESC LIMIT 15""")
    top["label"] = top.sender_name.where(top.sender_name.str.len() > 0, top.sender)
    fig2 = px.bar(top[::-1], x="n_sent", y="label", orientation="h",
                  labels={"n_sent": "Unique emails sent", "label": ""}, hover_data=["sender", "n_flagged"])
    fig2.update_layout(height=420, margin=dict(t=10, b=10))
    st.plotly_chart(fig2, use_container_width=True)

# ----- Flagged emails (R2) -----
with tab_flag:
    st.subheader("Which emails should a reviewer read first, and why?")
    rules_cfg = load_rules()
    rule_ids = [r["id"] for r in rules_cfg["language"]["strong_rules"]] + \
               [rules_cfg["language"]["topic_rule"]["id"], "C-EXTERNAL", "C-RARE-PAIR", "T-WEEKEND"]
    f1, f2, f3, f4 = st.columns([1, 1.3, 1.3, 1.4])
    min_score = f1.slider("Minimum score", 0, 100, 30, 5)
    pick_rules = f2.multiselect("Must include rule", rule_ids)
    sender_q = f3.text_input("Sender contains")
    text_q = f4.text_input("Subject / text contains")

    flagged = q("""SELECT r.email_id, r.score, r.priority, r.rules, e.sent_at_utc, e.sender, e.subject
                   FROM risk_results r JOIN emails e USING(email_id)
                   ORDER BY r.score DESC, LENGTH(r.rules) DESC, e.sent_at_utc DESC""")
    view = flagged[flagged.score >= min_score]
    for rid in pick_rules:
        view = view[view.rules.str.split(",").apply(lambda xs, rid=rid: rid in xs)]
    if sender_q:
        view = view[view.sender.str.contains(sender_q, case=False, regex=False)]
    if text_q:
        ids = q("SELECT email_id FROM emails WHERE email_id IN (SELECT email_id FROM risk_results) "
                "AND (subject LIKE ? OR body_authored LIKE ?)", (f"%{text_q}%", f"%{text_q}%")).email_id
        view = view[view.email_id.isin(set(ids))]
    view = view.reset_index(drop=True)
    view.insert(0, "rank", view.index + 1)

    if view.empty:
        st.info("No flagged emails match these filters.")
    else:
        st.caption(f"{len(view):,} of {len(flagged):,} flagged emails · select a row to see the evidence")
        sel = st.dataframe(
            view[["rank", "score", "priority", "sent_at_utc", "sender", "subject", "rules"]],
            hide_index=True, use_container_width=True, height=330,
            on_select="rerun", selection_mode="single-row", key="flag_table",
            column_config={"score": st.column_config.ProgressColumn("score", min_value=0, max_value=100, format="%d"),
                           "sent_at_utc": "date (UTC)"})
        rows = sel.selection.rows if sel and sel.selection else []
        st.divider()
        render_evidence(view.email_id.iat[rows[0]] if rows else view.email_id.iat[0])

# ----- Network & people (R1 + R2 people view) -----
with tab_net:
    st.subheader("Who communicates most frequently with whom?")
    n_nodes = st.slider("People shown (most active by email volume)", 15, 50, 30, 5)
    nodes = q("""SELECT addr, SUM(n) AS volume FROM (
                   SELECT sender AS addr, n_emails AS n FROM edges
                   UNION ALL SELECT recipient, n_emails FROM edges)
                 GROUP BY addr ORDER BY volume DESC LIMIT ?""", (n_nodes,))
    keep = set(nodes.addr)
    edges = q("SELECT sender, recipient, n_emails FROM edges ORDER BY n_emails DESC LIMIT 20000")
    sub = edges[edges.sender.isin(keep) & edges.recipient.isin(keep)]
    G = nx.DiGraph()
    G.add_nodes_from(keep)
    for s, r, n in sub.values:
        G.add_edge(s, r, weight=int(n))
    pos = nx.spring_layout(G, seed=42, k=1.2, weight="weight")
    wmax = max([d["weight"] for *_, d in G.edges(data=True)] or [1])
    fig = go.Figure()
    for s, r, d in G.edges(data=True):
        fig.add_trace(go.Scatter(x=[pos[s][0], pos[r][0]], y=[pos[s][1], pos[r][1]], mode="lines",
                                 line=dict(width=0.5 + 6 * d["weight"] / wmax, color="rgba(120,120,160,0.35)"),
                                 hoverinfo="skip", showlegend=False))
    mids = [((pos[s][0] + pos[r][0]) / 2, (pos[s][1] + pos[r][1]) / 2, f"{s} → {r}: {d['weight']:,} emails")
            for s, r, d in G.edges(data=True)]
    if mids:
        fig.add_trace(go.Scatter(x=[m[0] for m in mids], y=[m[1] for m in mids], mode="markers",
                                 marker=dict(size=6, opacity=0), hovertext=[m[2] for m in mids],
                                 hoverinfo="text", showlegend=False))
    vol_map = dict(nodes.values)
    vmax = max(vol_map.values())
    fig.add_trace(go.Scatter(
        x=[pos[n][0] for n in G.nodes], y=[pos[n][1] for n in G.nodes], mode="markers+text",
        marker=dict(size=[10 + 30 * vol_map[n] / vmax for n in G.nodes], color="#4C78A8"),
        text=[n.split("@")[0] for n in G.nodes], textposition="top center", textfont_size=10,
        hovertext=[f"{n}<br>{vol_map[n]:,} emails sent+received" for n in G.nodes], hoverinfo="text",
        showlegend=False))
    fig.update_layout(height=600, margin=dict(t=10, b=10, l=10, r=10),
                      xaxis=dict(visible=False), yaxis=dict(visible=False), plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Circle size = email volume; line thickness = emails between the two addresses "
               "(hover the middle of a line). Connectivity describes communication, not wrongdoing.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Top communication pairs**")
        pairs = q("SELECT sender, recipient, n_emails FROM edges ORDER BY n_emails DESC LIMIT 25")
        psel = st.dataframe(pairs, hide_index=True, use_container_width=True, height=300,
                            on_select="rerun", selection_mode="single-row", key="pair_table")
        prow = psel.selection.rows if psel and psel.selection else []
    with c2:
        st.markdown("**People with the most flagged emails** (≥ "
                    f"{load_rules()['people']['min_sent_emails']} sent emails)")
        people = q("""SELECT sender, sender_name, n_sent, n_flagged, flag_rate_per_1000, max_score, top_rule
                      FROM people WHERE eligible = 1 AND n_flagged > 0
                      ORDER BY n_flagged DESC, flag_rate_per_1000 DESC, max_score DESC LIMIT 50""")
        hsel = st.dataframe(people, hide_index=True, use_container_width=True, height=300,
                            on_select="rerun", selection_mode="single-row", key="people_table",
                            column_config={"flag_rate_per_1000": "flagged per 1,000"})
        hrow = hsel.selection.rows if hsel and hsel.selection else []

    if prow:
        s, r = pairs.sender.iat[prow[0]], pairs.recipient.iat[prow[0]]
        st.markdown(f"**Emails {html.escape(s)} → {html.escape(r)}** (most recent 200)")
        st.dataframe(q("""SELECT e.sent_at_utc, e.subject, rr.score, e.email_id FROM emails e
                          JOIN recipients x USING(email_id) LEFT JOIN risk_results rr USING(email_id)
                          WHERE e.sender = ? AND x.recipient = ? AND e.date_valid = 1
                          ORDER BY e.sent_at_utc DESC LIMIT 200""", (s, r)),
                     hide_index=True, use_container_width=True, height=250)
    if hrow:
        who = people.sender.iat[hrow[0]]
        st.markdown(f"**Flagged emails sent by {html.escape(who)}** — select one for evidence")
        pf = q("""SELECT r.email_id, r.score, r.rules, e.sent_at_utc, e.subject FROM risk_results r
                  JOIN emails e USING(email_id) WHERE e.sender = ? ORDER BY r.score DESC""", (who,))
        esel = st.dataframe(pf, hide_index=True, use_container_width=True, height=220,
                            on_select="rerun", selection_mode="single-row", key="person_emails")
        erow = esel.selection.rows if esel and esel.selection else []
        render_evidence(pf.email_id.iat[erow[0]] if erow else pf.email_id.iat[0])

# ----- Method & precision -----
with tab_method:
    cfg = load_rules()
    st.subheader("How are emails flagged?")
    st.markdown(
        "An email is **flagged for review only if a strong language rule fires** on the sender's own words "
        "(quoted replies, forwarded text and legal disclaimers are removed first). Communication and timing "
        "signals only **add** points to an already-flagged email — being unusual alone never flags anyone.\n\n"
        "`score = min(100, K + C + T)` · K language 0–60 · C communication 0–30 · T timing 0–10 · "
        f"medium ≥ {cfg['priority_bands']['medium']}, high ≥ {cfg['priority_bands']['high']} · "
        f"rules v{cfg['rule_version']}")
    rows = [(r["id"], "K language", cfg["language"]["points_per_strong_rule"], r["explanation"])
            for r in cfg["language"]["strong_rules"]]
    t = cfg["language"]["topic_rule"]
    com, tim = cfg["communication"], cfg["timing"]
    rows += [(t["id"], "K language (context only)", t["points"], t["explanation"]),
             (com["external"]["id"], "C communication", com["external"]["points"], com["external"]["explanation"]),
             (com["rare_pair"]["id"], "C communication", com["rare_pair"]["points"], com["rare_pair"]["explanation"]),
             (tim["weekend"]["id"], "T timing", tim["weekend"]["points"], tim["weekend"]["explanation"]),
             (tim["hour_rule"]["id"], "T timing", 0, tim["hour_rule"]["explanation"])]
    st.dataframe(pd.DataFrame(rows, columns=["rule", "signal", "points", "meaning"]),
                 hide_index=True, use_container_width=True)
    st.caption("Full patterns and exclusions: config/rules.json")

    counts = q("SELECT rules FROM risk_results").rules.str.split(",").explode().value_counts()
    st.markdown("**How often each rule fired on the processed corpus**")
    st.bar_chart(counts)

    st.subheader("How accurate are the flags?")
    if os.path.exists(METRICS_PATH):
        with open(METRICS_PATH, encoding="utf-8") as f:
            met = json.load(f)
        st.json(met)
    else:
        st.info("Precision pending manual review. Fill docs/ANNOTATION_TEMPLATE.csv and run "
                "`python -m src.evaluate score --labels <file>`.")

    st.subheader("Run details")
    st.json(M)
