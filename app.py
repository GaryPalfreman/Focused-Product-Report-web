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

ENTRY_COLUMNS = [
    "Machine Name",
    "Manufacturing Order",
    "Operation Number",
    "Completed Quantity",
    "Rejected Quantity",
]


def blank_entry_table():
    return pd.DataFrame([
        {
            "Machine Name": "",
            "Manufacturing Order": "",
            "Operation Number": "",
            "Completed Quantity": 0,
            "Rejected Quantity": 0,
        }
    ], columns=ENTRY_COLUMNS)


def safe_name(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text.strip()) or "focused_product"


def legacy_sheets_to_dataframe(sheets: dict[str, pd.DataFrame], product_name: str) -> pd.DataFrame:
    """Convert the older Monday-Saturday workbook structure into the new focused-product dataframe."""
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
        source["Completed Quantity"] = pd.to_numeric(
            source.get("Completed Quantity", 0), errors="coerce"
        ).fillna(0)

        if "Rejected Quantity" in source.columns:
            source["Rejected Quantity"] = pd.to_numeric(
                source["Rejected Quantity"], errors="coerce"
            ).fillna(0)
        else:
            source["Rejected Quantity"] = 0.0

        source["Accepted Quantity"] = source["Completed Quantity"] - source["Rejected Quantity"]
        frames.append(source[[
            "Date",
            "Machine Name",
            "Manufacturing Order",
            "Product Name",
            "Operation Number",
            "Completed Quantity",
            "Rejected Quantity",
            "Accepted Quantity",
        ]])

    if not frames:
        return pd.DataFrame(columns=[
            "Date",
            "Machine Name",
            "Manufacturing Order",
            "Product Name",
            "Operation Number",
            "Completed Quantity",
            "Rejected Quantity",
            "Accepted Quantity",
        ])

    return pd.concat(frames, ignore_index=True).sort_values(
        ["Date", "Manufacturing Order", "Operation Number"], kind="stable"
    ).reset_index(drop=True)


if "daily_editor" not in st.session_state:
    st.session_state.daily_editor = blank_entry_table()
if "daily_product" not in st.session_state:
    st.session_state.daily_product = ""
if "daily_date" not in st.session_state:
    st.session_state.daily_date = date.today()

st.title("Focused Product Report")
st.caption(
    "Enter focused-product production directly, save each day locally as JSON, reload daily files later, and generate weekly, monthly or yearly reports. Excel upload remains available for older report files."
)

with st.sidebar:
    st.header("Focused Product Reporting")
    workflow = st.radio("Workflow", ["Daily Entry", "Build Period Report", "Legacy Excel Upload"])
    st.caption(
        "The app does not deliberately persist report data. Use the JSON and PDF download buttons to keep your records on the computer you are using."
    )

