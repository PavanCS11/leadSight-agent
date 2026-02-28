# Sales Intelligence Web Crawler & LLM Enricher

This project is a **Playwright + LLM–powered sales intelligence agent**. It:

- Crawls company websites from an input Excel sheet
- Extracts **Founded Info**, **About Us**, and **Email**
- Sends the scraped content to an LLM to generate a **360° company intelligence JSON**
- Flattens the JSON into multiple columns in a clean `output.xlsx`
- Exposes a **web UI + Flask backend** so you can upload a sheet and download the enriched report

You can use it in two ways:

1. **Web app** — `server.py` + `index.html` (recommended)
2. **CLI script** — `app.py` (reads `companies.xlsx` and writes `output.xlsx` directly)

---

## 1. Project Structure

- `app.py`  
  Core async crawler and enrichment pipeline. Uses Playwright to crawl each website, calls the LLM via `llm_utils.py`, flattens the JSON response, and writes `output.xlsx`.

- `server.py`  
  Flask backend server. Reuses the same `scrape_company` function and `OUTPUT_COLUMNS` from `app.py`. Provides endpoints for file upload, progress streaming (SSE), status, results, and downloading `output.xlsx`. Serves `index.html` at `/`.

- `llm_utils.py`  
  LLM helper module. Builds the prompt using **company name**, **website**, and **About Us** text, calls the Groq Chat Completions API using `httpx`, and returns a **single JSON object** with a fixed schema (company_overview, business_model, products_services, etc.).

- `index.html`  
  Frontend UI for the “NEXUS — Sales Intelligence Agent”. Lets you:
  - Upload `companies.xlsx`
  - See live scraping progress via SSE
  - View a summary table
  - Download the generated Excel report

- `companies.xlsx`  
  Input file for both CLI and web modes. **Must** contain at least:
  - `company_name`
  - `website`

- `output.xlsx`  
  Generated report. Contains:
  - `Company Name`
  - `Website`
  - `Founded Info`
  - `About Us`
  - `company_overview`
  - `business_model`
  - `products_services`
  - `operational_footprint`
  - `ai_ml_opportunity_map`
  - `leadership`
  - `strategic_developments`
  - `strategic_outlook`
  - `executive_brief`
  - `Email`

---

## 2. Setup

### 2.1. Clone / open the project

Make sure your working directory is:

```bash
cd "C:\Users\deepankar.s\OneDrive - Praval\Documents\Data Extraction"
```

### 2.2. (Recommended) Create and activate a virtual environment

```bash
python -m venv dataExtract
dataExtract\Scripts\activate
```

### 2.3. Install Python dependencies

If `requirements.txt` is configured:

```bash
pip install -r requirements.txt
```

Otherwise, make sure at least these are installed:

```bash
pip install flask flask-cors pandas playwright httpx python-dotenv openpyxl
playwright install chromium
```

### 2.4. Configure LLM credentials

`llm_utils.py` reads credentials from environment variables via `python-dotenv`:

```python
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL_NAME = os.getenv("GROQ_MODEL_NAME")
```

Create a `.env` file in the project root:

```text
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL_NAME=your_groq_model_name_here   # e.g. llama-3.1-70b-versatile
```

> If these are not set, LLM enrichment is skipped gracefully with a log message.

---

## 3. Running the Web App (Flask + Frontend)

### 3.1. Start the backend server

From the project folder (with venv activated if using one):

```bash
python server.py
```

You should see:

```text
🚀 Sales Intelligence Server running at http://localhost:5000
```

### 3.2. Open the UI

1. In your browser, go to: `http://localhost:5000/`
2. Click the upload area and select `companies.xlsx`
3. Click **“Run Intelligence Agent”**
4. Watch the live progress cards and table populate via SSE
5. When finished, click **Download Excel** to save the enriched report

The downloaded Excel file (`sales_intelligence_output.xlsx` from `/download`) is backed by the same schema as `app.py` (including all 360° intelligence columns).

> **Note (Windows/Excel):** Don’t keep `output.xlsx` open in Excel while running jobs or downloading; Excel locks the file and you may get a `PermissionError`. Close the file before re-running or downloading.

---

## 4. Running the CLI Pipeline (app.py)

You can also run the full pipeline directly from the command line, without the web UI.

1. Ensure `companies.xlsx` is present in the project folder and has the columns:
   - `company_name`
   - `website`

2. Run:

```bash
python app.py
```

