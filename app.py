"""Streamlit 대시보드: DB 로그인(SHA-256), 3회 실패 시 5분 잠금, 사이드바 필터."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import db

st.set_page_config(page_title="BZ 대시보드", layout="wide", initial_sidebar_state="expanded")

db.init_db()


def ensure_session() -> None:
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False


def _ensure_ad_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "channel" not in out.columns:
        out["channel"] = "기타"
    else:
        out["channel"] = out["channel"].replace("", "기타").fillna("기타")
    if "conversions" not in out.columns:
        out["conversions"] = 0
    out["conversions"] = pd.to_numeric(out["conversions"], errors="coerce").fillna(0)
    out["ad_spend"] = pd.to_numeric(out["ad_spend"], errors="coerce").fillna(0)
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce").fillna(0)
    return out


def _prev_period(d0: date, d1: date) -> tuple[date, date]:
    """선택 기간과 동일한 길이의 직전 구간."""
    n = (d1 - d0).days + 1
    p1 = d0 - timedelta(days=1)
    p0 = p1 - timedelta(days=n - 1)
    return p0, p1


def _period_kpis(frame: pd.DataFrame) -> tuple[float, float, float, float]:
    """(광고비, 매출, ROAS%, CPA). ROAS는 매출÷광고비×100."""
    if frame is None or frame.empty:
        return 0.0, 0.0, 0.0, float("nan")
    spend = float(frame["ad_spend"].sum())
    rev = float(frame["amount"].sum())
    conv = float(frame["conversions"].sum())
    roas_pct = (rev / spend * 100.0) if spend > 0 else 0.0
    cpa = (spend / conv) if conv > 0 else float("nan")
    return spend, rev, roas_pct, cpa


def _fmt_metric_delta(curr: float, prev: float) -> str | None:
    if prev == 0:
        if curr == 0:
            return None
        return "신규"
    p = (curr - prev) / prev * 100.0
    return f"{p:+.1f}%"


def _pct_change(curr: float, prev: float) -> float:
    if prev == 0:
        return float("nan") if curr == 0 else float("inf")
    return (curr - prev) / prev * 100.0


def _roas_delta_pct(roas_curr: float, roas_prev: float) -> float:
    if roas_prev == 0:
        return float("nan") if roas_curr == 0 else float("inf")
    return (roas_curr - roas_prev) / roas_prev * 100.0


def _agg_by_channel(d: pd.DataFrame) -> pd.DataFrame:
    if d.empty:
        return pd.DataFrame(
            columns=["channel", "ad_spend", "revenue", "conversions", "roas"]
        )
    g = d.groupby("channel", as_index=False).agg(
        ad_spend=("ad_spend", "sum"),
        revenue=("amount", "sum"),
        conversions=("conversions", "sum"),
    )
    spend = g["ad_spend"].astype(float)
    rev = g["revenue"].astype(float)
    g["roas"] = np.where(spend > 0, rev / spend, 0.0)
    return g


def _weekly_channel_comparison_table(
    anchor: date,
) -> tuple[pd.DataFrame, tuple[date, date, date, date]] | tuple[None, tuple[date, date, date, date]]:
    """이번주(anchor 기준 최근 7일) vs 직전 7일, 채널별 집계."""
    tw_end = anchor
    tw_start = anchor - timedelta(days=6)
    pw_end = anchor - timedelta(days=7)
    pw_start = anchor - timedelta(days=13)

    rows = db.fetch_sales_date_range(
        pw_start.isoformat(),
        tw_end.isoformat(),
    )
    raw = pd.DataFrame([dict(r) for r in rows])
    if raw.empty:
        return None, (tw_start, tw_end, pw_start, pw_end)

    raw["sale_date"] = pd.to_datetime(raw["sale_date"]).dt.date
    if "channel" not in raw.columns:
        raw["channel"] = "기타"
    raw["channel"] = raw["channel"].replace("", "기타").fillna("기타")
    if "conversions" not in raw.columns:
        raw["conversions"] = 0

    tw_mask = (raw["sale_date"] >= tw_start) & (raw["sale_date"] <= tw_end)
    pw_mask = (raw["sale_date"] >= pw_start) & (raw["sale_date"] <= pw_end)
    tw_df = _agg_by_channel(raw.loc[tw_mask])
    pw_df = _agg_by_channel(raw.loc[pw_mask])

    channels = sorted(
        set(tw_df["channel"].tolist()) | set(pw_df["channel"].tolist())
    )
    rec: list[dict[str, float | str]] = []
    for ch in channels:
        a = tw_df[tw_df["channel"] == ch]
        b = pw_df[pw_df["channel"] == ch]
        spend_tw = float(a["ad_spend"].iloc[0]) if not a.empty else 0.0
        spend_pw = float(b["ad_spend"].iloc[0]) if not b.empty else 0.0
        rev_tw = float(a["revenue"].iloc[0]) if not a.empty else 0.0
        rev_pw = float(b["revenue"].iloc[0]) if not b.empty else 0.0
        conv_tw = float(a["conversions"].iloc[0]) if not a.empty else 0.0
        conv_pw = float(b["conversions"].iloc[0]) if not b.empty else 0.0
        roas_tw = float(a["roas"].iloc[0]) if not a.empty else 0.0
        roas_pw = float(b["roas"].iloc[0]) if not b.empty else 0.0

        rec.append(
            {
                "채널": ch,
                "광고비(전주)": spend_pw,
                "광고비(금주)": spend_tw,
                "광고비 증감(%)": _pct_change(spend_tw, spend_pw),
                "매출(전주)": rev_pw,
                "매출(금주)": rev_tw,
                "매출 증감(%)": _pct_change(rev_tw, rev_pw),
                "ROAS(전주)": roas_pw,
                "ROAS(금주)": roas_tw,
                "ROAS 증감(%)": _roas_delta_pct(roas_tw, roas_pw),
                "전환(전주)": conv_pw,
                "전환(금주)": conv_tw,
                "전환 증감(%)": _pct_change(conv_tw, conv_pw),
            }
        )

    out = pd.DataFrame(rec).sort_values("채널").reset_index(drop=True)
    return out, (tw_start, tw_end, pw_start, pw_end)


def _style_weekly_comparison(df: pd.DataFrame) -> Any:
    work = df.copy()
    delta_cols = [
        "광고비 증감(%)",
        "매출 증감(%)",
        "ROAS 증감(%)",
        "전환 증감(%)",
    ]
    money_cols = ["광고비(전주)", "광고비(금주)", "매출(전주)", "매출(금주)"]
    conv_cols = ["전환(전주)", "전환(금주)"]
    roas_cols = ["ROAS(전주)", "ROAS(금주)"]

    for c in delta_cols:
        if c in work.columns:
            work[c] = work[c].replace([np.inf, -np.inf], np.nan)

    def _delta_color(v: object) -> str:
        if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
            return ""
        try:
            x = float(v)
        except (TypeError, ValueError):
            return ""
        if x > 0:
            return "color: #198754; font-weight: 600"
        if x < 0:
            return "color: #dc3545; font-weight: 600"
        return "color: #6c757d"

    fmt: dict[str, str] = {c: "{:,.0f}원" for c in money_cols}
    fmt.update({c: "{:,.0f}" for c in conv_cols})
    fmt.update({c: "{:.2f}" for c in roas_cols})
    fmt.update({c: "{:+.1f}%" for c in delta_cols})

    sty = work.style.map(_delta_color, subset=delta_cols).format(fmt, na_rep="—")
    return sty


def login_view() -> None:
    st.title("로그인")
    st.caption("데모 계정: ID `admin` / PW `admin1234` · 비밀번호는 SHA-256으로 검증됩니다.")
    with st.form("login_form", clear_on_submit=False):
        uid = st.text_input("아이디", key="login_id")
        pw = st.text_input("비밀번호", type="password", key="login_pw")
        submitted = st.form_submit_button("로그인", type="primary")
    if submitted:
        ok, msg = db.try_login(uid, pw)
        if ok:
            st.session_state.authenticated = True
            st.session_state.pop("login_pw", None)
            st.rerun()
        elif msg:
            st.error(msg)


def dashboard() -> None:
    mn, mx = db.sales_date_bounds()
    cats = db.distinct_categories()
    regs = db.distinct_regions()

    with st.sidebar:
        st.header("필터")
        dr = st.date_input(
            "기간",
            value=(
                pd.to_datetime(mn).date(),
                pd.to_datetime(mx).date(),
            ),
            min_value=pd.to_datetime(mn).date(),
            max_value=pd.to_datetime(mx).date(),
        )
        if isinstance(dr, tuple) and len(dr) == 2:
            d0, d1 = dr[0], dr[1]
        else:
            d0 = d1 = dr
        cat_sel = st.multiselect("카테고리", options=cats, default=cats)
        reg_sel = st.multiselect("지역", options=regs, default=regs)
        st.divider()
        if st.button("로그아웃"):
            st.session_state.authenticated = False
            st.rerun()

    df_from = d0.isoformat() if d0 else None
    df_to = d1.isoformat() if d1 else None
    cat_filter = cat_sel if cat_sel else None
    reg_filter = reg_sel if reg_sel else None

    rows = db.fetch_sales(df_from, df_to, cat_filter, reg_filter)
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        st.warning("조건에 맞는 데이터가 없습니다.")
        return

    df["sale_date"] = pd.to_datetime(df["sale_date"])
    df = _ensure_ad_columns(df)

    d0_date = d0 if isinstance(d0, date) else pd.to_datetime(d0).date()
    d1_date = d1 if isinstance(d1, date) else pd.to_datetime(d1).date()
    p0, p1 = _prev_period(d0_date, d1_date)
    rows_prev = db.fetch_sales(
        p0.isoformat(),
        p1.isoformat(),
        cat_filter,
        reg_filter,
    )
    df_prev = _ensure_ad_columns(pd.DataFrame([dict(r) for r in rows_prev]))
    if not df_prev.empty:
        df_prev["sale_date"] = pd.to_datetime(df_prev["sale_date"])

    spend_c, rev_c, roas_c, cpa_c = _period_kpis(df)
    spend_p, rev_p, roas_p, cpa_p = _period_kpis(df_prev)

    tab_dash, = st.tabs(["대시보드"])
    with tab_dash:
        st.title("대시보드")
        st.caption(
            f"선택 기간: {d0_date} ~ {d1_date} · 비교: 직전 동일 길이 기간 "
            f"({p0} ~ {p1})"
        )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric(
            "광고비",
            f"{spend_c:,.0f}원",
            delta=_fmt_metric_delta(spend_c, spend_p),
            delta_color="inverse",
        )
        m2.metric(
            "매출",
            f"{rev_c:,.0f}원",
            delta=_fmt_metric_delta(rev_c, rev_p),
            delta_color="normal",
        )
        m3.metric(
            "ROAS",
            f"{roas_c:.1f}%",
            delta=_fmt_metric_delta(roas_c, roas_p),
            delta_color="normal",
        )
        if np.isnan(cpa_c):
            m4.metric("CPA", "—", delta=None, delta_color="inverse")
        else:
            cpa_delta = None if np.isnan(cpa_p) else _fmt_metric_delta(cpa_c, cpa_p)
            m4.metric(
                "CPA",
                f"{cpa_c:,.0f}원",
                delta=cpa_delta,
                delta_color="inverse",
            )

        st.subheader("추이")
        trend_metric = st.radio(
            "지표",
            ["광고비", "매출", "ROAS", "CPA"],
            horizontal=True,
            key="dash_trend_metric",
        )
        daily_t = (
            df.assign(day=df["sale_date"].dt.date)
            .groupby("day", as_index=False)
            .agg(
                ad_spend=("ad_spend", "sum"),
                revenue=("amount", "sum"),
                conversions=("conversions", "sum"),
            )
        )
        daily_t["roas_pct"] = np.where(
            daily_t["ad_spend"] > 0,
            daily_t["revenue"] / daily_t["ad_spend"] * 100.0,
            0.0,
        )
        daily_t["cpa"] = np.where(
            daily_t["conversions"] > 0,
            daily_t["ad_spend"] / daily_t["conversions"],
            np.nan,
        )

        fig_t = go.Figure()
        x_dt = daily_t["day"]
        if trend_metric == "광고비":
            fig_t.add_trace(
                go.Scatter(
                    x=x_dt,
                    y=daily_t["ad_spend"],
                    mode="lines+markers",
                    name="광고비",
                    line=dict(color="#636EFA"),
                )
            )
            fig_t.update_layout(yaxis_title="원")
        elif trend_metric == "매출":
            fig_t.add_trace(
                go.Scatter(
                    x=x_dt,
                    y=daily_t["revenue"],
                    mode="lines+markers",
                    name="매출",
                    line=dict(color="#00CC96"),
                )
            )
            fig_t.update_layout(yaxis_title="원")
        elif trend_metric == "ROAS":
            fig_t.add_trace(
                go.Scatter(
                    x=x_dt,
                    y=daily_t["roas_pct"],
                    mode="lines+markers",
                    name="ROAS",
                    line=dict(color="#AB63FA"),
                )
            )
            fig_t.add_hline(
                y=200,
                line_dash="dash",
                line_color="rgba(128,128,128,0.9)",
                annotation_text="손익분기 200%",
                annotation_position="right",
            )
            fig_t.update_layout(yaxis_title="ROAS (%)")
        else:
            fig_t.add_trace(
                go.Scatter(
                    x=x_dt,
                    y=daily_t["cpa"],
                    mode="lines+markers",
                    name="CPA",
                    line=dict(color="#EF553B"),
                )
            )
            fig_t.update_layout(yaxis_title="원 (전환당)")

        fig_t.update_layout(
            height=420,
            margin=dict(l=8, r=8, t=40, b=8),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            xaxis_title="일자",
        )
        st.plotly_chart(fig_t, use_container_width=True)

        st.subheader("채널")
        ch = _agg_by_channel(df)
        if ch.empty:
            st.info("채널 데이터가 없습니다.")
        else:
            c_left, c_right = st.columns(2)
            with c_left:
                fig_p = go.Figure(
                    data=[
                        go.Pie(
                            labels=ch["channel"],
                            values=ch["ad_spend"],
                            hole=0.52,
                            textinfo="percent+label",
                        )
                    ]
                )
                fig_p.update_layout(
                    title="채널별 광고비 비중",
                    height=400,
                    margin=dict(t=50, b=8, l=8, r=8),
                    showlegend=False,
                )
                st.plotly_chart(fig_p, use_container_width=True)
            with c_right:
                ch_bar = ch.sort_values("roas", ascending=True)
                roas_pct_bar = ch_bar["roas"].astype(float) * 100.0
                fig_b = go.Figure(
                    go.Bar(
                        x=roas_pct_bar,
                        y=ch_bar["channel"],
                        orientation="h",
                        marker_color="#636EFA",
                        name="ROAS",
                    )
                )
                fig_b.add_vline(
                    x=200,
                    line_dash="dash",
                    line_color="rgba(128,128,128,0.9)",
                )
                fig_b.update_layout(
                    title="채널별 ROAS (%)",
                    height=400,
                    margin=dict(t=50, b=8, l=8, r=8),
                    xaxis_title="ROAS (%)",
                    yaxis_title="",
                )
                st.plotly_chart(fig_b, use_container_width=True)

        st.subheader("주간 성과 비교 (채널별)")
        data_mx = pd.to_datetime(mx).date()
        anchor = min(date.today(), data_mx)
        comp, bounds = _weekly_channel_comparison_table(anchor)
        tw_s, tw_e, pw_s, pw_e = bounds
        st.caption(
            f"금주(최근 7일): {tw_s} ~ {tw_e} · 전주: {pw_s} ~ {pw_e} "
            "(DB 최신일 기준으로 달력을 맞춥니다)"
        )
        if comp is None or comp.empty:
            st.info("주간 비교에 사용할 기간 데이터가 없습니다.")
        else:
            st.dataframe(
                _style_weekly_comparison(comp),
                use_container_width=True,
                hide_index=True,
            )

        with st.expander("원본 데이터 미리보기"):
            st.dataframe(
                df.sort_values("sale_date", ascending=False),
                use_container_width=True,
            )


def main() -> None:
    ensure_session()
    if not st.session_state.authenticated:
        login_view()
    else:
        dashboard()


main()
