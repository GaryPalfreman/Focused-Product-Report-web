# Focused Product Report Web

Focused-product production reporting app built with Streamlit.

Live app: https://focused-pr0duct-report.streamlit.app

## Recommended workflow

The app no longer requires an Excel workbook for normal use.

1. Open **Daily Entry**.
2. Choose the production date and enter the single focused product being tracked.
3. Enter one or more production records for that product.
4. Download that day's JSON file to the local computer.
5. Repeat for each production day.
6. Open **Build Period Report** and upload the required daily JSON files.
7. Generate a **Weekly**, **Monthly**, or **Yearly** Focused Product Report PDF.

Daily files are sorted by the date stored inside the JSON, not by upload order or filename.

## Daily entry fields

Each production record contains:

- Machine Name
- Manufacturing Order
- Operation Number
- Completed Quantity
- Rejected Quantity
- Accepted Quantity, calculated automatically as Completed - Rejected

The production date and focused product name are stored once at daily-file level and applied to all records in that file.

## Daily JSON format

Daily downloads use the Focused Product JSON schema:

```json
{
  "schema": "focused-product-daily",
  "version": 1,
  "date": "2026-09-12",
  "product_name": "AT7701",
  "records": []
}
```

Existing daily JSON files can be uploaded back into **Daily Entry** and edited before downloading a replacement file.

## Period reports

### Weekly

Choose a date in the desired week. The app includes uploaded daily JSON files in that Monday-Sunday reporting week and produces chronological daily production, machine performance, KPIs and PDF output.

### Monthly

Choose a date in the required month. All uploaded daily files from that calendar month are combined chronologically.

### Yearly

Choose a date in the required year. All uploaded daily files from that calendar year are combined. The annual report also includes a month-by-month production summary.

The application rejects a combined set when uploaded files contain more than one focused product or duplicate production dates. This keeps each report dedicated to one product only.

## Report metrics

- Completed Quantity
- Rejected Quantity
- Accepted Quantity
- Rejection Rate
- Production Days
- Machines Used
- Manufacturing Orders
- Daily chronological totals
- Machine performance
- Monthly trend in yearly reports

## Legacy Excel support

The previous Excel workflow remains available under **Legacy Excel Upload** for older weekly workbooks. It reads the original Monday-Saturday and `Daily And Weekly Total` workbook structure, but the report itself remains focused on one selected product.

## Privacy / storage

The application does not deliberately persist daily JSON files, Excel files, or generated reports. Downloads are the intended method of keeping data on the user's computer.

Because the public app is hosted by Streamlit, anything uploaded to the public deployment is transmitted to the hosted Streamlit process for temporary processing. For information that must never leave the local computer, run the application locally.

## Streamlit Community Cloud

- Repository: `GaryPalfreman/Focused-Product-Report-web`
- Branch: `main`
- Main file: `app.py`