3. The script will:
   - Launch Playwright Chromium (visible browser)
   - Iterate over each row in `companies.xlsx`
   - Crawl the website and key internal pages
   - Extract:
     - `Founded Info` (regex-based)
     - `About Us` (sentence around “about us”)
     - `Email` (regex-based)
   - Call the LLM with `company_name`, `website`, and `About Us`
   - Parse the JSON response and populate the 360° columns
   - Write/update `output.xlsx` after each company

4. Open `output.xlsx` in Excel to inspect the full enriched sheet.

---

## 5. Architecture & Data Flow

### 5.1. High-Level Components

- **Crawler (Playwright)**  
  Implemented in `app.py` (`scrape_company`) and reused by `server.py`:
  - Opens homepage
  - Handles simple cookie popups
  - Scans internal `<a>` links, scores them by presence of keywords like “about”, “company”, “overview”, etc.
  - Visits the top N high-scoring internal pages
  - Concatenates all text and normalizes whitespace
  - Applies regex / keyword extraction to derive founded info, About Us, and email.

- **LLM Layer (`llm_utils.py`)**  
  - Builds a structured, instruction-heavy prompt including:
    - Company name
    - Company website
    - Extracted About Us text
  - Specifies a **fixed JSON schema** with top-level keys:
    - `company_overview`, `business_model`, `products_services`, `operational_footprint`,
      `ai_ml_opportunity_map`, `leadership`, `strategic_developments`, `strategic_outlook`,
      `executive_brief`
  - Calls Groq’s OpenAI-compatible Chat Completions endpoint with `httpx`
  - Returns the raw JSON string.

- **Flattening / Excel Writer (`app.py` & `server.py`)**
  - Parses the JSON string with `json.loads`
  - For each top-level key:
    - If it’s a dict/list → store compact JSON string in its own Excel column
    - If it’s a primitive (string, etc.) → store directly
  - Uses `pandas` to write `output.xlsx` in a stable column order (`OUTPUT_COLUMNS`).

- **Flask Backend (`server.py`)**
  - `POST /upload`: save uploaded Excel, start background scraper thread
  - `GET /progress`: stream progress events with SSE (start, step, company_start, company_done, done, error)
  - `GET /status`: current job status
  - `GET /results`: accumulated results in JSON
  - `GET /download`: send `output.xlsx` to the client
  - `GET /`: serve `index.html`

- **Frontend (`index.html`)**
  - Vanilla HTML/CSS/JS, no build step
  - Handles file drop/upload
  - Starts job via `/upload`
  - Listens to `/progress` via `EventSource`
  - Updates:
    - Progress bar + percentage
    - Per-company status cards
    - Results table (for a few headline fields)
    - Download bar once done

### 5.2. End-to-End Flow (Web Mode)

1. User uploads `companies.xlsx` from the browser
2. `POST /upload` saves it to `uploads/` and starts `run_scraper_thread(...)`
3. `run_scraper_async`:
   - Reads the file into a DataFrame
   - For each row calls `scrape_company` (from `app.py`)
   - Appends the result dict to `job["results"]`
   - Writes `output.xlsx` after each company using `OUTPUT_COLUMNS`
   - Pushes SSE events for UI updates
4. When scraping finishes, the server emits a `done` SSE event
5. Frontend shows “Report Ready” and the **Download Excel** button (link to `/download`)
6. User clicks download and receives the latest `output.xlsx`

---

## 6. Troubleshooting

- **`PermissionError: [Errno 13] output.xlsx`**  
  Close `output.xlsx` in Excel before running the scraper or downloading; Excel locks the file for exclusive access.

- **Playwright errors about missing browser**  
  Run `playwright install chromium` once inside your environment.

- **LLM not being called**  
  Check that `.env` contains valid `GROQ_API_KEY` and `GROQ_MODEL_NAME`. If missing, you’ll see a log like  
  `"ℹ️ GROQ_API_KEY or GROQ_MODEL_NAME not set; skipping LLM preprocessing."`

- **Frontend can’t reach backend**  
  Ensure `server.py` is running and that `API` in `index.html` is set to `http://localhost:5000` (default).

---

## 7. Entry Points Summary

- **Web app entry point:**  
  `python server.py` → open `http://localhost:5000/`

- **CLI entry point:**  
  `python app.py` → reads `companies.xlsx` and writes `output.xlsx`

Both paths share the same core scraping and LLM enrichment logic, ensuring consistent results between the web UI and local runs. 

