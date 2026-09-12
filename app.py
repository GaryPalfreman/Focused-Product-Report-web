from datetime import date

import pandas as pd
import streamlit as st

from report_generator import (
    aggregate_dataframe,
    available_day_sheets,
    daily_payload_bytes,
    filter_period_payloads,
    filter_product,
    focused_products,
    generate_period_pdf,
    load_daily_payload,
    load_workbook,
    machine_totals,
    make_daily_payload,
    payloads_to_dataframe,
    product_totals,
    summary_metrics,
    validate_payload_collection,
    validate_workbook,
)

st.set_page_config(page_title="Focused Product Report", page_icon="📊", layout="wide")


def safe_name(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text.strip()) or "focused_product"


def legacy_sheets_to_dataframe(sheets: dict[str, pd.DataFrame], product_name: str) -> pd.DataFrame:
    frames = []
    for day_name in available_day_sheets(sheets):
        source = sheets[day_name].copy()
        if source.empty:
            continue
        if "Product Name" in source.columns:
            source = source[source["Product Name"].astype(str) == str(product_name)].copy()
        if source.empty:
            continue
        if "Date" not in source.columns:
            source["Date"] = pd.NaT
        source["Date"] = pd.to_datetime(source["Date"], errors="coerce")
        for col in ["Machine Name", "Manufacturing Order", "Operation Number"]:
            if col not in source.columns:
                source[col] = ""
            source[col] = source[col].fillna("").astype(str)
        source["Product Name"] = product_name
        source["Completed Quantity"] = pd.to_numeric(source.get("Completed Quantity", 0), errors="coerce").fillna(0)
        if "Rejected Quantity" in source.columns:
            source["Rejected Quantity"] = pd.to_numeric(source["Rejected Quantity"], errors="coerce").fillna(0)
        else:
            source["Rejected Quantity"] = 0.0
        source["Accepted Quantity"] = source["Completed Quantity"] - source["Rejected Quantity"]
        frames.append(source[[
            "Date", "Machine Name", "Manufacturing Order", "Product Name", "Operation Number",
            "Completed Quantity", "Rejected Quantity", "Accepted Quantity"
        ]])
    if not frames:
        return pd.DataFrame(columns=[
            "Date", "Machine Name", "Manufacturing Order", "Product Name", "Operation Number",
            "Completed Quantity", "Rejected Quantity", "Accepted Quantity"
        ])
    return pd.concat(frames, ignore_index=True).sort_values(
        ["Date", "Manufacturing Order", "Operation Number"], kind="stable"
    ).reset_index(drop=True)


def reset_daily_entry():
    st.session_state.daily_records = []
    st.session_state.daily_product = ""
    st.session_state.daily_date = date.today()
    st.session_state.edit_record_index = None
    st.session_state.loaded_daily_key = None


if "daily_records" not in st.session_state:
    st.session_state.daily_records = []
if "daily_product" not in st.session_state:
    st.session_state.daily_product = ""
if "daily_date" not in st.session_state:
    st.session_state.daily_date = date.today()
if "edit_record_index" not in st.session_state:
    st.session_state.edit_record_index = None

