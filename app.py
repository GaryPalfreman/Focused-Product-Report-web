import io

import pandas as pd
import streamlit as st

from report_generator import (
    available_day_sheets,
    date_range,
    filter_product,
    focused_products,
    generate_pdf,
    load_workbook,
    machine_totals,
    product_totals,
    summary_metrics,
    validate_workbook,
)

st.set_page_config(page_title="Focused Product Report", page_icon="📊", layout="wide")

st.title("Focused Product Report")
st.caption(
    "Upload a weekly production Excel workbook, focus the report on one product or view all products, preview the results, and download a finished PDF report."
)

with st.sidebar:
    st.header("Report settings")
    st.caption("No report data is deliberately stored by this app. Uploaded workbooks are processed only for the active session.")

uploaded = st.file_uploader("Upload weekly production Excel workbook", type=["xlsx", "xlsm", "xls"])

if uploaded is None:
    st.info("Upload a production workbook to begin.")
    st.stop()

try:
    workbook_bytes = uploaded.getvalue()
    sheets = load_workbook(workbook_bytes)
except Exception as exc:
    st.error(f"Could not read this workbook: {exc}")
    st.stop()

errors = validate_workbook(sheets)
if errors:
    st.error("The workbook needs attention before a report can be generated.")
    for error in errors:
        st.write(f"- {error}")
    st.stop()

products = focused_products(sheets)
with st.sidebar:
    focus_mode = st.radio("Report scope", ["All products", "One focused product"])
    selected_product = None
    if focus_mode == "One focused product":
        if products:
            selected_product = st.selectbox("Focused product", products)
        else:
            st.warning("No Product Name values were found in the day sheets.")

filtered = filter_product(sheets, selected_product)
metrics = summary_metrics(filtered)
start_date, end_date = date_range(filtered)

st.subheader("Report overview")
cols = st.columns(6)
cols[0].metric("Completed", f"{metrics['completed']:.0f}")
cols[1].metric("Rejected", f"{metrics['rejected']:.0f}")
cols[2].metric("Accepted", f"{metrics['accepted']:.0f}")
cols[3].metric("Rejection rate", f"{metrics['rejection_rate']:.2f}%")
cols[4].metric("Machines", metrics["machines"])
cols[5].metric("Orders", metrics["orders"])

scope_text = selected_product if selected_product else "All products"
st.caption(f"Scope: {scope_text}  |  Reporting period: {start_date} to {end_date}")

tab1, tab2, tab3, tab4 = st.tabs(["Daily Production", "Machine Summary", "Product Summary", "Generate Report"])

with tab1:
    daily = metrics["daily"]
    if daily.empty:
        st.info("No matching production data was found for this report scope.")
    else:
        chart_df = daily.set_index("Day")[["Completed Quantity", "Rejected Quantity"]]
        st.bar_chart(chart_df, use_container_width=True)
        st.dataframe(daily, use_container_width=True, hide_index=True)

        for day in available_day_sheets(filtered):
            df = filtered[day]
            if df.empty:
                continue
            with st.expander(f"{day} production records"):
                display = df.copy()
                for col in display.columns:
                    if pd.api.types.is_datetime64_any_dtype(display[col]):
                        display[col] = display[col].dt.strftime("%Y-%m-%d")
                st.dataframe(display, use_container_width=True, hide_index=True)

with tab2:
    machines = machine_totals(filtered)
    if machines.empty:
        st.info("No machine production data is available for this scope.")
    else:
        st.bar_chart(machines.set_index("Machine Name")["Completed Quantity"], use_container_width=True)
        st.dataframe(machines, use_container_width=True, hide_index=True)

with tab3:
    products_summary = product_totals(filtered)
    if products_summary.empty:
        st.info("No product production data is available for this scope.")
    else:
        st.bar_chart(products_summary.set_index("Product Name")["Completed Quantity"], use_container_width=True)
        st.dataframe(products_summary, use_container_width=True, hide_index=True)

with tab4:
    report_title = "Focused Product Report"
    if selected_product:
        report_title += f" - {selected_product}"

    st.markdown(f"### {report_title}")
    st.write(f"**From:** {start_date}")
    st.write(f"**To:** {end_date}")
    st.write(f"**Completed:** {metrics['completed']:.0f}")
    st.write(f"**Rejected:** {metrics['rejected']:.0f}")
    st.write(f"**Accepted:** {metrics['accepted']:.0f}")
    st.write(f"**Rejection rate:** {metrics['rejection_rate']:.2f}%")

    try:
        pdf_bytes = generate_pdf(filtered, selected_product)
    except Exception as exc:
        st.error(f"The PDF could not be generated: {exc}")
    else:
        safe_product = "all-products" if not selected_product else "".join(
            ch if ch.isalnum() or ch in "-_" else "_" for ch in selected_product
        )
        file_name = f"Focused_Product_Report_{safe_product}_{start_date}_to_{end_date}.pdf"
        st.download_button(
            "Download Focused Product Report PDF",
            data=pdf_bytes,
            file_name=file_name,
            mime="application/pdf",
            use_container_width=True,
        )

st.divider()
st.caption(
    "This web version replaces the original fixed Mac file paths with browser upload/download and changes the report terminology from Cone Report to Focused Product Report."
)
