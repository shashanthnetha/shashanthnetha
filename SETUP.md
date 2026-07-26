# Setup & Maintenance Guide

This repository contains a complete, self-hosted, handcrafted GitHub Profile setup for **shashanthnetha**.

All stats are generated directly via Python standard library and GitHub's GraphQL API without reliance on third-party stat cards, external Vercel deployments, or external iframe services.

---

## 📁 Repository Structure

```
shashanthnetha/
├── README.md              ← Main handcrafted developer profile page
├── SETUP.md               ← One-time setup & maintenance instructions
├── LICENSE                ← MIT License
├── .gitignore             ← Python & macOS ignore rules
├── requirements.txt       ← Dependency declaration (stdlib only)
├── assets/
│   ├── hero.svg           ← Animated terminal hero banner (static)
│   └── dashboard.svg      ← Self-hosted neofetch stats card (regenerated daily)
├── scripts/
│   └── build_dashboard.py ← Python engine for GitHub GraphQL data fetching & SVG generation
└── .github/
    └── workflows/
        └── dashboard.yml   ← GitHub Actions workflow to regenerate dashboard.svg
```

---

## 🚀 One-Time Setup (2 Minutes)

1. **Enable Action Write Permissions**:
   - Go to your repository on GitHub: **Settings → Actions → General → Workflow permissions**.
   - Select **Read and write permissions**.
   - Click **Save**.

2. **Push to Your Special Profile Repository**:
   - Copy all repository files into your special GitHub profile repository (`shashanthnetha/shashanthnetha`).
   - Push to `main`:
     ```bash
     git add .
     git commit -m "feat: setup handcrafted profile repository"
     git push origin main
     ```

3. **Verify Execution**:
   - Pushing to `main` triggers `.github/workflows/dashboard.yml`.
   - The workflow runs `scripts/build_dashboard.py shashanthnetha`, queries GitHub GraphQL API via the auto-injected `GITHUB_TOKEN`, and updates `assets/dashboard.svg`.
   - The workflow runs automatically **every day at 03:17 UTC**. You can also trigger it manually anytime under the **Actions** tab → **refresh live dashboard** → **Run workflow**.

---

## 💻 Local Testing & Customization

### Run Locally (Offline Seed Mode)
To test SVG generation locally without a token:
```bash
python3 scripts/build_dashboard.py shashanthnetha --offline
```

### Run Locally (Live GraphQL Mode)
To test with live GraphQL data locally:
```bash
GITHUB_TOKEN=your_personal_access_token python3 scripts/build_dashboard.py shashanthnetha
```

### Customizing Colors & Rows
- **Colors & Palette**: Edit constants (`BG`, `GREEN`, `TEXT`, `BLUE`, `GOLD`) at the top of `scripts/build_dashboard.py`.
- **Stat Rows**: Modify the `rows` list inside `render_svg()` in `scripts/build_dashboard.py`.
- **Hero Banner**: Edit `assets/hero.svg` directly in any text editor to adjust terminal sequence text or timings.
