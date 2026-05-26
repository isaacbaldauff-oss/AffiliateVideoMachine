# AffiliateVideoMachine

A Streamlit dashboard for managing an affiliate short-form video production pipeline, from product research through AI video generation and official TikTok upload workflows.

## What v1 includes

- Product management with scoring.
- Configurable scoring weights in `config.yaml`.
- Local script generation with five reusable video angles per product.
- Compliance checks for risky claims and affiliate disclosures.
- SQLite storage in `data/affiliate_video_machine.db`.
- Per-product project folders under `data/projects/`.
- Local export packages under `exports/`.
- Product image import from product or affiliate URLs when the site allows it.
- Zero-touch orchestration from queue item to media plan and rendered output.
- AI presenter video generation with product reference images through Replicate.
- Official TikTok OAuth, upload/direct-post workflow, and post status tracking.
- Local vertical MP4 draft rendering from generated scripts.
- Export queue tracking.
- App logs in `logs/app.log` and error logs in `logs/errors.log`.

## Windows setup

From PowerShell:

```powershell
cd AffiliateVideoMachine
py -3.11 -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app\main.py
```

If `py -3.11` is not available, install Python 3.11 or newer from <https://www.python.org/downloads/windows/>, then try again.

## Project structure

```text
AffiliateVideoMachine/
  app/
    main.py
    database.py
    scoring.py
    script_generator.py
    compliance.py
    project_generator.py
    views/
  assets/
  data/
    projects/
  exports/
  logs/
  templates/
  config.yaml
  requirements.txt
```

## Daily workflow

1. Paste a product or affiliate URL on **Products -> Quick add URL**.
2. Let the app infer product metadata, import images, generate scripts, and optionally queue the first script.
3. Open **Export Queue** and use **Run autonomous media pipeline** for the AI video pass.
4. Review the generated MP4.
5. Use the TikTok page to upload the rendered MP4 as a TikTok inbox draft or direct post.
6. Adjust scoring, compliance, render, AI video, and TikTok settings on the Settings page when needed.

The manual product form still exists for corrections, but URL-first setup is the intended workflow.

For the deployment and TikTok review path, read `DEPLOYMENT.md` and `TIKTOK_REVIEW.md`.

## Local data notes

The SQLite database is created automatically the first time the app runs. Generated product folders and script text files are stored locally under `data/projects/`.

Export queue packages are local folders under `exports/`. The renderer creates a vertical MP4 draft from script scenes, product metadata, and available product imagery.

On the Export Queue page, use **Import product images from affiliate link** to copy page images into the product project's `source_assets` folder. Some stores block automated requests; when that happens, save product or lifestyle images manually into that same folder before rendering. Supported image types are `.jpg`, `.png`, `.webp`, and `.bmp`.

The local draft renderer is free and runs on your machine. It does not upload or publish anything.

## AI presenter video

For a fresh AI-generated clip of a person holding and talking about the product, the app includes a Replicate reference-to-video integration. Add product images first, then use **Generate AI presenter video** on the Export Queue page. This cloud AI path may use paid API credits from your provider account.

You need a Replicate API token. In PowerShell, set it before launching Streamlit:

```powershell
$env:REPLICATE_API_TOKEN="your_token_here"
streamlit run app\main.py
```

The default provider model is `xai/grok-imagine-r2v`, which accepts 1-7 reference images, a prompt, duration, aspect ratio, and resolution. Generated videos are saved into the selected export package.

### AI cost controls

The app does not generate Replicate videos in the background. A paid AI video job only starts after you click an AI generation button and approve the paid-generation checkbox.

The default test clip length is 5 seconds. The default cost estimate is `$0.05` per output second, so the first test run is estimated around `$0.25`. Change the estimate in Settings if your selected model's pricing changes.

If a queue item already has an AI-rendered MP4, the app blocks accidental regeneration unless you explicitly allow a second paid generation for that item.

## Zero-touch orchestration

On the Export Queue page, **Run autonomous media pipeline** performs the full framework pass:

1. Dereference the product or affiliate URL.
2. Extract commercial metadata from Open Graph, JSON-LD, and product-page markup when available.
3. Acquire product imagery from the page when allowed.
4. Normalize and rank images for vertical short-form video.
5. Write a conversion media plan and AI presenter prompt into the export package.
6. Generate an AI presenter video when a Replicate token is available.
7. Stop with an actionable error in AI-only mode, or fall back to a deterministic local MP4 when fallback mode is allowed.

Some retailers block automated asset access. In that case, the framework still creates the plan. In AI-only mode it stops until usable reference images and a provider token are available. If fallback mode is allowed, it can create an image-composited MP4, but that is not the same as a generated presenter video.

## TikTok publishing

The TikTok page uses TikTok's official Content Posting API. You need:

- A TikTok Developer app.
- Login Kit configured with an HTTPS redirect URI.
- Content Posting API added to the app.
- Approved `video.upload` and/or `video.publish` scopes.
- A TikTok user to authorize the app.

For local testing, set credentials before launching Streamlit:

```powershell
$env:TIKTOK_CLIENT_KEY="your_client_key"
$env:TIKTOK_CLIENT_SECRET="your_client_secret"
$env:TIKTOK_REDIRECT_URI="https://your-deployed-app.streamlit.app"
streamlit run app\main.py
```

For Streamlit Community Cloud, set those same values as app secrets. TikTok will not accept `localhost` as the review redirect URI, so the deployed HTTPS URL is required for the real TikTok connection flow.

Workflow:

1. Open **TikTok -> Connect**.
2. Open the generated TikTok authorization URL.
3. TikTok redirects back to the deployed dashboard. The app captures the callback code automatically.
4. Open **TikTok -> Accounts** and query creator info.
5. Open **TikTok -> Publish**, select a rendered MP4, review caption/disclosure/privacy, then send to TikTok.
6. Open **TikTok -> Status** to refresh the TikTok processing state.

Direct posts require TikTok approval and creator consent. Unaudited apps may be restricted to private/`SELF_ONLY` posting. TikTok's public Content Posting API does not expose a general affiliate product-link attachment field; attaching a TikTok Shop affiliate product may still need TikTok Shop or Creator Center tooling.
