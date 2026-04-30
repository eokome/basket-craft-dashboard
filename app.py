import os
import datetime
import pandas as pd
import streamlit as st
import snowflake.connector
from dotenv import load_dotenv

load_dotenv()

st.title("Basket Craft — Merchandising Dashboard")


def get_connection():
    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
        role=os.getenv("SNOWFLAKE_ROLE"),
    )


# ── Sidebar date filter ───────────────────────────────────────────────
st.sidebar.header("Filters")
date_min = datetime.date(2023, 3, 1)
date_max = datetime.date(2026, 3, 31)

start_date = st.sidebar.date_input("Start date", value=date_min, min_value=date_min, max_value=date_max)
end_date   = st.sidebar.date_input("End date",   value=date_max, min_value=date_min, max_value=date_max)


# ── KPI metrics (always current vs prior month, ignores date filter) ──
@st.cache_data(ttl=600)
def get_kpi_metrics():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        WITH monthly AS (
            SELECT
                DATE_TRUNC('MONTH', "created_at")  AS month,
                SUM("price_usd")                   AS revenue,
                COUNT(DISTINCT "order_id")         AS orders,
                COUNT(*)                           AS items_sold
            FROM BASKET_CRAFT.RAW."order_items"
            GROUP BY 1
        ),
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (ORDER BY month DESC) AS rn
            FROM monthly
        )
        SELECT
            MAX(CASE WHEN rn = 1 THEN revenue    END) AS cur_revenue,
            MAX(CASE WHEN rn = 2 THEN revenue    END) AS prev_revenue,
            MAX(CASE WHEN rn = 1 THEN orders     END) AS cur_orders,
            MAX(CASE WHEN rn = 2 THEN orders     END) AS prev_orders,
            MAX(CASE WHEN rn = 1 THEN items_sold END) AS cur_items,
            MAX(CASE WHEN rn = 2 THEN items_sold END) AS prev_items
        FROM ranked
        WHERE rn <= 2
    """)
    row = cur.fetchone()
    conn.close()

    cur_rev, prev_rev, cur_ord, prev_ord, cur_itm, prev_itm = row

    def delta_pct(cur, prev):
        if prev and prev != 0:
            return (cur - prev) / prev
        return None

    cur_aov  = cur_rev  / cur_ord  if cur_ord  else 0
    prev_aov = prev_rev / prev_ord if prev_ord else 0

    return {
        "revenue":    (cur_rev,  delta_pct(cur_rev,  prev_rev)),
        "orders":     (cur_ord,  delta_pct(cur_ord,  prev_ord)),
        "aov":        (cur_aov,  delta_pct(cur_aov,  prev_aov)),
        "items_sold": (cur_itm,  delta_pct(cur_itm,  prev_itm)),
    }


metrics = get_kpi_metrics()

col1, col2, col3, col4 = st.columns(4)

rev_val, rev_delta = metrics["revenue"]
ord_val, ord_delta = metrics["orders"]
aov_val, aov_delta = metrics["aov"]
itm_val, itm_delta = metrics["items_sold"]

col1.metric("Total Revenue",  f"${rev_val:,.0f}",  f"{rev_delta:+.1%}" if rev_delta is not None else None)
col2.metric("Total Orders",   f"{ord_val:,}",       f"{ord_delta:+.1%}" if ord_delta is not None else None)
col3.metric("Avg Order Value", f"${aov_val:,.2f}",  f"{aov_delta:+.1%}" if aov_delta is not None else None)
col4.metric("Items Sold",     f"{itm_val:,}",       f"{itm_delta:+.1%}" if itm_delta is not None else None)


# ── Revenue trend ─────────────────────────────────────────────────────
@st.cache_data(ttl=600)
def get_revenue_trend(start: datetime.date, end: datetime.date) -> pd.DataFrame:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            DATE_TRUNC('MONTH', "created_at") AS month,
            SUM("price_usd")                  AS revenue
        FROM BASKET_CRAFT.RAW."order_items"
        WHERE "created_at" BETWEEN %s AND %s
        GROUP BY 1
        ORDER BY 1
    """, (start, end))
    rows = cur.fetchall()
    conn.close()
    df = pd.DataFrame(rows, columns=["Month", "Revenue"])
    df["Month"] = pd.to_datetime(df["Month"])
    return df.set_index("Month")


st.subheader("Revenue Trend")
trend_df = get_revenue_trend(start_date, end_date)
st.line_chart(trend_df["Revenue"])


# ── Top products by revenue ───────────────────────────────────────────
@st.cache_data(ttl=600)
def get_top_products(start: datetime.date, end: datetime.date) -> pd.DataFrame:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT p.PRODUCT_NAME, SUM(oi."price_usd") AS revenue
        FROM BASKET_CRAFT.RAW."order_items" oi
        JOIN BASKET_CRAFT.ANALYTICS.DIM_PRODUCT p ON oi."product_id" = p.PRODUCT_ID
        WHERE oi."created_at" BETWEEN %s AND %s
        GROUP BY 1
        ORDER BY 2 DESC
    """, (start, end))
    rows = cur.fetchall()
    conn.close()
    return pd.DataFrame(rows, columns=["Product", "Revenue"]).set_index("Product")


st.subheader("Top Products by Revenue")
products_df = get_top_products(start_date, end_date)
st.bar_chart(products_df["Revenue"])


# ── Bundle finder ─────────────────────────────────────────────────────
@st.cache_data(ttl=600)
def get_product_list() -> list[tuple[int, str]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT PRODUCT_ID, PRODUCT_NAME FROM BASKET_CRAFT.ANALYTICS.DIM_PRODUCT ORDER BY PRODUCT_ID")
    rows = cur.fetchall()
    conn.close()
    return rows


@st.cache_data(ttl=600)
def get_bundles(product_id: int) -> pd.DataFrame:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT p.PRODUCT_NAME AS "Also Bought", COUNT(DISTINCT oi2."order_id") AS "# of Orders"
        FROM BASKET_CRAFT.RAW."order_items" oi1
        JOIN BASKET_CRAFT.RAW."order_items" oi2
            ON  oi1."order_id"   = oi2."order_id"
            AND oi1."product_id" != oi2."product_id"
        JOIN BASKET_CRAFT.ANALYTICS.DIM_PRODUCT p ON oi2."product_id" = p.PRODUCT_ID
        WHERE oi1."product_id" = %s
        GROUP BY 1
        ORDER BY 2 DESC
    """, (product_id,))
    rows = cur.fetchall()
    conn.close()
    return pd.DataFrame(rows, columns=["Also Bought", "# of Orders"])


st.subheader("Bundle Finder: Bought With…")

product_list = get_product_list()
product_names = [name for _, name in product_list]
product_ids   = {name: pid for pid, name in product_list}

selected = st.selectbox("Pick a product", product_names)
bundles_df = get_bundles(product_ids[selected])

st.dataframe(bundles_df, use_container_width=True, hide_index=True)
st.download_button(
    label="Download CSV",
    data=bundles_df.to_csv(index=False).encode(),
    file_name=f"bundles_{selected.replace(' ', '_')}.csv",
    mime="text/csv",
)
