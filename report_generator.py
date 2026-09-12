import io
import json
from datetime import datetime

import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# Streamlit deployment sync: app.py and this report engine are maintained together.

DAY_SHEETS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
REQUIRED_DAY_COLUMNS = ["Machine Name", "Manufacturing Order", "Product Name", "Operation Number", "Completed Quantity"]
DAILY_JSON_VERSION = 1


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
    for col in ["Completed Quantity", "Rejected Quantity", "Accepted Quantity"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    if "Rejected Quantity" not in out.columns:
        out["Rejected Quantity"] = 0
    if "Accepted Quantity" not in out.columns and "Completed Quantity" in out.columns:
        out["Accepted Quantity"] = out["Completed Quantity"] - out["Rejected Quantity"]
    return out


def available_day_sheets(sheets: dict[str, pd.DataFrame]) -> list[str]:
    return [day for day in DAY_SHEETS if day in sheets and not sheets[day].empty]


def date_range(sheets: dict[str, pd.DataFrame]) -> tuple[str, str]:
    dates = []
    for day in available_day_sheets(sheets):
        df = clean_day_data(sheets[day])
        if "Date" in df.columns:
            dates.extend(df["Date"].dropna().tolist())
    if not dates:
        return "N/A", "N/A"
    return min(dates).strftime("%Y-%m-%d"), max(dates).strftime("%Y-%m-%d")


def focused_products(sheets: dict[str, pd.DataFrame]) -> list[str]:
    products = set()
    for day in available_day_sheets(sheets):
        df = sheets[day]
        if "Product Name" in df.columns:
            products.update(str(v).strip() for v in df["Product Name"].dropna() if str(v).strip())
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
    total_completed = 0.0
    total_rejected = 0.0
    machines, orders, products = set(), set(), set()
    daily = []
    for day in available_day_sheets(sheets):
        df = clean_day_data(sheets[day])
        completed = float(df.get("Completed Quantity", pd.Series(dtype=float)).sum())
        rejected = float(df.get("Rejected Quantity", pd.Series(dtype=float)).sum())
        total_completed += completed
        total_rejected += rejected
        machines.update(str(v) for v in df.get("Machine Name", pd.Series(dtype=str)).dropna())
        orders.update(str(v) for v in df.get("Manufacturing Order", pd.Series(dtype=str)).dropna())
        products.update(str(v) for v in df.get("Product Name", pd.Series(dtype=str)).dropna())
        daily.append({"Day": day, "Completed Quantity": completed, "Rejected Quantity": rejected})
    accepted = total_completed - total_rejected
    return {"completed": total_completed, "rejected": total_rejected, "accepted": accepted, "rejection_rate": (total_rejected / total_completed * 100) if total_completed else 0.0, "machines": len(machines), "orders": len(orders), "products": len(products), "daily": pd.DataFrame(daily)}


def daily_totals_table(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return summary_metrics(sheets)["daily"]


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


def make_daily_payload(report_date, product_name: str, records: list[dict]) -> dict:
    date_text = pd.to_datetime(report_date).strftime("%Y-%m-%d")
    clean_records = []
    for row in records:
        completed = float(row.get("Completed Quantity", 0) or 0)
        rejected = float(row.get("Rejected Quantity", 0) or 0)
        clean_records.append({"Machine Name": str(row.get("Machine Name", "")).strip(), "Manufacturing Order": str(row.get("Manufacturing Order", "")).strip(), "Product Name": product_name.strip(), "Operation Number": str(row.get("Operation Number", "")).strip(), "Completed Quantity": completed, "Rejected Quantity": rejected, "Accepted Quantity": completed - rejected})
    return {"schema": "focused-product-daily", "version": DAILY_JSON_VERSION, "date": date_text, "product_name": product_name.strip(), "records": clean_records}


def daily_payload_bytes(payload: dict) -> bytes:
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def load_daily_payload(file_bytes: bytes) -> dict:
    payload = json.loads(file_bytes.decode("utf-8"))
    if payload.get("schema") != "focused-product-daily":
        raise ValueError("This is not a Focused Product daily JSON file.")
    if not payload.get("date") or not payload.get("product_name") or not isinstance(payload.get("records"), list):
        raise ValueError("Daily JSON is missing date, product_name, or records.")
    pd.to_datetime(payload["date"], format="%Y-%m-%d", errors="raise")
    return payload


def payloads_to_dataframe(payloads: list[dict]) -> pd.DataFrame:
    rows = []
    for payload in sorted(payloads, key=lambda p: p["date"]):
        for record in payload["records"]:
            row = dict(record); row["Date"] = payload["date"]; row["Product Name"] = payload["product_name"]; rows.append(row)
    cols = ["Date", "Machine Name", "Manufacturing Order", "Product Name", "Operation Number", "Completed Quantity", "Rejected Quantity", "Accepted Quantity"]
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows)
    for col in ["Completed Quantity", "Rejected Quantity", "Accepted Quantity"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    return df[cols].sort_values(["Date", "Manufacturing Order", "Operation Number"], kind="stable").reset_index(drop=True)


def validate_payload_collection(payloads: list[dict]) -> tuple[list[dict], list[str]]:
    if not payloads: return [], []
    ordered = sorted(payloads, key=lambda p: p["date"]); errors = []
    products = sorted({p["product_name"].strip() for p in ordered})
    if len(products) > 1: errors.append("Uploaded daily files contain more than one focused product: " + ", ".join(products))
    seen = set()
    for p in ordered:
        if p["date"] in seen: errors.append(f"Duplicate daily file date: {p['date']}")
        seen.add(p["date"])
    return ordered, errors


def filter_period_payloads(payloads: list[dict], period: str, anchor_date) -> list[dict]:
    anchor = pd.Timestamp(anchor_date); selected = []
    for payload in payloads:
        d = pd.Timestamp(payload["date"]); include = False
        if period == "Weekly": include = d.to_period("W-SUN") == anchor.to_period("W-SUN")
        elif period == "Monthly": include = d.year == anchor.year and d.month == anchor.month
        elif period == "Yearly": include = d.year == anchor.year
        if include: selected.append(payload)
    return sorted(selected, key=lambda p: p["date"])


def aggregate_dataframe(df: pd.DataFrame) -> dict:
    if df.empty:
        empty = pd.DataFrame(); return {"completed": 0.0, "rejected": 0.0, "accepted": 0.0, "rejection_rate": 0.0, "days": 0, "machines": 0, "orders": 0, "daily": empty, "machine": empty, "monthly": empty}
    completed = float(df["Completed Quantity"].sum()); rejected = float(df["Rejected Quantity"].sum())
    daily = df.groupby("Date", as_index=False)[["Completed Quantity", "Rejected Quantity", "Accepted Quantity"]].sum().sort_values("Date")
    machine = df.groupby("Machine Name", as_index=False)[["Completed Quantity", "Rejected Quantity", "Accepted Quantity"]].sum().sort_values("Accepted Quantity", ascending=False)
    monthly_df = df.copy(); monthly_df["Month"] = monthly_df["Date"].dt.to_period("M").astype(str)
    monthly = monthly_df.groupby("Month", as_index=False)[["Completed Quantity", "Rejected Quantity", "Accepted Quantity"]].sum().sort_values("Month")
    return {"completed": completed, "rejected": rejected, "accepted": completed-rejected, "rejection_rate": (rejected/completed*100) if completed else 0.0, "days": int(df["Date"].dt.date.nunique()), "machines": int(df["Machine Name"].nunique()), "orders": int(df["Manufacturing Order"].nunique()), "daily": daily, "machine": machine, "monthly": monthly}


def make_bar_chart(df: pd.DataFrame, x: str, y: str, title: str, rotate: int = 0) -> bytes:
    fig, ax = plt.subplots(figsize=(9, 5.2))
    if df.empty: ax.text(0.5, 0.5, "No data available", ha="center", va="center"); ax.axis("off")
    else:
        bars = ax.bar(df[x].astype(str), df[y].astype(float)); ax.set_title(title); ax.set_xlabel(x); ax.set_ylabel(y); ax.tick_params(axis="x", rotation=rotate)
        for bar in bars:
            h = bar.get_height(); ax.annotate(f"{h:.0f}", (bar.get_x()+bar.get_width()/2, h), textcoords="offset points", xytext=(0,3), ha="center", fontsize=8)
        fig.tight_layout()
    buffer = io.BytesIO(); fig.savefig(buffer, format="png", dpi=140, bbox_inches="tight"); plt.close(fig); return buffer.getvalue()


def dataframe_for_display(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]): out[col] = out[col].dt.strftime("%Y-%m-%d")
    return out.fillna("")


def _table_from_df(df: pd.DataFrame, max_rows: int = 80) -> Table:
    display = dataframe_for_display(df.head(max_rows)); data = [list(display.columns)] + [[str(v) for v in row] for row in display.itertuples(index=False, name=None)]
    if len(data) == 1: data = [["No data"]]
    table = Table(data, repeatRows=1, hAlign="CENTER")
    table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2f3e46")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 6.3), ("GRID", (0,0), (-1,-1), 0.25, colors.grey), ("VALIGN", (0,0), (-1,-1), "TOP"), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f3f4f6")]), ("LEFTPADDING", (0,0), (-1,-1), 2.5), ("RIGHTPADDING", (0,0), (-1,-1), 2.5)])); return table


