from datetime import date, datetime

import pandas as pd
import streamlit as st

from report_generator import (
    aggregate_dataframe,
    available_day_sheets,
    comparison_summary,
    create_weekly_backup_zip,
    daily_payload_bytes,
    filter_period_payloads,
    focused_products,
    generate_daily_confirmation_pdf,
    generate_period_pdf,
    load_daily_payload,
    load_workbook,
    make_daily_payload,
    missing_expected_dates,
    payloads_to_dataframe,
    previous_period_anchor,
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
        source["Rejected Quantity"] = pd.to_numeric(source.get("Rejected Quantity", 0), errors="coerce").fillna(0) if "Rejected Quantity" in source.columns else 0.0
        source["Accepted Quantity"] = source["Completed Quantity"] - source["Rejected Quantity"]
        source["Daily Target"] = 0.0
        source["Comments"] = ""
        source["Downtime Reason"] = ""
        source["Entered By"] = ""
        source["Entered At"] = ""
        frames.append(source[["Date", "Machine Name", "Manufacturing Order", "Product Name", "Operation Number", "Completed Quantity", "Rejected Quantity", "Accepted Quantity", "Daily Target", "Comments", "Downtime Reason", "Entered By", "Entered At"]])
    if not frames:
        return pd.DataFrame(columns=["Date", "Machine Name", "Manufacturing Order", "Product Name", "Operation Number", "Completed Quantity", "Rejected Quantity", "Accepted Quantity", "Daily Target", "Comments", "Downtime Reason", "Entered By", "Entered At"])
    return pd.concat(frames, ignore_index=True).sort_values(["Date", "Manufacturing Order", "Operation Number"], kind="stable").reset_index(drop=True)


def reset_daily_entry():
    st.session_state.daily_records = []
    st.session_state.daily_product = ""
    st.session_state.daily_date = date.today()
    st.session_state.daily_target = 0.0
    st.session_state.entered_by = ""
    st.session_state.edit_record_index = None
    st.session_state.loaded_daily_key = None


def add_recent(name: str, value: str):
    value = str(value).strip()
    if not value:
        return
    items = st.session_state.setdefault(name, [])
    if value in items:
        items.remove(value)
    items.insert(0, value)
    del items[12:]


def recent_or_text(label: str, state_name: str, default: str, key_prefix: str, placeholder: str):
    options = st.session_state.get(state_name, [])
    mode = st.radio(f"{label} entry", ["Recent", "Type new"], horizontal=True, key=f"{key_prefix}_mode", label_visibility="collapsed") if options else "Type new"
    if mode == "Recent":
        index = options.index(default) if default in options else 0
        return st.selectbox(label, options, index=index, key=f"{key_prefix}_select")
    return st.text_input(label, value=default, placeholder=placeholder, key=f"{key_prefix}_text")


for key, default in {
    "daily_records": [],
    "daily_product": "",
    "daily_date": date.today(),
    "daily_target": 0.0,
    "entered_by": "",
    "edit_record_index": None,
    "recent_machines": [],
    "recent_operations": [],
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

st.markdown("""
<style>
.block-container {max-width: 1320px; padding-top: 1.3rem; padding-bottom: 3rem;}
div[data-testid="stMetric"] {border:1px solid rgba(128,128,128,.22); border-radius:14px; padding:12px 14px;}
.record-card {border:1px solid rgba(128,128,128,.25); border-radius:16px; padding:15px 17px; margin:8px 0 10px 0; background:rgba(128,128,128,.035);}
.section-note {opacity:.74; margin-top:-6px; margin-bottom:12px;}
.small-muted {opacity:.7; font-size:.9rem;}
</style>
""", unsafe_allow_html=True)

st.title("Focused Product Report")
st.caption("Modern daily focused-product entry, local JSON backups, and weekly/monthly/yearly management reporting.")

with st.sidebar:
    st.header("Focused Product Reporting")
    workflow = st.radio("Workflow", ["Daily Entry", "Build Period Report", "Legacy Excel Upload"])
    st.caption("Data is not deliberately persisted by the app. Download JSON/PDF/ZIP files to keep records locally.")

if workflow == "Daily Entry":
    st.subheader("Daily Focused Product Entry")
    st.markdown('<div class="section-note">Add one production record at a time. Recent machines and operations are remembered for this browser session.</div>', unsafe_allow_html=True)

    top1, top2 = st.columns([2, 1])
    with top1:
        uploaded_daily = st.file_uploader("Load an existing daily JSON", type=["json"], key="edit_daily_json", help="Continue or correct an existing daily file.")
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
                st.session_state.daily_records = [{
                    "Machine Name": row.get("Machine Name", ""),
                    "Manufacturing Order": row.get("Manufacturing Order", ""),
                    "Operation Number": row.get("Operation Number", ""),
                    "Completed Quantity": float(row.get("Completed Quantity", 0) or 0),
                    "Rejected Quantity": float(row.get("Rejected Quantity", 0) or 0),
                    "Comments": row.get("Comments", ""),
                    "Downtime Reason": row.get("Downtime Reason", ""),
                    "Entered By": row.get("Entered By", payload.get("entered_by", "")),
                    "Entered At": row.get("Entered At", ""),
                } for row in payload["records"]]
                st.session_state.daily_product = payload["product_name"]
                st.session_state.daily_date = pd.Timestamp(payload["date"]).date()
                st.session_state.daily_target = float(payload.get("daily_target", 0) or 0)
                st.session_state.entered_by = payload.get("entered_by", "")
                for row in st.session_state.daily_records:
                    add_recent("recent_machines", row["Machine Name"])
                    add_recent("recent_operations", row["Operation Number"])
                st.session_state.loaded_daily_key = load_key
                st.session_state.edit_record_index = None
                st.rerun()

    d1, d2, d3, d4 = st.columns([1.1, 1.4, 1, 1.2])
    report_date = d1.date_input("Production date", value=st.session_state.daily_date)
    product_name = d2.text_input("Focused product", value=st.session_state.daily_product, placeholder="e.g. AT7701")
    daily_target = d3.number_input("Daily target", min_value=0.0, step=1.0, value=float(st.session_state.daily_target))
    entered_by = d4.text_input("Entered by", value=st.session_state.entered_by, placeholder="Name / initials")
    st.session_state.daily_date = report_date
    st.session_state.daily_product = product_name
    st.session_state.daily_target = daily_target
    st.session_state.entered_by = entered_by

    records = st.session_state.daily_records
    if records:
        running_accepted = sum(float(r["Completed Quantity"]) - float(r["Rejected Quantity"]) for r in records)
        variance = running_accepted - daily_target
        k1, k2, k3 = st.columns(3)
        k1.metric("Accepted so far", f"{running_accepted:.0f}")
        k2.metric("Daily target", f"{daily_target:.0f}")
        k3.metric("Variance", f"{variance:+.0f}")
        if daily_target > 0:
            st.progress(min(running_accepted / daily_target, 1.0), text=f"Target attainment: {running_accepted / daily_target * 100:.1f}%")

    control1, control2 = st.columns([3, 1])
    with control2:
        st.write("")
        if st.button("Duplicate Last Record", use_container_width=True, disabled=not records):
            clone = dict(records[-1])
            clone["Entered At"] = datetime.now().isoformat(timespec="seconds")
            st.session_state.daily_records.append(clone)
            st.rerun()

    st.markdown("### Add production record")
    edit_index = st.session_state.edit_record_index
    edit_record = records[edit_index] if edit_index is not None and 0 <= edit_index < len(records) else None
    if edit_record is not None:
        st.info(f"Editing record {edit_index + 1}")
    defaults = edit_record or {"Machine Name":"", "Manufacturing Order":"", "Operation Number":"", "Completed Quantity":0.0, "Rejected Quantity":0.0, "Comments":"", "Downtime Reason":""}

    with st.form("production_record_form", clear_on_submit=edit_record is None):
        r1, r2, r3 = st.columns(3)
        with r1:
            machine = recent_or_text("Machine Name", "recent_machines", str(defaults["Machine Name"]), "machine", "e.g. Puma 2600")
        with r2:
            order = st.text_input("Manufacturing Order", value=str(defaults["Manufacturing Order"]), placeholder="e.g. MO12345")
        with r3:
            operation = recent_or_text("Operation Number", "recent_operations", str(defaults["Operation Number"]), "operation", "e.g. OP10")
        q1, q2, q3 = st.columns(3)
        completed = q1.number_input("Completed Quantity", min_value=0.0, step=1.0, value=float(defaults["Completed Quantity"]))
        rejected = q2.number_input("Rejected Quantity", min_value=0.0, step=1.0, value=float(defaults["Rejected Quantity"]))
        q3.metric("Accepted Quantity", f"{max(completed-rejected, 0):.0f}")
        x1, x2 = st.columns(2)
        comments = x1.text_area("Comments / issues", value=str(defaults.get("Comments", "")), placeholder="Quality issue, unusual event, notes...")
        downtime = x2.text_input("Downtime reason", value=str(defaults.get("Downtime Reason", "")), placeholder="Optional")
        submitted = st.form_submit_button("Save Changes" if edit_record is not None else "Add Record", use_container_width=True)

    if submitted:
        errors = []
        if not str(machine).strip():
            errors.append("Machine Name is required.")
        if not order.strip():
            errors.append("Manufacturing Order is required.")
        if not str(operation).strip():
            errors.append("Operation Number is required.")
        if rejected > completed:
            errors.append("Rejected Quantity cannot be greater than Completed Quantity.")
        if errors:
            for err in errors:
                st.error(err)
        else:
            record = {
                "Machine Name": str(machine).strip(),
                "Manufacturing Order": order.strip(),
                "Operation Number": str(operation).strip(),
                "Completed Quantity": float(completed),
                "Rejected Quantity": float(rejected),
                "Comments": comments.strip(),
                "Downtime Reason": downtime.strip(),
                "Entered By": entered_by.strip(),
                "Entered At": edit_record.get("Entered At") if edit_record and edit_record.get("Entered At") else datetime.now().isoformat(timespec="seconds"),
            }
            add_recent("recent_machines", record["Machine Name"])
            add_recent("recent_operations", record["Operation Number"])
            if edit_record is None:
                st.session_state.daily_records.append(record)
            else:
                st.session_state.daily_records[edit_index] = record
                st.session_state.edit_record_index = None
            st.rerun()

    if edit_record is not None and st.button("Cancel Edit", use_container_width=True):
        st.session_state.edit_record_index = None
        st.rerun()

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
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Completed", f"{total_completed:.0f}")
        k2.metric("Rejected", f"{total_rejected:.0f}")
        k3.metric("Accepted", f"{total_accepted:.0f}")
        k4.metric("Rejection rate", f"{(total_rejected/total_completed*100) if total_completed else 0:.2f}%")
        for i, row in enumerate(records):
            accepted_row = float(row["Completed Quantity"]) - float(row["Rejected Quantity"])
            note = row.get("Comments", "") or "No comments"
            down = row.get("Downtime Reason", "") or "None"
            st.markdown(f'''<div class="record-card"><b>Record {i+1}</b><br><b>Machine:</b> {row['Machine Name']} &nbsp; | &nbsp; <b>MO:</b> {row['Manufacturing Order']} &nbsp; | &nbsp; <b>Operation:</b> {row['Operation Number']}<br><b>Completed:</b> {row['Completed Quantity']:.0f} &nbsp; | &nbsp; <b>Rejected:</b> {row['Rejected Quantity']:.0f} &nbsp; | &nbsp; <b>Accepted:</b> {accepted_row:.0f}<br><span class="small-muted"><b>Comments:</b> {note} &nbsp; | &nbsp; <b>Downtime:</b> {down}<br><b>Entered by:</b> {row.get('Entered By','') or 'Not specified'} &nbsp; | &nbsp; <b>Timestamp:</b> {row.get('Entered At','')}</span></div>''', unsafe_allow_html=True)
            b1, b2 = st.columns(2)
            if b1.button("Edit", key=f"edit_{i}", use_container_width=True):
                st.session_state.edit_record_index = i
                st.rerun()
            if b2.button("Remove", key=f"remove_{i}", use_container_width=True):
                st.session_state.daily_records.pop(i)
                st.session_state.edit_record_index = None
                st.rerun()

        if not product_name.strip():
            st.warning("Enter the focused product name before downloading files.")
        else:
            payload = make_daily_payload(report_date, product_name, records, daily_target=daily_target, entered_by=entered_by)
            c1, c2 = st.columns(2)
            c1.download_button("Download Daily JSON", data=daily_payload_bytes(payload), file_name=f"Focused_Product_{safe_name(product_name)}_{report_date.isoformat()}.json", mime="application/json", use_container_width=True)
            c2.download_button("Print / Download Daily Confirmation PDF", data=generate_daily_confirmation_pdf(payload), file_name=f"Focused_Product_{safe_name(product_name)}_{report_date.isoformat()}_Confirmation.pdf", mime="application/pdf", use_container_width=True)

elif workflow == "Build Period Report":
    st.subheader("Build Weekly, Monthly or Yearly Focused Product Report")
    st.write("Upload daily JSON files. Upload a wider date range if you want automatic previous-period comparisons.")
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
    all_dates = [pd.Timestamp(p["date"]) for p in payloads]
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
    prev_anchor = previous_period_anchor(period, anchor)
    previous = filter_period_payloads(payloads, period, prev_anchor)
    previous_df = payloads_to_dataframe(previous) if previous else pd.DataFrame()
    comparison = comparison_summary(df, previous_df) if previous else None
    missing = missing_expected_dates(selected, period, anchor)

    st.markdown(f"### {period} Report - {product_name}")
    st.caption(f"Included dates: {start} to {end} | {len(selected)} daily file(s)")
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Accepted", f"{metrics['accepted']:.0f}")
    k2.metric("Target", f"{metrics['target']:.0f}")
    k3.metric("Variance", f"{metrics['variance']:+.0f}")
    k4.metric("Attainment", f"{metrics['attainment']:.1f}%")
    k5.metric("Rejected", f"{metrics['rejected']:.0f}")
    k6.metric("Rejection rate", f"{metrics['rejection_rate']:.2f}%")

    if missing:
        st.warning(f"Missing expected production dates ({len(missing)}): " + ", ".join(missing[:12]) + (" ..." if len(missing)>12 else ""))
    else:
        st.success("No expected production dates are missing from the selected period.")

    if comparison:
        pct = "N/A" if comparison["accepted_pct"] is None else f"{comparison['accepted_pct']:+.1f}%"
        c1, c2, c3 = st.columns(3)
        c1.metric("Accepted vs previous", f"{comparison['accepted_delta']:+.0f}", pct)
        c2.metric("Rejection-rate change", f"{comparison['rejection_rate_delta']:+.2f} pp")
        c3.metric("Attainment change", f"{comparison['target_attainment_delta']:+.1f} pp")
    else:
        st.info("Previous-period comparison is unavailable. Upload the preceding period's daily JSON files as well to enable it.")

    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Best day", metrics['best_day'].strftime('%Y-%m-%d') if metrics['best_day'] is not None else 'N/A')
    h2.metric("Lowest-output day", metrics['worst_day'].strftime('%Y-%m-%d') if metrics['worst_day'] is not None else 'N/A')
    h3.metric("Top machine", metrics['best_machine'] or 'N/A')
    h4.metric("Lowest-output machine", metrics['worst_machine'] or 'N/A')

    tab1, tab2, tab3, tab4 = st.tabs(["Chronological Production", "Machine Performance", "Management Summary", "Downloads"])
    with tab1:
        daily = metrics["daily"].copy()
        if not daily.empty:
            chart = daily.copy()
            chart["Date"] = chart["Date"].dt.strftime("%Y-%m-%d")
            st.line_chart(chart.set_index("Date")[["Accepted Quantity", "Daily Target"]], use_container_width=True)
            st.dataframe(chart, use_container_width=True, hide_index=True)
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
        st.markdown("#### Management highlights")
        st.write(f"**Accepted production:** {metrics['accepted']:.0f} against a target of {metrics['target']:.0f} ({metrics['variance']:+.0f}).")
        st.write(f"**Quality:** {metrics['rejection_rate']:.2f}% rejection rate across {metrics['days']} production day(s).")
        st.write(f"**Best day:** {metrics['best_day'].strftime('%Y-%m-%d') if metrics['best_day'] is not None else 'N/A'}; **Top machine:** {metrics['best_machine'] or 'N/A'}.")
        if period == "Yearly" and not metrics["monthly"].empty:
            st.markdown("#### Month-by-month")
            st.bar_chart(metrics["monthly"].set_index("Month")[["Accepted Quantity", "Rejected Quantity"]], use_container_width=True)
            st.dataframe(metrics["monthly"], use_container_width=True, hide_index=True)
    with tab4:
        pdf = generate_period_pdf(df, product_name, period, previous_df=previous_df if previous else None, missing_dates=missing)
        st.download_button("Download Management Report PDF", data=pdf, file_name=f"Focused_Product_{safe_name(product_name)}_{period}_{start}_to_{end}.pdf", mime="application/pdf", use_container_width=True)
        if period == "Weekly":
            zip_bytes = create_weekly_backup_zip(selected, product_name)
            st.download_button("Download Weekly JSON Backup Package", data=zip_bytes, file_name=f"Focused_Product_{safe_name(product_name)}_Weekly_Backup_{start}_to_{end}.zip", mime="application/zip", use_container_width=True)
            st.caption("ZIP includes the daily JSON files plus ARCHIVE_INFO.txt and SHA-256 manifest verification.")

else:
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
    legacy_df = legacy_sheets_to_dataframe(sheets, selected_product)
    if legacy_df.empty:
        st.warning("No records were found for that product.")
        st.stop()
    metrics = aggregate_dataframe(legacy_df)
    start = legacy_df["Date"].min().strftime("%Y-%m-%d") if legacy_df["Date"].notna().any() else "N/A"
    end = legacy_df["Date"].max().strftime("%Y-%m-%d") if legacy_df["Date"].notna().any() else "N/A"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Completed", f"{metrics['completed']:.0f}")
    c2.metric("Rejected", f"{metrics['rejected']:.0f}")
    c3.metric("Accepted", f"{metrics['accepted']:.0f}")
    c4.metric("Rejection rate", f"{metrics['rejection_rate']:.2f}%")
    st.dataframe(legacy_df, use_container_width=True, hide_index=True)
    st.download_button("Download Focused Product Report PDF", data=generate_period_pdf(legacy_df, selected_product, "Weekly"), file_name=f"Focused_Product_Report_{safe_name(selected_product)}_{start}_to_{end}.pdf", mime="application/pdf", use_container_width=True)

st.divider()
st.caption("Recommended workflow: enter one focused product each day -> save the dated JSON -> upload a date range later for weekly, monthly or yearly reporting and comparisons.")
