"""Streamlit 대시보드: DB 로그인(SHA-256), 3회 실패 시 5분 잠금, 사이드바 필터."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
import streamlit as st

import db

st.set_page_config(page_title="BZ 대시보드", layout="wide", initial_sidebar_state="expanded")

db.init_db()


def ensure_session() -> None:
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False


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
    total_amt = df["amount"].sum()
    total_qty = df["quantity"].sum()
    orders = len(df)

    tab_dash, = st.tabs(["대시보드"])
    with tab_dash:
        st.title("매출 대시보드")
        c1, c2, c3 = st.columns(3)
        c1.metric("총 매출액", f"{total_amt:,.0f}원")
        c2.metric("총 판매 수량", f"{int(total_qty):,}")
        c3.metric("건수", f"{orders:,}")

        total_clk = int(df["clicks"].sum())
        total_imp = int(df["impressions"].sum())
        ctr_pct = (total_clk / total_imp * 100.0) if total_imp else 0.0
        total_spend = float(df["ad_spend"].sum())
        cpc = (total_spend / total_clk) if total_clk else 0.0

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("총 클릭수", f"{total_clk:,}")
        k2.metric("총 노출수", f"{total_imp:,}")
        k3.metric("평균 CTR", f"{ctr_pct:.2f}%")
        k4.metric("평균 CPC", f"{cpc:,.0f}원")

        daily = (
            df.assign(일자=df["sale_date"].dt.date)
            .groupby("일자", as_index=False)
            .agg(amount=("amount", "sum"), quantity=("quantity", "sum"))
        )

        st.subheader("일별 매출 추이")
        st.line_chart(daily.set_index("일자")["amount"])

        st.subheader("카테고리별 매출")
        by_cat = (
            df.groupby("category", as_index=False)
            .agg(amount=("amount", "sum"))
            .sort_values("amount", ascending=False)
        )
        st.bar_chart(by_cat.set_index("category")["amount"])

        st.subheader("지역별 매출")
        by_reg = (
            df.groupby("region", as_index=False)
            .agg(amount=("amount", "sum"))
            .sort_values("amount", ascending=False)
        )
        st.bar_chart(by_reg.set_index("region")["amount"])

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
