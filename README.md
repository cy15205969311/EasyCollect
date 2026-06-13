# EasyCollect

EasyCollect is a lightweight cross-border ecommerce automation assistant for
collecting and normalizing product data from 1688 product detail pages. It uses a
Manifest V3 Chrome extension to capture page-level product JSON, a FastAPI
backend to clean and flatten the payload, and an optional LLM workflow to produce
retail-ready listing copy.

The project is designed as an MVP-friendly monorepo: no database, no external
object storage, and no heavyweight ERP assumptions. Product data, debug payloads,
and export packages are handled locally so the complete workflow is easy to run,
inspect, and iterate.

## Features

- **1688 page capture**: Chrome extension injects a Shadow DOM floating UI into
  1688 product pages.
- **MV3 MAIN world extraction**: Service Worker uses `chrome.scripting` to read
  page globals without inline script CSP issues.
- **Dual collection modes**:
  - Fast collection skips the LLM and immediately creates a ZIP asset package.
  - AI deep collection runs the Kiro Agent copywriting workflow before export.
- **Robust parser**: Backend flattens volatile 1688 payload structures into a
  compact EasyCollect product schema.
- **Local debug files**: Latest raw and parsed payloads are written to
  `server/static/cache_data/`.
- **ERP-style export**: Images, listing copy, and SKU inventory CSV are packed
  into a downloadable ZIP file.
- **LLM failover and graceful degradation**: Primary OpenAI-compatible provider
  falls back to DeepSeek; model calls are capped at 15 seconds and fallback copy
  is generated if the model times out or returns invalid JSON.

## Tech Stack

### Browser Extension

- Vue 3
- Vite
- `@crxjs/vite-plugin`
- Tailwind CSS
- Chrome Manifest V3

### Backend

- Python
- FastAPI
- Uvicorn
- Pydantic
- HTTPX
- OpenAI-compatible async SDK
- Local `StaticFiles` media and export hosting

## Repository Structure

```text
EasyCollect/
├── extension/              # Chrome extension source
│   ├── src/
│   │   ├── background/     # MV3 service worker
│   │   ├── content/        # 1688 floating UI and message dispatch
│   │   └── popup/          # Extension popup
│   └── vite.config.ts
└── server/                 # FastAPI backend
    ├── app/
    │   ├── api/
    │   │   ├── export.py   # ZIP export package builder
    │   │   └── optimize.py # Kiro Agent LLM workflow
    │   ├── agents/
    │   ├── core/
    │   ├── models/
    │   └── static/
    ├── main.py             # FastAPI app and /api/collect
    └── requirements.txt
```

## Data Flow

```text
1688 product page
  -> Chrome content script floating UI
  -> Service Worker chrome.scripting.executeScript(world="MAIN")
  -> FastAPI /api/collect
  -> raw_payload.json + parsed_product.json
  -> optional Kiro Agent optimization
  -> ZIP export package
  -> Chrome downloads API
```

## Quick Start

### 1. Backend

```bash
cd server
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Health check:

```text
http://127.0.0.1:8000/health
```

### 2. LLM Configuration

Create `server/.env` from `server/.env.example`:

```env
PRIMARY_API_KEY=sk-your-primary-key
PRIMARY_BASE_URL=https://api2.apiaqi.com/v1
PRIMARY_MODEL_NAME=gpt-4o

FALLBACK_API_KEY=sk-your-deepseek-key
FALLBACK_BASE_URL=https://api.deepseek.com/v1
FALLBACK_MODEL_NAME=deepseek-chat
```

`server/.env` is intentionally ignored by Git. If the keys are missing or the
model fails, AI deep collection still exports a safe fallback ZIP.

### 3. Extension

```bash
cd extension
npm install
npm run dev
```

Open `chrome://extensions`, enable Developer Mode, and load the generated CRXJS
development extension. When permissions or scripts change, refresh the extension
and refresh the 1688 product page.

For stable testing without Vite HMR:

```bash
cd extension
npm run build
```

Then load `extension/dist` as an unpacked extension.

## Collection Modes

- **Fast Collection**: extracts product data, cleans SKU and image fields, builds
  the ZIP package, and downloads it as quickly as possible.
- **AI Deep Collection**: performs the same cleanup, then tries to generate
  optimized listing copy with the Kiro Agent before packaging.

The AI path is defensive by design:

- Client timeout: `15.0` seconds.
- Hard async timeout: `asyncio.wait_for(..., timeout=15.0)`.
- Invalid model JSON is rejected by Pydantic.
- Timeout or validation failure returns fallback copy instead of blocking ZIP
  export.

## Generated Local Files

Runtime artifacts are not committed:

- `server/static/cache_data/raw_payload.json`
- `server/static/cache_data/parsed_product.json`
- `server/static/cache_data/optimized_product.json`
- `server/static/exports/*.zip`
- `extension/dist/`

## API Endpoints

- `GET /health`: backend health check.
- `POST /api/collect`: accepts captured product payload, parses it, optionally
  optimizes copy, and returns an export download URL.
- `POST /api/optimize`: optimizes the latest `parsed_product.json`.
- `GET /api/export/download`: builds and downloads a ZIP from the latest cached
  product data.

## Notes

This project intentionally avoids a database for the MVP. The current workflow
uses local JSON files and local static assets so the parser, Agent behavior, and
export package can be inspected directly during development.