if workflow == "Daily Entry":
    st.subheader("Daily Focused Product Entry")
    st.write("Create one JSON file for each production date. Each daily file is tied to one focused product.")

    uploaded_daily = st.file_uploader(
        "Load an existing daily JSON to continue/edit",
        type=["json"],
        key="edit_daily_json",
    )
    if uploaded_daily is not None:
        try:
            raw = uploaded_daily.getvalue()
            payload = load_daily_payload(raw)
        except Exception as exc:
            st.error(f"Could not load this daily file: {exc}")
        else:
            load_key = f"{uploaded_daily.name}:{len(raw)}"
            if st.session_state.get("loaded_daily_key") != load_key:
                rows = []
                for row in payload["records"]:
                    rows.append({
                        "Machine Name": row.get("Machine Name", ""),
                        "Manufacturing Order": row.get("Manufacturing Order", ""),
                        "Operation Number": row.get("Operation Number", ""),
                        "Completed Quantity": row.get("Completed Quantity", 0),
                        "Rejected Quantity": row.get("Rejected Quantity", 0),
                    })
                st.session_state.daily_editor = (
                    pd.DataFrame(rows, columns=ENTRY_COLUMNS) if rows else blank_entry_table()
                )
                st.session_state.daily_product = payload["product_name"]
                st.session_state.daily_date = pd.Timestamp(payload["date"]).date()
                st.session_state.loaded_daily_key = load_key
                st.rerun()

    c1, c2 = st.columns(2)
    report_date = c1.date_input(
        "Production date",
        value=st.session_state.daily_date,
        key="focused_daily_date_input",
    )
    product_name = c2.text_input(
        "Focused product",
        value=st.session_state.daily_product,
        placeholder="e.g. AT7701",
        key="focused_daily_product_input",
    )

    st.session_state.daily_date = report_date
    st.session_state.daily_product = product_name

    edited = st.data_editor(
        st.session_state.daily_editor,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "Machine Name": st.column_config.TextColumn(required=True),
            "Manufacturing Order": st.column_config.TextColumn(required=True),
            "Operation Number": st.column_config.TextColumn(required=True),
            "Completed Quantity": st.column_config.NumberColumn(min_value=0.0, step=1.0, required=True),
            "Rejected Quantity": st.column_config.NumberColumn(min_value=0.0, step=1.0, required=True),
        },
        key="daily_data_editor",
    )
    st.session_state.daily_editor = edited

    preview = edited.copy()
    if not preview.empty:
        preview["Completed Quantity"] = pd.to_numeric(
            preview["Completed Quantity"], errors="coerce"
        ).fillna(0)
        preview["Rejected Quantity"] = pd.to_numeric(
            preview["Rejected Quantity"], errors="coerce"
        ).fillna(0)
        preview["Accepted Quantity"] = preview["Completed Quantity"] - preview["Rejected Quantity"]
        total_completed = float(preview["Completed Quantity"].sum())
        total_rejected = float(preview["Rejected Quantity"].sum())
        total_accepted = total_completed - total_rejected
        rejection_rate = (total_rejected / total_completed * 100) if total_completed else 0.0
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Completed", f"{total_completed:.0f}")
        k2.metric("Rejected", f"{total_rejected:.0f}")
        k3.metric("Accepted", f"{total_accepted:.0f}")
        k4.metric("Rejection rate", f"{rejection_rate:.2f}%")

    invalid = False
    if not product_name.strip():
        st.warning("Enter the focused product name before downloading the daily file.")
        invalid = True

    clean_rows = []
    for _, row in edited.iterrows():
        machine = str(row.get("Machine Name", "")).strip()
        order = str(row.get("Manufacturing Order", "")).strip()
        operation = str(row.get("Operation Number", "")).strip()
        completed_value = pd.to_numeric(row.get("Completed Quantity", 0), errors="coerce")
        rejected_value = pd.to_numeric(row.get("Rejected Quantity", 0), errors="coerce")
        completed = 0.0 if pd.isna(completed_value) else float(completed_value)
        rejected = 0.0 if pd.isna(rejected_value) else float(rejected_value)

        if not machine and not order and not operation and completed == 0 and rejected == 0:
            continue
        if rejected > completed:
            st.error("Rejected Quantity cannot be greater than Completed Quantity.")
            invalid = True

        clean_rows.append({
            "Machine Name": machine,
            "Manufacturing Order": order,
            "Operation Number": operation,
            "Completed Quantity": completed,
            "Rejected Quantity": rejected,
        })

    if clean_rows and not invalid:
        payload = make_daily_payload(report_date, product_name, clean_rows)
        filename = f"Focused_Product_{safe_name(product_name)}_{report_date.isoformat()}.json"
        st.download_button(
            "Download Daily JSON",
            data=daily_payload_bytes(payload),
            file_name=filename,
            mime="application/json",
            use_container_width=True,
        )
        st.caption(
            "Keep these daily JSON files on your computer. Their internal production dates are used to build chronological weekly, monthly and yearly reports."
        )
    elif not clean_rows:
        st.info("Enter at least one production record to create the daily JSON file.")

