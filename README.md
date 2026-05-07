# Weekly G-Enterprise Report

This repo runs the G-Enterprise weekly macro report every Monday with GitHub Actions and publishes the latest `index.html` through GitHub Pages.

## Final website URL

After GitHub Pages is turned on, your report should publish here:

```text
https://g-enterprisegroup.github.io/Weekly-G-enterprise-Report/
```

Embed that public URL into Google Sites using **Insert → Embed → URL**.

## Repo structure

```text
Weekly-G-enterprise-Report/
├── scripts/
│   └── weekly_macro_report.py
├── requirements.txt
├── public/
│   └── .gitkeep
└── .github/
    └── workflows/
        └── weekly-macro.yml
```

## How to upload

1. Download this folder/zip.
2. Open your GitHub repo: `G-enterpriseGroup/Weekly-G-enterprise-Report`.
3. Upload everything exactly as structured.
4. Go to **Settings → Pages**.
5. Under **Build and deployment**, select **GitHub Actions**.
6. Go to **Actions → Weekly G-Enterprise Macro Report → Run workflow**.
7. Once it turns green, open the Pages URL above.
8. In Google Sites, embed the Pages URL, not the GitHub repo URL.

## Local test from your Mac

```bash
pip install -r requirements.txt
python scripts/weekly_macro_report.py
```

The GitHub-ready script writes output to `output/` and publishes the latest report to `public/index.html`.
