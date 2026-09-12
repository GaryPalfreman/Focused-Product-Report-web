import io
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
REQUIRED_DAY_COLUMNS = [
    "Machine Name",
    "Manufacturing Order",
    "Product Name",
    "Operation Number",
    "Completed Quantity",
]


def load_workbook(file_bytes: bytes) -> dict[str, pd.DataFrame]:
    excel = pd.ExcelFile(io.BytesIO(file_bytes))
    return {sheet: pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet) for sheet in excel.sheet_names}


def validate_workbook(sheets: dict[str, pd.DataFrame]) -> list[str]:
    errors = []
    if "Daily And Weekly Total" not in sheets:
        errors.append("Missing required sheet: Daily And Weekly Total")

    for day in DAY_SHEETS:
        if day not in sheets:
            continue
        df = sheets[day]
        if df.empty:
            continue
        missing = [c for c in REQUIRED_DAY_COLUMNS if c not in df.columns]
        if missing:
            errors.append(f"{day}: missing column(s): {', '.join(missing)}")
    return errors


def clean_day_data(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "Date" in out.columns:
        out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    if "Completed Quantity" in out.columns:
        out["Completed Quantity"] = pd.to_numeric(out["Completed Quantity"], errors="coerce").fillna(0)
    if "Rejected Quantity" in out.columns:
        out["Rejected Quantity"] = pd.to_numeric(out["Rejected Quantity"], errors="coerce").fillna(0)
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
    machines = set()
    orders = set()
    products = set()
    daily = []

    for day in available_day_sheets(sheets):
        df = clean_day_data(sheets[day])
        completed = float(df.get("Completed Quantity", pd.Series(dtype=float)).sum())
        rejected = float(df.get("Rejected Quantity", pd.Series(dtype=float)).sum()) if "Rejected Quantity" in df.columns else 0.0
        total_completed += completed
        total_rejected += rejected
        if "Machine Name" in df.columns:
            machines.update(str(v) for v in df["Machine Name"].dropna())
        if "Manufacturing Order" in df.columns:
            orders.update(str(v) for v in df["Manufacturing Order"].dropna())
        if "Product Name" in df.columns:
            products.update(str(v) for v in df["Product Name"].dropna())
        daily.append({"Day": day, "Completed Quantity": completed, "Rejected Quantity": rejected})

    accepted = total_completed - total_rejected
    rejection_rate = (total_rejected / total_completed * 100) if total_completed else 0.0
    return {
        "completed": total_completed,
        "rejected": total_rejected,
        "accepted": accepted,
        "rejection_rate": rejection_rate,
        "machines": len(machines),
        "orders": len(orders),
        "products": len(products),
        "daily": pd.DataFrame(daily),
    }


def daily_totals_table(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return summary_metrics(sheets)["daily"]


def machine_totals(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for day in available_day_sheets(sheets):
        df = clean_day_data(sheets[day])
        if "Machine Name" in df.columns and "Completed Quantity" in df.columns:
            frames.append(df[["Machine Name", "Completed Quantity"]])
    if not frames:
        return pd.DataFrame(columns=["Machine Name", "Completed Quantity"])
    out = pd.concat(frames, ignore_index=True).groupby("Machine Name", as_index=False)["Completed Quantity"].sum()
    return out.sort_values("Completed Quantity", ascending=False)


def product_totals(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for day in available_day_sheets(sheets):
        df = clean_day_data(sheets[day])
        if "Product Name" in df.columns and "Completed Quantity" in df.columns:
            frames.append(df[["Product Name", "Completed Quantity"]])
    if not frames:
        return pd.DataFrame(columns=["Product Name", "Completed Quantity"])
    out = pd.concat(frames, ignore_index=True).groupby("Product Name", as_index=False)["Completed Quantity"].sum()
    return out.sort_values("Completed Quantity", ascending=False)


def make_bar_chart(df: pd.DataFrame, x: str, y: str, title: str, rotate: int = 0) -> bytes:
    fig, ax = plt.subplots(figsize=(9, 5.2))
    if df.empty:
        ax.text(0.5, 0.5, "No data available", ha="center", va="center")
        ax.axis("off")
    else:
        bars = ax.bar(df[x].astype(str), df[y].astype(float))
        ax.set_title(title)
        ax.set_xlabel(x)
        ax.set_ylabel(y)
        ax.tick_params(axis="x", rotation=rotate)
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f"{height:.0f}", (bar.get_x() + bar.get_width() / 2, height),
                        textcoords="offset points", xytext=(0, 3), ha="center", fontsize=8)
        fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    return buffer.getvalue()


def dataframe_for_display(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
    return out.fillna("")


def _table_from_df(df: pd.DataFrame, max_rows: int = 40) -> Table:
    display = dataframe_for_display(df.head(max_rows))
    data = [list(display.columns)] + [[str(v) for v in row] for row in display.itertuples(index=False, name=None)]
    if not data or len(data) == 1:
        data = [["No data"]]
    table = Table(data, repeatRows=1, hAlign="CENTER")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f3e46")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    return table


def generate_pdf(sheets: dict[str, pd.DataFrame], product_label: str | None = None) -> bytes:
    start_date, end_date = date_range(sheets)
    metrics = summary_metrics(sheets)
    title = "Focused Product Report"
    if product_label:
        title += f" - {product_label}"

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=10*mm, leftMargin=10*mm, topMargin=10*mm, bottomMargin=10*mm)
    styles = getSampleStyleSheet()
    centered = ParagraphStyle("centered", parent=styles["Title"], alignment=TA_CENTER, fontSize=20, spaceAfter=12)
    heading = ParagraphStyle("heading", parent=styles["Heading2"], spaceBefore=6, spaceAfter=6)

    story = [
        Spacer(1, 45*mm),
        Paragraph(title, centered),
        Paragraph(f"From: {start_date}", ParagraphStyle("c1", parent=styles["Normal"], alignment=TA_CENTER, fontSize=11)),
        Paragraph(f"To: {end_date}", ParagraphStyle("c2", parent=styles["Normal"], alignment=TA_CENTER, fontSize=11)),
        Spacer(1, 12*mm),
        Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ParagraphStyle("c3", parent=styles["Normal"], alignment=TA_CENTER, fontSize=9)),
        PageBreak(),
    ]

    summary_df = pd.DataFrame([
        ["Completed", f"{metrics['completed']:.0f}"],
        ["Rejected", f"{metrics['rejected']:.0f}"],
        ["Accepted", f"{metrics['accepted']:.0f}"],
        ["Rejection Rate", f"{metrics['rejection_rate']:.2f}%"],
        ["Machines", metrics["machines"]],
        ["Manufacturing Orders", metrics["orders"]],
    ], columns=["Metric", "Value"])
    story += [Paragraph("Weekly Summary", heading), _table_from_df(summary_df), Spacer(1, 6*mm)]

    daily = daily_totals_table(sheets)
    chart = make_bar_chart(daily, "Day", "Completed Quantity", "Daily Completed Quantity")
    story += [Image(io.BytesIO(chart), width=185*mm, height=105*mm), Spacer(1, 4*mm), _table_from_df(daily), PageBreak()]

    machines = machine_totals(sheets)
    if not machines.empty:
        chart = make_bar_chart(machines, "Machine Name", "Completed Quantity", "Completed Quantity by Machine", 25)
        story += [Paragraph("Machine Performance", heading), Image(io.BytesIO(chart), width=185*mm, height=105*mm), Spacer(1, 4*mm), _table_from_df(machines), PageBreak()]

    for day in available_day_sheets(sheets):
        df = clean_day_data(sheets[day])
        if df.empty:
            continue
        story.append(Paragraph(f"{day} Production Data", heading))
        if "Date" in df.columns and "Completed Quantity" in df.columns:
            chart_df = df.copy()
            chart_df["Date Label"] = chart_df["Date"].dt.strftime("%Y-%m-%d").fillna(day)
            grouped = chart_df.groupby("Date Label", as_index=False)["Completed Quantity"].sum()
            chart = make_bar_chart(grouped, "Date Label", "Completed Quantity", f"{day} Production", 25)
            story.append(Image(io.BytesIO(chart), width=185*mm, height=100*mm))
            story.append(Spacer(1, 3*mm))
        story.append(_table_from_df(df, max_rows=60))
        story.append(PageBreak())

    doc.build(story)
    return buffer.getvalue()