elif workflow == "Build Period Report":
    st.subheader("Build Weekly, Monthly or Yearly Focused Product Report")
    st.write(
        "Upload the daily JSON files you previously downloaded. The app sorts them chronologically by the production date stored inside each file."
    )

    uploads = st.file_uploader(
        "Upload daily Focused Product JSON files",
        type=["json"],
        accept_multiple_files=True,
        key="period_jsons",
    )
    if not uploads:
        st.info("Upload one or more daily JSON files to begin.")
        st.stop()

    payloads = []
    load_errors = []
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
    anchor = c2.date_input(
        "Report date",
        value=max_date,
        min_value=min_date,
        max_value=max_date,
    )

    selected = filter_period_payloads(payloads, period, anchor)
    if not selected:
        st.warning(f"No uploaded daily files fall inside the selected {period.lower()} period.")
        st.stop()

    df = payloads_to_dataframe(selected)
    metrics = aggregate_dataframe(df)
    start = df["Date"].min().strftime("%Y-%m-%d")
    end = df["Date"].max().strftime("%Y-%m-%d")

    st.markdown(f"### {period} Report - {product_name}")
    st.caption(
        f"Included dates: {start} to {end} | {len(selected)} daily JSON file(s), sorted chronologically"
    )

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Completed", f"{metrics['completed']:.0f}")
    k2.metric("Rejected", f"{metrics['rejected']:.0f}")
    k3.metric("Accepted", f"{metrics['accepted']:.0f}")
    k4.metric("Rejection rate", f"{metrics['rejection_rate']:.2f}%")
    k5.metric("Production days", metrics["days"])
    k6.metric("Machines", metrics["machines"])

    tab1, tab2, tab3, tab4 = st.tabs([
        "Chronological Production",
        "Machine Performance",
        "Period Summary",
        "Generate PDF",
    ])

    with tab1:
        daily = metrics["daily"].copy()
        if not daily.empty:
            chart = daily.copy()
            chart["Date"] = chart["Date"].dt.strftime("%Y-%m-%d")
            st.bar_chart(
                chart.set_index("Date")[["Accepted Quantity", "Rejected Quantity"]],
                use_container_width=True,
            )
        display_df = df.copy()
        display_df["Date"] = display_df["Date"].dt.strftime("%Y-%m-%d")
        st.dataframe(display_df, use_container_width=True, hide_index=True)

    with tab2:
        if metrics["machine"].empty:
            st.info("No machine data available.")
        else:
            st.bar_chart(
                metrics["machine"].set_index("Machine Name")[["Accepted Quantity", "Rejected Quantity"]],
                use_container_width=True,
            )
            st.dataframe(metrics["machine"], use_container_width=True, hide_index=True)

    with tab3:
        if period == "Yearly" and not metrics["monthly"].empty:
            st.markdown("#### Month-by-month production")
            st.bar_chart(
                metrics["monthly"].set_index("Month")[["Accepted Quantity", "Rejected Quantity"]],
                use_container_width=True,
            )
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
            st.download_button(
                "Download Report PDF",
                data=pdf,
                file_name=filename,
                mime="application/pdf",
                use_container_width=True,
            )

elif workflow == "Legacy Excel Upload":
    st.subheader("Legacy Excel Report")
    st.caption(
        "Use this for the older weekly Excel workbook format. New reporting should use Daily Entry + JSON files."
    )
    uploaded = st.file_uploader(
        "Upload weekly production Excel workbook",
        type=["xlsx", "xlsm", "xls"],
    )
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

    cols = st.columns(4)
    cols[0].metric("Completed", f"{metrics['completed']:.0f}")
    cols[1].metric("Rejected", f"{metrics['rejected']:.0f}")
    cols[2].metric("Accepted", f"{metrics['accepted']:.0f}")
    cols[3].metric("Rejection rate", f"{metrics['rejection_rate']:.2f}%")

    daily = metrics["daily"]
    if not daily.empty:
        st.bar_chart(
            daily.set_index("Day")[["Completed Quantity", "Rejected Quantity"]],
            use_container_width=True,
        )
        st.dataframe(daily, use_container_width=True, hide_index=True)

    machines = machine_totals(filtered)
    if not machines.empty:
        st.markdown("#### Machine performance")
        st.dataframe(machines, use_container_width=True, hide_index=True)

    product_summary = product_totals(filtered)
    if not product_summary.empty:
        st.markdown("#### Product summary")
        st.dataframe(product_summary, use_container_width=True, hide_index=True)

    legacy_df = legacy_sheets_to_dataframe(sheets, selected_product)
    if legacy_df.empty:
        st.warning("No focused-product rows were available to generate the PDF.")
    elif legacy_df["Date"].isna().all():
        st.warning(
            "The selected workbook rows do not contain valid dates, so the report can be reviewed above but a chronological PDF cannot be generated."
        )
    else:
        legacy_df = legacy_df.dropna(subset=["Date"]).reset_index(drop=True)
        try:
            pdf = generate_period_pdf(legacy_df, selected_product, "Weekly")
        except Exception as exc:
            st.error(f"The PDF could not be generated: {exc}")
        else:
            start = legacy_df["Date"].min().strftime("%Y-%m-%d")
            end = legacy_df["Date"].max().strftime("%Y-%m-%d")
            st.download_button(
                "Download Focused Product Report PDF",
                data=pdf,
                file_name=(
                    f"Focused_Product_{safe_name(selected_product)}_Weekly_{start}_to_{end}.pdf"
                ),
                mime="application/pdf",
                use_container_width=True,
            )

st.divider()
st.caption(
    "Recommended workflow: enter one focused product each day -> download the dated JSON -> later upload those JSON files to generate weekly, monthly or yearly reports. Uploaded data is processed by the hosted Streamlit app for the active session but is not deliberately persisted by this application."
)
