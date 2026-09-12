# Focused Product Report Web

Focused-product production entry and management reporting app built with Streamlit.

Live app: https://focused-pr0duct-report.streamlit.app

## Main workflow

1. Open **Daily Entry**.
2. Set production date, focused product, daily target and entered-by name/initials.
3. Add production records using the form interface.
4. Download the dated JSON file and, when required, the print-friendly Daily Confirmation PDF.
5. Repeat for each production day.
6. Open **Build Period Report** and upload the relevant daily JSON files.
7. Generate **Weekly**, **Monthly**, or **Yearly** Focused Product management reports.

The app sorts daily files by the production date stored inside each JSON file rather than upload order or filename.

## Daily entry improvements

- Modern form-style entry rather than spreadsheet-style editing
- Recent machine and operation values remembered for the active browser session
- Quick **Duplicate Last Record** action
- Daily production target and live variance / attainment
- Completed, Rejected and automatically calculated Accepted quantities
- Comments / issues field
- Downtime reason field
- Entered-by traceability
- Entry timestamps
- Edit / remove controls for existing records
- Existing JSON files can be loaded back into Daily Entry and corrected
- Print-friendly daily confirmation PDF with sign-off line

## Daily JSON schema

Current files use schema version 2 while the loader remains compatible with older version-1 files.

```json
{
  "schema": "focused-product-daily",
  "version": 2,
  "date": "2026-09-12",
  "product_name": "AT7701",
  "daily_target": 250,
  "entered_by": "GP",
  "records": []
}
```

## Weekly / Monthly / Yearly reports

Period reports include:

- Completed, Rejected and Accepted production
- Daily and period production targets
- Variance to target
- Target attainment percentage
- Rejection rate
- Missing expected production-day warnings
- Chronological production vs target chart
- Previous-week / previous-month / previous-year comparison when the required JSON files are uploaded
- Best and lowest-output day
- Top and lowest-output machine
- Machine performance tables and charts
- Month-by-month yearly view
- Management summary page in the generated PDF
- Production record detail including comments, downtime and traceability fields

## Weekly backup package

Weekly reports can also produce a ZIP backup containing:

- All included daily JSON files
- `ARCHIVE_INFO.txt`
- `MANIFEST_SHA256.txt`

The SHA-256 manifest can be used to verify that archived JSON files have not changed since the backup package was created.

## Legacy Excel support

The previous Excel workflow remains under **Legacy Excel Upload** for older Monday-Saturday workbooks. It remains focused on one selected product.

## Privacy / storage

The application does not deliberately persist uploaded production files or generated reports. JSON, PDF and ZIP downloads are the intended persistence method.

Because the public app is hosted by Streamlit, uploaded files are transmitted to the hosted Streamlit process for temporary processing. For information that must never leave the local computer, run the application locally.

## Streamlit Community Cloud

- Repository: `GaryPalfreman/Focused-Product-Report-web`
- Branch: `main`
- Main file: `app.py`
