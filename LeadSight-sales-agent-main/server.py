"""
Flask Backend Server for Sales Intelligence Agent
--------------------------------------------------
Endpoints:
  POST /upload       — Upload Excel file, start scraping
  GET  /progress     — SSE stream of real-time progress
  GET  /download     — Download output.xlsx
  GET  /status       — Current job status (JSON)
  GET  /results      — Results so far (JSON)
"""

import asyncio
import json
import os
import re
import threading
import time
import uuid
from io import StringIO
from urllib.parse import urljoin, urlparse

import pandas as pd
from flask import Flask, Response, jsonify, request, send_file
from flask_cors import CORS

# Reuse core scraping logic and output schema from app.py
from app import scrape_company, OUTPUT_COLUMNS as APP_OUTPUT_COLUMNS

# -----------------------------------------------------------
# CONFIGURATION (mirrored from app.py)
# -----------------------------------------------------------

IMPORTANT_KEYWORDS = [
    "about", "company", "corporate", "group",
    "leadership", "management", "investor",
    "who", "overview", "profile"
]
COOKIE_KEYWORDS = ["accept", "agree", "allow all"]

# Mirror the richer Excel schema from app.py so downloaded reports
# contain the full 360° intelligence columns.
OUTPUT_COLUMNS = APP_OUTPUT_COLUMNS

UPLOAD_FOLDER = "uploads"
OUTPUT_FILE = "output.xlsx"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# -----------------------------------------------------------
# FLASK APP
# -----------------------------------------------------------

app = Flask(__name__)
CORS(app)

# Global job state (single-job server for hackathon)
job = {
    "id": None,
    "status": "idle",        # idle | running | done | error
    "total": 0,
    "current": 0,
    "current_company": "",
    "current_step": "",
    "results": [],
    "events": [],            # SSE event queue
    "error": None,
}


def push_event(event_type: str, data: dict):
    """Append an SSE event to the queue."""
    job["events"].append({
        "type": event_type,
        "data": data,
        "ts": time.time(),
    })


# -----------------------------------------------------------
# EXTRACTION HELPERS (from app.py)
# -----------------------------------------------------------

def extract_founded(text):
    patterns = [
        r"Founded\s+(in\s+)?(\d{4})",
        r"Established\s+(in\s+)?(\d{4})",
        r"Since\s+(\d{4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def extract_email(text):
    pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]+"
    match = re.search(pattern, text)
    return match.group(0) if match else None


def extract_sentence_near_keyword(text, keyword):
    pattern = rf"([^.]*{keyword}[^.]*)"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(0).strip() if match else None


# -----------------------------------------------------------
# ASYNC SCRAPER (adapted from app.py)
# -----------------------------------------------------------