st.markdown(
    """
    <style>
    .block-container {max-width: 1280px; padding-top: 1.4rem; padding-bottom: 3rem;}
    div[data-testid="stMetric"] {border: 1px solid rgba(128,128,128,.22); border-radius: 14px; padding: 12px 14px;}
    .record-card {border: 1px solid rgba(128,128,128,.25); border-radius: 14px; padding: 14px 16px; margin: 8px 0 12px 0;}
    .section-note {opacity: .75; margin-top: -6px; margin-bottom: 12px;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Focused Product Report")
st.caption(
    "Enter focused-product production directly, save each day locally as JSON, reload daily files later, and generate weekly, monthly or yearly reports."
)

with st.sidebar:
    st.header("Focused Product Reporting")
    workflow = st.radio("Workflow", ["Daily Entry", "Build Period Report", "Legacy Excel Upload"])
    st.caption("Use JSON and PDF downloads to keep your records on the computer you are using.")

if workflow == "Daily Entry":
    st.subheader("Daily Focused Product Entry")
    st.markdown('<div class="section-note">Use the form below to add one production record at a time. Existing daily JSON files can be loaded, edited and downloaded again.</div>', unsafe_allow_html=True)

    top1, top2 = st.columns([2, 1])
    with top1:
        uploaded_daily = st.file_uploader(
            "Load an existing daily JSON",
            type=["json"],
            key="edit_daily_json",
            help="Use this to continue or correct an existing daily file.",
        )
    with top2:
        st.write("")
        st.write("")
        if st.button("Start New Day", use_container_width=True):
            reset_daily_entry()
            st.rerun()

    if uploaded_daily is not None:
        try:
            raw = uploaded_daily.getvalue()
            payload = load_daily_payload(raw)
        except Exception as exc:
            st.error(f"Could not load this daily file: {exc}")
        else:
            load_key = f"{uploaded_daily.name}:{len(raw)}"
            if st.session_state.get("loaded_daily_key") != load_key:
                st.session_state.daily_records = [
                    {
                        "Machine Name": row.get("Machine Name", ""),
                        "Manufacturing Order": row.get("Manufacturing Order", ""),
                        "Operation Number": row.get("Operation Number", ""),
                        "Completed Quantity": float(row.get("Completed Quantity", 0) or 0),
                        "Rejected Quantity": float(row.get("Rejected Quantity", 0) or 0),
                    }
                    for row in payload["records"]
                ]
                st.session_state.daily_product = payload["product_name"]
                st.session_state.daily_date = pd.Timestamp(payload["date"]).date()
                st.session_state.loaded_daily_key = load_key
                st.session_state.edit_record_index = None
                st.rerun()

    d1, d2 = st.columns(2)
    report_date = d1.date_input("Production date", value=st.session_state.daily_date)
    product_name = d2.text_input("Focused product", value=st.session_state.daily_product, placeholder="e.g. AT7701")
    st.session_state.daily_date = report_date
    st.session_state.daily_product = product_name

    st.markdown("### Add production record")

    edit_index = st.session_state.edit_record_index
    edit_record = None
    if edit_index is not None and 0 <= edit_index < len(st.session_state.daily_records):
        edit_record = st.session_state.daily_records[edit_index]
        st.info(f"Editing record {edit_index + 1}")

    defaults = edit_record or {
        "Machine Name": "",
        "Manufacturing Order": "",
        "Operation Number": "",
        "Completed Quantity": 0.0,
        "Rejected Quantity": 0.0,
    }

    with st.form("production_record_form", clear_on_submit=edit_record is None):
        r1, r2, r3 = st.columns(3)
        machine = r1.text_input("Machine Name", value=str(defaults["Machine Name"]), placeholder="e.g. Puma 2600")
        order = r2.text_input("Manufacturing Order", value=str(defaults["Manufacturing Order"]), placeholder="e.g. MO12345")
        operation = r3.text_input("Operation Number", value=str(defaults["Operation Number"]), placeholder="e.g. OP10")

        q1, q2, q3 = st.columns(3)
        completed = q1.number_input("Completed Quantity", min_value=0.0, step=1.0, value=float(defaults["Completed Quantity"]))
        rejected = q2.number_input("Rejected Quantity", min_value=0.0, step=1.0, value=float(defaults["Rejected Quantity"]))
        accepted = max(completed - rejected, 0.0)
        q3.metric("Accepted Quantity", f"{accepted:.0f}")

        submit_text = "Save Changes" if edit_record is not None else "Add Record"
        submitted = st.form_submit_button(submit_text, use_container_width=True)

    if submitted:
        errors = []
        if not machine.strip():
            errors.append("Machine Name is required.")
        if not order.strip():
            errors.append("Manufacturing Order is required.")
        if not operation.strip():
            errors.append("Operation Number is required.")
        if rejected > completed:
            errors.append("Rejected Quantity cannot be greater than Completed Quantity.")

        if errors:
            for err in errors:
                st.error(err)
        else:
            record = {
                "Machine Name": machine.strip(),
                "Manufacturing Order": order.strip(),
                "Operation Number": operation.strip(),
                "Completed Quantity": float(completed),
                "Rejected Quantity": float(rejected),
            }
            if edit_record is None:
                st.session_state.daily_records.append(record)
            else:
                st.session_state.daily_records[edit_index] = record
                st.session_state.edit_record_index = None
            st.rerun()

    if edit_record is not None:
        if st.button("Cancel Edit", use_container_width=True):
            st.session_state.edit_record_index = None
            st.rerun()

    records = st.session_state.daily_records
    st.divider()
    st.markdown("### Today's records")

    if not records:
        st.info("No production records have been added yet.")
    else:
        df = pd.DataFrame(records)
        df["Accepted Quantity"] = df["Completed Quantity"] - df["Rejected Quantity"]

        total_completed = float(df["Completed Quantity"].sum())
        total_rejected = float(df["Rejected Quantity"].sum())
        total_accepted = total_completed - total_rejected
        rejection_rate = (total_rejected / total_completed * 100) if total_completed else 0.0

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Completed", f"{total_completed:.0f}")
        k2.metric("Rejected", f"{total_rejected:.0f}")
        k3.metric("Accepted", f"{total_accepted:.0f}")
        k4.metric("Rejection rate", f"{rejection_rate:.2f}%")

        for i, row in enumerate(records):
            accepted_row = float(row["Completed Quantity"]) - float(row["Rejected Quantity"])
            st.markdown(
                f"""
                <div class="record-card">
                <b>Record {i + 1}</b><br>
                <b>Machine:</b> {row['Machine Name']} &nbsp;&nbsp; | &nbsp;&nbsp;
                <b>MO:</b> {row['Manufacturing Order']} &nbsp;&nbsp; | &nbsp;&nbsp;
                <b>Operation:</b> {row['Operation Number']}<br>
                <b>Completed:</b> {row['Completed Quantity']:.0f} &nbsp;&nbsp; | &nbsp;&nbsp;
                <b>Rejected:</b> {row['Rejected Quantity']:.0f} &nbsp;&nbsp; | &nbsp;&nbsp;
                <b>Accepted:</b> {accepted_row:.0f}
                </div>
                """,
                unsafe_allow_html=True,
            )
            b1, b2 = st.columns(2)
            if b1.button("Edit", key=f"edit_{i}", use_container_width=True):
                st.session_state.edit_record_index = i
                st.rerun()
            if b2.button("Remove", key=f"remove_{i}", use_container_width=True):
                st.session_state.daily_records.pop(i)
                st.session_state.edit_record_index = None
                st.rerun()

        st.divider()
        if not product_name.strip():
            st.warning("Enter the focused product name before downloading the daily JSON file.")
        else:
            payload = make_daily_payload(report_date, product_name, records)
            filename = f"Focused_Product_{safe_name(product_name)}_{report_date.isoformat()}.json"
            st.download_button(
                "Download Daily JSON",
                data=daily_payload_bytes(payload),
                file_name=filename,
                mime="application/json",
                use_container_width=True,
            )
            st.caption("This dated JSON file can be loaded back into Daily Entry or combined later into weekly, monthly and yearly reports.")

elif workflow == "Build Period Report":
    st.subheader("Build Weekly, Monthly or Yearly Focused Product Report")
    st.write("Upload the daily JSON files you previously downloaded. The app sorts them chronologically by the production date stored inside each file.")

    uploads = st.file_uploader("Upload daily Focused Product JSON files", type=["json"], accept_multiple_files=True, key="period_jsons")
    if not uploads:
        st.info("Upload one or more daily JSON files to begin.")
        st.stop()

    payloads, load_errors = [], []
    for file in uploads:
        try:
            payloads.append(load_daily_payload(file.getvalue()))
        except Exception as exc:
            load_errors.append(f"{file.name}: {exc}")
    if load_errors:
        st.error("Some files could not be loaded.")
        for err in load_errors:
            st.write(f"- {err}")
        st.stop()

    payloads, collection_errors = validate_payload_collection(payloads)
    if collection_errors:
        st.error("The uploaded daily files cannot be combined yet.")
        for err in collection_errors:
            st.write(f"- {err}")
        st.stop()

    product_name = payloads[0]["product_name"]
    all_dates = [pd.Timestamp(payload["date"]) for payload in payloads]
    min_date, max_date = min(all_dates).date(), max(all_dates).date()

    c1, c2 = st.columns(2)
    period = c1.selectbox("Report version", ["Weekly", "Monthly", "Yearly"])
    anchor = c2.date_input("Report date", value=max_date, min_value=min_date, max_value=max_date)

    selected = filter_period_payloads(payloads, period, anchor)
    if not selected:
        st.warning(f"No uploaded daily files fall inside the selected {period.lower()} period.")
        st.stop()

    df = payloads_to_dataframe(selected)
    metrics = aggregate_dataframe(df)
    start = df["Date"].min().strftime("%Y-%m-%d")
    end = df["Date"].max().strftime("%Y-%m-%d")

    st.markdown(f"### {period} Report - {product_name}")
    st.caption(f"Included dates: {start} to {end} | {len(selected)} daily JSON file(s), sorted chronologically")

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Completed", f"{metrics['completed']:.0f}")
    k2.metric("Rejected", f"{metrics['rejected']:.0f}")
    k3.metric("Accepted", f"{metrics['accepted']:.0f}")
    k4.metric("Rejection rate", f"{metrics['rejection_rate']:.2f}%")
    k5.metric("Production days", metrics["days"])
    k6.metric("Machines", metrics["machines"])

    tab1, tab2, tab3, tab4 = st.tabs(["Chronological Production", "Machine Performance", "Period Summary", "Generate PDF"])
    with tab1:
        daily = metrics["daily"].copy()
        if not daily.empty:
            chart = daily.copy()
            chart["Date"] = chart["Date"].dt.strftime("%Y-%m-%d")
            st.bar_chart(chart.set_index("Date")[["Accepted Quantity", "Rejected Quantity"]], use_container_width=True)
        display_df = df.copy()
        display_df["Date"] = display_df["Date"].dt.strftime("%Y-%m-%d")
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    with tab2:
        if metrics["machine"].empty:
            st.info("No machine data available.")
        else:
            st.bar_chart(metrics["machine"].set_index("Machine Name")[["Accepted Quantity", "Rejected Quantity"]], use_container_width=True)
            st.dataframe(metrics["machine"], use_container_width=True, hide_index=True)
    with tab3:
        if period == "Yearly" and not metrics["monthly"].empty:
            st.markdown("#### Month-by-month production")
            st.bar_chart(metrics["monthly"].set_index("Month")[["Accepted Quantity", "Rejected Quantity"]], use_container_width=True)
            st.dataframe(metrics["monthly"], use_container_width=True, hide_index=True)
        else:
            st.markdown("#### Daily totals")
            day_display = metrics["daily"].copy()
            if not day_display.empty:
                day_display["Date"] = day_display["Date"].dt.strftime("%Y-%m-%d")
            st.dataframe(day_display, use_container_width=True, hide_index=True)
    with tab4:
        try:
            pdf = generate_period_pdf(df, product_name, period)
        except Exception as exc:
            st.error(f"Could not generate the PDF: {exc}")
        else:
            filename = f"Focused_Product_{safe_name(product_name)}_{period}_{start}_to_{end}.pdf"
            st.download_button("Download Report PDF", data=pdf, file_name=filename, mime="application/pdf", use_container_width=True)

elif workflow == "Legacy Excel Upload":
    st.subheader("Legacy Excel Report")
    st.caption("Use this for the older weekly Excel workbook format. New reporting should use Daily Entry + JSON files.")
    uploaded = st.file_uploader("Upload weekly production Excel workbook", type=["xlsx", "xlsm", "xls"])
    if uploaded is None:
        st.info("Upload a production workbook to begin.")
        st.stop()

    try:
        sheets = load_workbook(uploaded.getvalue())
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
    if not products:
        st.error("No Product Name values were found in the workbook.")
        st.stop()

    selected_product = st.selectbox("Focused product", products)
    filtered = filter_product(sheets, selected_product)
    metrics = summary_metrics(filtered)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Completed", f"{metrics['completed']:.0f}")
    c2.metric("Rejected", f"{metrics['rejected']:.0f}")
    c3.metric("Accepted", f"{metrics['accepted']:.0f}")
    c4.metric("Rejection rate", f"{metrics['rejection_rate']:.2f}%")

    daily = metrics["daily"]
    if not daily.empty:
        st.bar_chart(daily.set_index("Day")[["Completed Quantity", "Rejected Quantity"]], use_container_width=True)
        st.dataframe(daily, use_container_width=True, hide_index=True)

    machines = machine_totals(filtered)
    if not machines.empty:
        st.markdown("#### Machine performance")
        st.dataframe(machines, use_container_width=True, hide_index=True)

    products_summary = product_totals(filtered)
    if not products_summary.empty:
        st.markdown("#### Product summary")
        st.dataframe(products_summary, use_container_width=True, hide_index=True)

    legacy_df = legacy_sheets_to_dataframe(sheets, selected_product)
    if legacy_df.empty:
        st.warning("No matching focused-product rows were found for PDF generation.")
    else:
        try:
            pdf = generate_period_pdf(legacy_df, selected_product, "Weekly")
        except Exception as exc:
            st.error(f"The PDF could not be generated: {exc}")
        else:
            st.download_button(
                "Download Focused Product Report PDF",
                data=pdf,
                file_name=f"Focused_Product_Report_{safe_name(selected_product)}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

st.divider()
st.caption("Recommended workflow: enter one focused product each day, download the dated JSON, then upload those files later to build weekly, monthly or yearly reports.")