def generate_period_pdf(df: pd.DataFrame, product_name: str, period_label: str) -> bytes:
    metrics = aggregate_dataframe(df); start = df["Date"].min().strftime("%Y-%m-%d") if not df.empty else "N/A"; end = df["Date"].max().strftime("%Y-%m-%d") if not df.empty else "N/A"
    buffer = io.BytesIO(); doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=10*mm, leftMargin=10*mm, topMargin=10*mm, bottomMargin=10*mm); styles = getSampleStyleSheet()
    centered = ParagraphStyle("centered", parent=styles["Title"], alignment=TA_CENTER, fontSize=20, spaceAfter=12); heading = ParagraphStyle("heading", parent=styles["Heading2"], spaceBefore=6, spaceAfter=6)
    story = [Spacer(1,38*mm), Paragraph(f"{period_label} Focused Product Report", centered), Paragraph(product_name, ParagraphStyle("p", parent=styles["Heading2"], alignment=TA_CENTER)), Paragraph(f"From: {start}", ParagraphStyle("c1", parent=styles["Normal"], alignment=TA_CENTER)), Paragraph(f"To: {end}", ParagraphStyle("c2", parent=styles["Normal"], alignment=TA_CENTER)), Spacer(1,8*mm), Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ParagraphStyle("c3", parent=styles["Normal"], alignment=TA_CENTER, fontSize=9)), PageBreak()]
    summary = pd.DataFrame([["Completed",f"{metrics['completed']:.0f}"],["Rejected",f"{metrics['rejected']:.0f}"],["Accepted",f"{metrics['accepted']:.0f}"],["Rejection Rate",f"{metrics['rejection_rate']:.2f}%"],["Production Days",metrics["days"]],["Machines",metrics["machines"]],["Manufacturing Orders",metrics["orders"]]], columns=["Metric","Value"])
    story += [Paragraph("Period Summary", heading), _table_from_df(summary), Spacer(1,5*mm)]
    if not metrics["daily"].empty:
        chart_df=metrics["daily"].copy(); chart_df["Date"]=chart_df["Date"].dt.strftime("%Y-%m-%d"); story += [Image(io.BytesIO(make_bar_chart(chart_df,"Date","Accepted Quantity","Accepted Production by Date",45)), width=185*mm,height=105*mm), Spacer(1,3*mm), _table_from_df(chart_df), PageBreak()]
    if not metrics["machine"].empty: story += [Paragraph("Machine Performance",heading), Image(io.BytesIO(make_bar_chart(metrics["machine"],"Machine Name","Accepted Quantity","Accepted Quantity by Machine",30)),width=185*mm,height=105*mm), Spacer(1,3*mm), _table_from_df(metrics["machine"]), PageBreak()]
    if period_label == "Yearly" and not metrics["monthly"].empty: story += [Paragraph("Month by Month",heading), Image(io.BytesIO(make_bar_chart(metrics["monthly"],"Month","Accepted Quantity","Monthly Accepted Production",30)),width=185*mm,height=105*mm), Spacer(1,3*mm), _table_from_df(metrics["monthly"]), PageBreak()]
    story += [Paragraph("Production Records",heading), _table_from_df(df,max_rows=250)]; doc.build(story); return buffer.getvalue()


def generate_pdf(sheets: dict[str, pd.DataFrame], product_label: str | None = None) -> bytes:
    frames=[]
    for day in available_day_sheets(sheets):
        df=clean_day_data(sheets[day])
        if not df.empty: frames.append(df)
    if not frames: return generate_period_pdf(pd.DataFrame(columns=["Date","Machine Name","Manufacturing Order","Product Name","Operation Number","Completed Quantity","Rejected Quantity","Accepted Quantity"]), product_label or "All products", "Weekly")
    return generate_period_pdf(pd.concat(frames, ignore_index=True), product_label or "All products", "Weekly")
