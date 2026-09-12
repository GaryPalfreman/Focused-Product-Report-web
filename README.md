# Focused Product Report Web

Streamlit web conversion of the original Excel-driven weekly cone production report generator, renamed throughout as **Focused Product Report**.

## Workflow

1. Upload the weekly production Excel workbook.
2. Choose either **All products** or **One focused product**.
3. Review daily production, machine totals, and product totals in the browser.
4. Generate and download the finished PDF report.

## Expected workbook structure

The application keeps the original reporting model:

- Monday
- Tuesday
- Wednesday
- Thursday
- Friday
- Saturday
- Daily And Weekly Total

Day sheets should contain the original production columns including:

- Machine Name
- Manufacturing Order
- Product Name
- Operation Number
- Completed Quantity

If present, Rejected Quantity is also used for summary metrics.

## Improvements over the desktop script

- No hard-coded Mac file paths
- Browser-based Excel upload
- Browser PDF download
- Product-specific filtering
- Live KPI summary
- Daily production preview
- Machine performance summary
- Product summary
- Cleaner in-memory PDF generation
- All Cone Report terminology renamed to Focused Product Report

## Privacy / storage

The app does not deliberately persist uploaded workbook or report data. Files are processed in the active Streamlit session and the generated PDF is downloaded to the user's computer.

Because the public app is hosted by Streamlit, uploaded workbooks are transmitted to the hosted Streamlit process for temporary processing. For information that must never leave the local computer, run the app locally instead.

## Streamlit Community Cloud

- Repository: `GaryPalfreman/Focused-Product-Report-web`
- Branch: `main`
- Main file: `app.py`
