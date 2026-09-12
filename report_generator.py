import hashlib
import io
import json
import zipfile
from datetime import datetime

import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

DAY_SHEETS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
REQUIRED_DAY_COLUMNS = ["Machine Name", "Manufacturing Order", "Product Name", "Operation Number", "Completed Quantity"]
DAILY_JSON_VERSION = 2


def load_workbook(file_bytes: bytes) -> dict[str, pd.DataFrame]:
    excel = pd.ExcelFile(io.BytesIO(file_bytes))
    return {sheet: pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet) for sheet in excel.sheet_names}


def validate_workbook(sheets: dict[str, pd.DataFrame]) -> list[str]:
    errors = []
    if "Daily And Weekly Total" not in sheets:
        errors.append("Missing required sheet: Daily And Weekly Total")
    for day in DAY_SHEETS:
        if day not in sheets or sheets[day].empty:
            continue
        missing = [c for c in REQUIRED_DAY_COLUMNS if c not in sheets[day].columns]
        if missing:
            errors.append(f"{day}: missing column(s): {', '.join(missing)}")
    return errors


def clean_day_data(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "Date" in out.columns:
        out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    for col in ["Completed Quantity", "Rejected Quantity", "Accepted Quantity", "Daily Target"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    if "Rejected Quantity" not in out.columns:
        out["Rejected Quantity"] = 0.0
    if "Accepted Quantity" not in out.columns and "Completed Quantity" in out.columns:
        out["Accepted Quantity"] = out["Completed Quantity"] - out["Rejected Quantity"]
    return out


def available_day_sheets(sheets: dict[str, pd.DataFrame]) -> list[str]:
    return [day for day in DAY_SHEETS if day in sheets and not sheets[day].empty]


def focused_products(sheets: dict[str, pd.DataFrame]) -> list[str]:
    products = set()
    for day in available_day_sheets(sheets):
        if "Product Name" in sheets[day].columns:
            products.update(str(v).strip() for v in sheets[day]["Product Name"].dropna() if str(v).strip())
    return sorted(products)


def filter_product(sheets: dict[str, pd.DataFrame], product: str | None) -> dict[str, pd.DataFrame]:
    result = {}
    for name, df in sheets.items():
        if name in DAY_SHEETS and product and "Product Name" in df.columns:
            result[name] = df[df["Product Name"].astype(str) == str(product)].copy()
        else:
            result[name] = df.copy()
    return result


def summary_metrics(sheets: dict[str, pd.DataFrame]) -> dict:
    frames = []
    for day in available_day_sheets(sheets):
        df = clean_day_data(sheets[day])
        if not df.empty:
            frames.append(df)
    if not frames:
        return aggregate_dataframe(pd.DataFrame())
    combined = pd.concat(frames, ignore_index=True)
    if "Date" not in combined.columns:
        combined["Date"] = pd.NaT
    return aggregate_dataframe(combined)


def machine_totals(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for day in available_day_sheets(sheets):
        df = clean_day_data(sheets[day])
        if "Machine Name" in df.columns:
            frames.append(df[["Machine Name", "Completed Quantity", "Rejected Quantity", "Accepted Quantity"]])
    if not frames:
        return pd.DataFrame(columns=["Machine Name", "Completed Quantity", "Rejected Quantity", "Accepted Quantity"])
    return pd.concat(frames, ignore_index=True).groupby("Machine Name", as_index=False).sum(numeric_only=True).sort_values("Accepted Quantity", ascending=False)


def product_totals(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for day in available_day_sheets(sheets):
        df = clean_day_data(sheets[day])
        if "Product Name" in df.columns:
            frames.append(df[["Product Name", "Completed Quantity", "Rejected Quantity", "Accepted Quantity"]])
    if not frames:
        return pd.DataFrame(columns=["Product Name", "Completed Quantity", "Rejected Quantity", "Accepted Quantity"])
    return pd.concat(frames, ignore_index=True).groupby("Product Name", as_index=False).sum(numeric_only=True).sort_values("Accepted Quantity", ascending=False)


def make_daily_payload(report_date, product_name: str, records: list[dict], daily_target: float = 0, entered_by: str = "") -> dict:
    date_text = pd.to_datetime(report_date).strftime("%Y-%m-%d")
    clean_records = []
    for row in records:
        completed = float(row.get("Completed Quantity", 0) or 0)
        rejected = float(row.get("Rejected Quantity", 0) or 0)
        clean_records.append({
            "Machine Name": str(row.get("Machine Name", "")).strip(),
            "Manufacturing Order": str(row.get("Manufacturing Order", "")).strip(),
            "Product Name": product_name.strip(),
            "Operation Number": str(row.get("Operation Number", "")).strip(),
            "Completed Quantity": completed,
            "Rejected Quantity": rejected,
            "Accepted Quantity": completed - rejected,
            "Comments": str(row.get("Comments", "")).strip(),
            "Downtime Reason": str(row.get("Downtime Reason", "")).strip(),
            "Entered By": str(row.get("Entered By", entered_by)).strip(),
            "Entered At": str(row.get("Entered At", datetime.now().isoformat(timespec="seconds"))),
        })
    return {"schema": "focused-product-daily", "version": DAILY_JSON_VERSION, "date": date_text, "product_name": product_name.strip(), "daily_target": float(daily_target or 0), "entered_by": entered_by.strip(), "records": clean_records}


def daily_payload_bytes(payload: dict) -> bytes:
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def load_daily_payload(file_bytes: bytes) -> dict:
    payload = json.loads(file_bytes.decode("utf-8"))
    if payload.get("schema") != "focused-product-daily":
        raise ValueError("This is not a Focused Product daily JSON file.")
    if not payload.get("date") or not payload.get("product_name") or not isinstance(payload.get("records"), list):
        raise ValueError("Daily JSON is missing date, product_name, or records.")
    pd.to_datetime(payload["date"], format="%Y-%m-%d", errors="raise")
    payload.setdefault("daily_target", 0.0)
    payload.setdefault("entered_by", "")
    for row in payload["records"]:
        row.setdefault("Comments", "")
        row.setdefault("Downtime Reason", "")
        row.setdefault("Entered By", payload.get("entered_by", ""))
        row.setdefault("Entered At", "")
        completed = float(row.get("Completed Quantity", 0) or 0)
        rejected = float(row.get("Rejected Quantity", 0) or 0)
        row["Accepted Quantity"] = completed - rejected
    return payload


def payloads_to_dataframe(payloads: list[dict]) -> pd.DataFrame:
    rows = []
    for payload in sorted(payloads, key=lambda p: p["date"]):
        for record in payload["records"]:
            row = dict(record)
            row["Date"] = payload["date"]
            row["Product Name"] = payload["product_name"]
            row["Daily Target"] = float(payload.get("daily_target", 0) or 0)
            rows.append(row)
    cols = ["Date", "Machine Name", "Manufacturing Order", "Product Name", "Operation Number", "Completed Quantity", "Rejected Quantity", "Accepted Quantity", "Daily Target", "Comments", "Downtime Reason", "Entered By", "Entered At"]
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows)
    for col in cols:
        if col not in df.columns:
            df[col] = "" if col not in ["Completed Quantity", "Rejected Quantity", "Accepted Quantity", "Daily Target"] else 0
    for col in ["Completed Quantity", "Rejected Quantity", "Accepted Quantity", "Daily Target"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    return df[cols].sort_values(["Date", "Manufacturing Order", "Operation Number"], kind="stable").reset_index(drop=True)


def validate_payload_collection(payloads: list[dict]) -> tuple[list[dict], list[str]]:
    if not payloads:
        return [], []
    ordered = sorted(payloads, key=lambda p: p["date"])
    errors = []
    products = sorted({p["product_name"].strip() for p in ordered})
    if len(products) > 1:
        errors.append("Uploaded daily files contain more than one focused product: " + ", ".join(products))
    seen = set()
    for p in ordered:
        if p["date"] in seen:
            errors.append(f"Duplicate daily file date: {p['date']}")
        seen.add(p["date"])
    return ordered, errors


def filter_period_payloads(payloads: list[dict], period: str, anchor_date) -> list[dict]:
    anchor = pd.Timestamp(anchor_date)
    selected = []
    for payload in payloads:
        d = pd.Timestamp(payload["date"])
        include = False
        if period == "Weekly":
            include = d.to_period("W-SUN") == anchor.to_period("W-SUN")
        elif period == "Monthly":
            include = d.year == anchor.year and d.month == anchor.month
        elif period == "Yearly":
            include = d.year == anchor.year
        if include:
            selected.append(payload)
    return sorted(selected, key=lambda p: p["date"])


def previous_period_anchor(period: str, anchor_date):
    anchor = pd.Timestamp(anchor_date)
    if period == "Weekly":
        return (anchor - pd.Timedelta(days=7)).date()
    if period == "Monthly":
        return (anchor - pd.DateOffset(months=1)).date()
    return (anchor - pd.DateOffset(years=1)).date()


def expected_dates(period: str, anchor_date) -> list[pd.Timestamp]:
    anchor = pd.Timestamp(anchor_date).normalize()
    if period == "Weekly":
        start = anchor - pd.Timedelta(days=anchor.weekday()); end = start + pd.Timedelta(days=5)
    elif period == "Monthly":
        start = anchor.replace(day=1); end = start + pd.offsets.MonthEnd(0)
    else:
        start = pd.Timestamp(year=anchor.year, month=1, day=1); end = pd.Timestamp(year=anchor.year, month=12, day=31)
    return [d for d in pd.date_range(start, end, freq="D") if d.weekday() < 6]


def missing_expected_dates(payloads: list[dict], period: str, anchor_date) -> list[str]:
    present = {pd.Timestamp(p["date"]).normalize() for p in payloads}
    today = pd.Timestamp.today().normalize()
    return [d.strftime("%Y-%m-%d") for d in expected_dates(period, anchor_date) if d <= today and d not in present]


def aggregate_dataframe(df: pd.DataFrame) -> dict:
    if df.empty:
        empty = pd.DataFrame()
        return {"completed": 0.0, "rejected": 0.0, "accepted": 0.0, "rejection_rate": 0.0, "days": 0, "machines": 0, "orders": 0, "daily": empty, "machine": empty, "monthly": empty, "target": 0.0, "variance": 0.0, "attainment": 0.0, "best_day": None, "worst_day": None, "best_machine": None, "worst_machine": None}
    work = df.copy()
    for col in ["Completed Quantity", "Rejected Quantity", "Accepted Quantity", "Daily Target"]:
        if col not in work.columns: work[col] = 0.0
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0)
    completed = float(work["Completed Quantity"].sum()); rejected = float(work["Rejected Quantity"].sum())
    daily = work.groupby("Date", as_index=False)[["Completed Quantity", "Rejected Quantity", "Accepted Quantity"]].sum().sort_values("Date")
    daily = daily.merge(work.groupby("Date", as_index=False)["Daily Target"].max(), on="Date", how="left")
    daily["Variance"] = daily["Accepted Quantity"] - daily["Daily Target"]
    machine = work.groupby("Machine Name", as_index=False)[["Completed Quantity", "Rejected Quantity", "Accepted Quantity"]].sum().sort_values("Accepted Quantity", ascending=False)
    monthly_df = work.copy(); monthly_df["Month"] = monthly_df["Date"].dt.to_period("M").astype(str)
    monthly = monthly_df.groupby("Month", as_index=False)[["Completed Quantity", "Rejected Quantity", "Accepted Quantity"]].sum().sort_values("Month")
    target = float(daily["Daily Target"].sum()); accepted = completed - rejected; variance = accepted - target; attainment = accepted / target * 100 if target else 0.0
    best_day = None if daily.empty else daily.loc[daily["Accepted Quantity"].idxmax(), "Date"]; worst_day = None if daily.empty else daily.loc[daily["Accepted Quantity"].idxmin(), "Date"]
    best_machine = None if machine.empty else machine.iloc[0]["Machine Name"]; worst_machine = None if machine.empty else machine.iloc[-1]["Machine Name"]
    return {"completed": completed, "rejected": rejected, "accepted": accepted, "rejection_rate": (rejected / completed * 100) if completed else 0.0, "days": int(work["Date"].dt.date.nunique()), "machines": int(work["Machine Name"].nunique()), "orders": int(work["Manufacturing Order"].nunique()), "daily": daily, "machine": machine, "monthly": monthly, "target": target, "variance": variance, "attainment": attainment, "best_day": best_day, "worst_day": worst_day, "best_machine": best_machine, "worst_machine": worst_machine}


def comparison_summary(current_df: pd.DataFrame, previous_df: pd.DataFrame) -> dict:
    cur = aggregate_dataframe(current_df); prev = aggregate_dataframe(previous_df)
    return {"accepted_delta": cur["accepted"] - prev["accepted"], "accepted_pct": ((cur["accepted"] - prev["accepted"]) / prev["accepted"] * 100) if prev["accepted"] else None, "rejection_rate_delta": cur["rejection_rate"] - prev["rejection_rate"], "target_attainment_delta": cur["attainment"] - prev["attainment"], "previous": prev}


def _safe_name(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(text).strip()) or "focused_product"


def create_weekly_backup_zip(payloads: list[dict], product_name: str) -> bytes:
    ordered = sorted(payloads, key=lambda p: p["date"]); out = io.BytesIO(); manifest = []
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for payload in ordered:
            raw = daily_payload_bytes(payload); name = f"Focused_Product_{_safe_name(product_name)}_{payload['date']}.json"; zf.writestr(name, raw); manifest.append(f"{hashlib.sha256(raw).hexdigest()}  {name}")
        zf.writestr("ARCHIVE_INFO.txt", f"Focused Product weekly backup\nProduct: {product_name}\nFiles: {len(ordered)}\nCreated: {datetime.now().isoformat(timespec='seconds')}\n")
        zf.writestr("MANIFEST_SHA256.txt", "\n".join(manifest) + "\n")
    return out.getvalue()


def make_bar_chart(df: pd.DataFrame, x: str, y: str, title: str, rotate: int = 0, target_col: str | None = None) -> bytes:
    fig, ax = plt.subplots(figsize=(9, 5.2))
    if df.empty:
        ax.text(0.5, 0.5, "No data available", ha="center", va="center"); ax.axis("off")
    else:
        bars = ax.bar(df[x].astype(str), df[y].astype(float), label=y)
        if target_col and target_col in df.columns:
            ax.plot(df[x].astype(str), df[target_col].astype(float), marker="o", linewidth=1.6, label=target_col); ax.legend()
        ax.set_title(title); ax.set_xlabel(x); ax.set_ylabel(y); ax.tick_params(axis="x", rotation=rotate)
        for bar in bars:
            h = bar.get_height(); ax.annotate(f"{h:.0f}", (bar.get_x() + bar.get_width()/2, h), textcoords="offset points", xytext=(0, 3), ha="center", fontsize=8)
        fig.tight_layout()
    buffer = io.BytesIO(); fig.savefig(buffer, format="png", dpi=140, bbox_inches="tight"); plt.close(fig); return buffer.getvalue()


def dataframe_for_display(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]): out[col] = out[col].dt.strftime("%Y-%m-%d")
    return out.fillna("")


def _table_from_df(df: pd.DataFrame, max_rows: int = 120) -> Table:
    display = dataframe_for_display(df.head(max_rows)); data = [list(display.columns)] + [[str(v) for v in row] for row in display.itertuples(index=False, name=None)]
    if len(data) == 1: data = [["No data"]]
    table = Table(data, repeatRows=1, hAlign="CENTER")
    table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#24323d")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 6.2), ("GRID", (0,0), (-1,-1), 0.25, colors.grey), ("VALIGN", (0,0), (-1,-1), "TOP"), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f3f4f6")]), ("LEFTPADDING", (0,0), (-1,-1), 2.2), ("RIGHTPADDING", (0,0), (-1,-1), 2.2)])); return table


def generate_daily_confirmation_pdf(payload: dict) -> bytes:
    df = payloads_to_dataframe([payload]); metrics = aggregate_dataframe(df); buffer = io.BytesIO(); doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=12*mm, leftMargin=12*mm, topMargin=12*mm, bottomMargin=12*mm)
    styles = getSampleStyleSheet(); title = ParagraphStyle("title", parent=styles["Title"], alignment=TA_CENTER, fontSize=20)
    story = [Paragraph("Daily Focused Product Entry Confirmation", title), Spacer(1,5*mm), Paragraph(f"Product: {payload['product_name']}", styles["Heading2"]), Paragraph(f"Date: {payload['date']}", styles["Normal"]), Paragraph(f"Entered by: {payload.get('entered_by','') or 'Not specified'}", styles["Normal"]), Paragraph(f"Daily target: {float(payload.get('daily_target',0)):.0f}", styles["Normal"]), Spacer(1,5*mm)]
    summary = pd.DataFrame([["Completed", metrics["completed"]], ["Rejected", metrics["rejected"]], ["Accepted", metrics["accepted"]], ["Variance to Target", metrics["variance"]], ["Rejection Rate", f"{metrics['rejection_rate']:.2f}%"]], columns=["Metric", "Value"])
    story += [_table_from_df(summary), Spacer(1,6*mm), Paragraph("Production Records", styles["Heading2"]), _table_from_df(df.drop(columns=["Daily Target"], errors="ignore"), max_rows=100), Spacer(1,12*mm), Paragraph("Supervisor / Operator sign-off: ______________________________", styles["Normal"])]
    doc.build(story); return buffer.getvalue()


def generate_period_pdf(df: pd.DataFrame, product_name: str, period_label: str, previous_df: pd.DataFrame | None = None, missing_dates: list[str] | None = None) -> bytes:
    metrics = aggregate_dataframe(df); comparison = comparison_summary(df, previous_df) if previous_df is not None else None
    start = df["Date"].min().strftime("%Y-%m-%d") if not df.empty else "N/A"; end = df["Date"].max().strftime("%Y-%m-%d") if not df.empty else "N/A"
    buffer = io.BytesIO(); doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=10*mm, leftMargin=10*mm, topMargin=10*mm, bottomMargin=10*mm); styles = getSampleStyleSheet(); centered = ParagraphStyle("centered", parent=styles["Title"], alignment=TA_CENTER, fontSize=21, spaceAfter=12); heading = ParagraphStyle("heading", parent=styles["Heading2"], spaceBefore=6, spaceAfter=6)
    story = [Spacer(1,34*mm), Paragraph(f"{period_label} Focused Product Report", centered), Paragraph(product_name, ParagraphStyle("p", parent=styles["Heading2"], alignment=TA_CENTER)), Paragraph(f"{start} to {end}", ParagraphStyle("range", parent=styles["Normal"], alignment=TA_CENTER)), Spacer(1,8*mm), Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ParagraphStyle("gen", parent=styles["Normal"], alignment=TA_CENTER, fontSize=9)), PageBreak()]
    summary = pd.DataFrame([["Accepted", f"{metrics['accepted']:.0f}"], ["Target", f"{metrics['target']:.0f}"], ["Variance", f"{metrics['variance']:+.0f}"], ["Target Attainment", f"{metrics['attainment']:.1f}%"], ["Rejected", f"{metrics['rejected']:.0f}"], ["Rejection Rate", f"{metrics['rejection_rate']:.2f}%"], ["Best Day", metrics['best_day'].strftime('%Y-%m-%d') if metrics['best_day'] is not None else 'N/A'], ["Best Machine", metrics['best_machine'] or 'N/A']], columns=["Management KPI", "Result"])
    story += [Paragraph("Management Summary", heading), _table_from_df(summary), Spacer(1,5*mm)]
    if comparison:
        pct = "N/A" if comparison["accepted_pct"] is None else f"{comparison['accepted_pct']:+.1f}%"; comp = pd.DataFrame([["Accepted vs Previous", f"{comparison['accepted_delta']:+.0f} ({pct})"], ["Rejection Rate Change", f"{comparison['rejection_rate_delta']:+.2f} pp"], ["Target Attainment Change", f"{comparison['target_attainment_delta']:+.1f} pp"]], columns=["Comparison", "Result"]); story += [Paragraph("Period Comparison", heading), _table_from_df(comp), Spacer(1,5*mm)]
    if missing_dates: story += [Paragraph("Data Completeness", heading), Paragraph("Missing expected production dates: " + ", ".join(missing_dates[:30]) + (" ..." if len(missing_dates) > 30 else ""), styles["Normal"]), Spacer(1,5*mm)]
    if not metrics["daily"].empty:
        chart_df = metrics["daily"].copy(); chart_df["Date"] = chart_df["Date"].dt.strftime("%Y-%m-%d"); story += [Image(io.BytesIO(make_bar_chart(chart_df, "Date", "Accepted Quantity", "Accepted Production vs Target", 45, "Daily Target")), width=185*mm, height=105*mm), Spacer(1,3*mm), _table_from_df(chart_df), PageBreak()]
    if not metrics["machine"].empty: story += [Paragraph("Machine Performance", heading), Image(io.BytesIO(make_bar_chart(metrics["machine"], "Machine Name", "Accepted Quantity", "Accepted Quantity by Machine", 30)), width=185*mm, height=105*mm), Spacer(1,3*mm), _table_from_df(metrics["machine"]), PageBreak()]
    if period_label == "Yearly" and not metrics["monthly"].empty: story += [Paragraph("Month by Month", heading), Image(io.BytesIO(make_bar_chart(metrics["monthly"], "Month", "Accepted Quantity", "Monthly Accepted Production", 30)), width=185*mm, height=105*mm), Spacer(1,3*mm), _table_from_df(metrics["monthly"]), PageBreak()]
    story += [Paragraph("Production Records", heading), _table_from_df(df.drop(columns=["Daily Target"], errors="ignore"), max_rows=250)]; doc.build(story); return buffer.getvalue()


def generate_pdf(sheets: dict[str, pd.DataFrame], product_label: str | None = None) -> bytes:
    frames = []
    for day in available_day_sheets(sheets):
        df = clean_day_data(sheets[day])
        if not df.empty: frames.append(df)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["Date", "Machine Name", "Manufacturing Order", "Product Name", "Operation Number", "Completed Quantity", "Rejected Quantity", "Accepted Quantity", "Daily Target"])
    if "Daily Target" not in combined.columns: combined["Daily Target"] = 0.0
    return generate_period_pdf(combined, product_label or "All products", "Weekly")