async def scrape_company_async(browser, company_name, website):
    from playwright.async_api import async_playwright  # import here

    page = None
    result = {
        "Company Name": company_name,
        "Website": website,
        "Founded Info": None,
        "About Us": None,
        "Email": None,
    }

    try:
        page = await browser.new_page()

        push_event("step", {
            "company": company_name,
            "step": f"Opening {website}",
        })

        await page.goto(website, timeout=90000, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # Handle cookie popups
        for keyword in COOKIE_KEYWORDS:
            try:
                button = page.locator(f"text={keyword}")
                if await button.count() > 0:
                    await button.first.click()
                    await asyncio.sleep(1)
                    break
            except:
                pass

        all_text = await page.inner_text("body")

        # Discover internal links
        push_event("step", {
            "company": company_name,
            "step": "Discovering internal pages…",
        })

        domain = urlparse(website).netloc
        links = page.locator("a")
        link_count = await links.count()
        candidate_links = []

        for i in range(link_count):
            try:
                href = await links.nth(i).get_attribute("href")
                link_text = (await links.nth(i).inner_text()).lower().strip()
                if not href:
                    continue
                full_url = urljoin(website, href)
                if domain not in full_url:
                    continue
                score = sum(
                    2 * (kw in link_text) + 3 * (kw in full_url.lower())
                    for kw in IMPORTANT_KEYWORDS
                )
                if score > 0:
                    candidate_links.append((full_url, score))
            except:
                continue

        candidate_links = sorted(candidate_links, key=lambda x: x[1], reverse=True)
        visited = set()

        # Visit top 3 important pages
        for url, _ in candidate_links[:3]:
            if url in visited:
                continue
            visited.add(url)
            try:
                push_event("step", {
                    "company": company_name,
                    "step": f"Crawling: {url}",
                })
                await page.goto(url, timeout=90000, wait_until="domcontentloaded")
                await asyncio.sleep(2)
                sub_text = await page.inner_text("body")
                all_text += " " + sub_text
            except Exception as e:
                continue

        # Clean & extract
        all_text = re.sub(r"\s+", " ", all_text)
        result["Founded Info"] = extract_founded(all_text)
        result["About Us"] = extract_sentence_near_keyword(all_text, "about us")
        result["Email"] = extract_email(all_text)

    except Exception as e:
        push_event("step", {"company": company_name, "step": f"Error: {str(e)}"})
    finally:
        if page:
            try:
                await page.close()
            except:
                pass

    return result


async def run_scraper_async(input_file: str):
    from playwright.async_api import async_playwright

    df = pd.read_excel(input_file)
    total = len(df)
    job["total"] = total
    job["results"] = []

    push_event("start", {"total": total})

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for idx, row in df.iterrows():
            company_name = row["company_name"]
            website = row["website"]

            job["current"] = idx + 1
            job["current_company"] = company_name
            push_event("company_start", {
                "index": idx + 1,
                "total": total,
                "company": company_name,
                "website": website,
            })

            # Use the shared scraper from app.py so the server generates
            # the same rich output (including LLM-based 360° columns).
            result = await scrape_company(browser, company_name, website)
            job["results"].append(result)

            # Save output after each company
            try:
                out_df = pd.DataFrame(job["results"]).reindex(columns=OUTPUT_COLUMNS)
                out_df.to_excel(OUTPUT_FILE, index=False)
            except Exception as e:
                pass

            push_event("company_done", {
                "index": idx + 1,
                "total": total,
                "company": company_name,
                "result": result,
            })

        await browser.close()

    push_event("done", {
        "total": total,
        "output_file": OUTPUT_FILE,
    })
    job["status"] = "done"


def run_scraper_thread(input_file: str):
    """Run the async scraper in a dedicated thread."""
    try:
        asyncio.run(run_scraper_async(input_file))
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        push_event("error", {"message": str(e)})


# -----------------------------------------------------------
# ROUTES
# -----------------------------------------------------------


@app.route("/")
def home():
    """Serve the frontend so the app works at http://localhost:5000/."""
    return send_file("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    """Accept an Excel file, kick off scraping."""
    if job["status"] == "running":
        return jsonify({"error": "A job is already running."}), 409

    if "file" not in request.files:
        return jsonify({"error": "No file provided."}), 400

    f = request.files["file"]
    if not f.filename.endswith((".xlsx", ".xls", ".csv")):
        return jsonify({"error": "File must be .xlsx, .xls, or .csv"}), 400

    # Save uploaded file
    job_id = str(uuid.uuid4())[:8]
    input_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_{f.filename}")
    f.save(input_path)

    # Validate columns
    try:
        df = pd.read_excel(input_path) if not input_path.endswith(".csv") else pd.read_csv(input_path)
        required = {"company_name", "website"}
        if not required.issubset(set(df.columns)):
            return jsonify({
                "error": f"File must have columns: {required}. Found: {list(df.columns)}"
            }), 400
    except Exception as e:
        return jsonify({"error": f"Could not read file: {str(e)}"}), 400

    # Reset job state
    job.update({
        "id": job_id,
        "status": "running",
        "total": 0,
        "current": 0,
        "current_company": "",
        "current_step": "",
        "results": [],
        "events": [],
        "error": None,
    })

    # Start scraper in background thread
    t = threading.Thread(target=run_scraper_thread, args=(input_path,), daemon=True)
    t.start()

    return jsonify({"job_id": job_id, "message": "Scraping started."})


@app.route("/progress")
def progress():
    """SSE stream: sends events as they happen."""
    def generate():
        last_idx = 0
        while True:
            # Send any new events
            current_events = job["events"]
            new_events = current_events[last_idx:]
            for ev in new_events:
                payload = json.dumps({"type": ev["type"], "data": ev["data"]})
                yield f"data: {payload}\n\n"
            last_idx += len(new_events)

            # Stop streaming when done or error
            if job["status"] in ("done", "error") and last_idx >= len(job["events"]):
                break

            time.sleep(0.3)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/status")
def status():
    return jsonify({
        "status": job["status"],
        "total": job["total"],
        "current": job["current"],
        "current_company": job["current_company"],
        "error": job["error"],
    })


@app.route("/results")
def results():
    return jsonify({"results": job["results"]})


@app.route("/download")
def download():
    if not os.path.exists(OUTPUT_FILE):
        return jsonify({"error": "No output file yet."}), 404
    return send_file(OUTPUT_FILE, as_attachment=True, download_name="sales_intelligence_output.xlsx")


# -----------------------------------------------------------
# MAIN
# -----------------------------------------------------------

if __name__ == "__main__":
    print("🚀 Sales Intelligence Server running at http://localhost:5000")
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)
