"""Streamlit 대시보드: DB 로그인(SHA-256), 3회 실패 시 5분 잠금, 사이드바 필터."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import db

st.set_page_config(page_title="BZ 대시보드", layout="wide", initial_sidebar_state="expanded")

db.init_db()


def ensure_session() -> None:
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False


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

    st.title("매출 대시보드")
    c1, c2, c3 = st.columns(3)
    c1.metric("총 매출액", f"{total_amt:,.0f}원")
    c2.metric("총 판매 수량", f"{int(total_qty):,}")
    c3.metric("건수", f"{orders:,}")

    daily = df.groupby(df["sale_date"].dt.date, as_index=False).agg(
        amount=("amount", "sum"),
        quantity=("quantity", "sum"),
    )
    daily = daily.rename(columns={"sale_date": "일자"})

    st.subheader("일별 매출 추이")
    st.line_chart(daily.set_index("일자")["amount"])

    st.subheader("카테고리별 매출")
    by_cat = df.groupby("category", as_index=False)["amount"].sum().sort_values("amount", ascending=False)
    st.bar_chart(by_cat.set_index("category")["amount"])

    st.subheader("지역별 매출")
    by_reg = df.groupby("region", as_index=False)["amount"].sum().sort_values("amount", ascending=False)
    st.bar_chart(by_reg.set_index("region")["amount"])

    with st.expander("원본 데이터 미리보기"):
        st.dataframe(df.sort_values("sale_date", ascending=False), use_container_width=True)


def main() -> None:
    ensure_session()
    if not st.session_state.authenticated:
        login_view()
    else:
        dashboard()


main()
