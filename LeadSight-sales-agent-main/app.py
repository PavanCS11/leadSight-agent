"""
Enterprise-Level Finance Website Crawler
-----------------------------------------

Features:
- Async Playwright
- Visible browser
- Cookie handling
- Intelligent internal link crawling
- Multi-page navigation
- Regex extraction
- Context-based extraction
- Clean Excel output

Run:
    python app.py
"""

import asyncio
import json
import pandas as pd
import re
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright

from llm_utils import preprocess_about_with_llm


# -----------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------

IMPORTANT_KEYWORDS = [
    "about", "company", "corporate", "group",
    "leadership", "management", "investor",
    "who", "overview", "profile"
]

COOKIE_KEYWORDS = ["accept", "agree", "allow all"]

# Define output columns in exact order
OUTPUT_COLUMNS = [
    "Company Name",
    "Website",
    "Founded Info",
    "About Us",
    # Top-level 360° JSON keys as separate columns
    "company_overview",
    "business_model",
    "products_services",
    "operational_footprint",
    "ai_ml_opportunity_map",
    "leadership",
    "strategic_developments",
    "strategic_outlook",
    "executive_brief",
    "Email",
]


# -----------------------------------------------------------
# REGEX EXTRACTION FUNCTIONS
# -----------------------------------------------------------

def extract_founded(text):
    patterns = [
        r"Founded\s+(in\s+)?(\d{4})",
        r"Established\s+(in\s+)?(\d{4})",
        r"Since\s+(\d{4})"
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
# MAIN SCRAPER PER COMPANY
# -----------------------------------------------------------

async def scrape_company(browser, company_name, website):

    print(f"\n🔎 Starting: {company_name}")

    page = None
    result = {
        "Company Name": company_name,
        "Website": website,
        "Founded Info": None,
        "About Us": None,
        # 360° JSON top-level keys (each will store a JSON string or text)
        "company_overview": None,
        "business_model": None,
        "products_services": None,
        "operational_footprint": None,
        "ai_ml_opportunity_map": None,
        "leadership": None,
        "strategic_developments": None,
        "strategic_outlook": None,
        "executive_brief": None,
        "Email": None,
    }

    try:
        page = await browser.new_page()
        
        # Increase timeout and use domcontentloaded instead of networkidle for faster loading
        await page.goto(website, timeout=90000, wait_until="domcontentloaded")
        await asyncio.sleep(2)  # Give page time to load

        # ---------------------------------------------------
        # HANDLE COOKIE POPUPS
        # ---------------------------------------------------
        for keyword in COOKIE_KEYWORDS:
            try:
                button = page.locator(f"text={keyword}")
                if await button.count() > 0:
                    await button.first.click()
                    print("🍪 Cookie popup handled")
                    await asyncio.sleep(1)
                    break
            except:
                pass

        # ---------------------------------------------------
        # EXTRACT ALL TEXT FROM HOMEPAGE
        # ---------------------------------------------------
        all_text = await page.inner_text("body")

        # ---------------------------------------------------
        # INTELLIGENT INTERNAL LINK DISCOVERY
        # ---------------------------------------------------
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

                # Only crawl same domain
                if domain not in full_url:
                    continue

                score = 0

                for keyword in IMPORTANT_KEYWORDS:
                    if keyword in link_text:
                        score += 2
                    if keyword in full_url.lower():
                        score += 3

                if score > 0:
                    candidate_links.append((full_url, score))

            except:
                continue

        # Sort by score descending
        candidate_links = sorted(candidate_links, key=lambda x: x[1], reverse=True)

        visited = set()

        # ---------------------------------------------------
        # VISIT TOP 3 IMPORTANT PAGES
        # ---------------------------------------------------
        for url, _ in candidate_links[:3]:

            if url in visited:
                continue

            visited.add(url)

            try:
                print(f"➡ Crawling: {url}")
                await page.goto(url, timeout=90000, wait_until="domcontentloaded")
                await asyncio.sleep(2)

                sub_text = await page.inner_text("body")
                all_text += " " + sub_text

            except Exception as e:
                print(f"⚠️  Could not crawl {url}: {e}")
                continue

        # Clean text
        all_text = re.sub(r"\s+", " ", all_text)

        # ---------------------------------------------------
        # APPLY EXTRACTION LOGIC
        # ---------------------------------------------------
        result["Founded Info"] = extract_founded(all_text)
        result["About Us"] = extract_sentence_near_keyword(
            all_text, "about us"
        )
        result["Email"] = extract_email(all_text)

        # ---------------------------------------------------
        # LLM: 360° COMPANY JSON (USING NAME, WEBSITE, ABOUT US)
        # ---------------------------------------------------
        try:
            raw_json = await preprocess_about_with_llm(
                company_name=company_name,
                company_website=result["Website"],
                about_text=result["About Us"] or "",
            )

            if raw_json:
                try:
                    parsed = json.loads(raw_json)
                except json.JSONDecodeError as je:
                    print(f"⚠️  Could not parse JSON for {company_name}: {je}")
                    parsed = None

                if isinstance(parsed, dict):
                    for key in [
                        "company_overview",
                        "business_model",
                        "products_services",
                        "operational_footprint",
                        "ai_ml_opportunity_map",
                        "leadership",
                        "strategic_developments",
                        "strategic_outlook",
                        "executive_brief",
                    ]:
                        value = parsed.get(key)
                        if value is None:
                            result[key] = None
                        elif isinstance(value, (dict, list)):
                            # Store nested structures as compact JSON strings
                            result[key] = json.dumps(value, ensure_ascii=False)
                        else:
                            # Primitive types (str, int, etc.)
                            result[key] = value

        except Exception as e:
            print(f"⚠️  Error during LLM preprocessing for {company_name}: {e}")

    except Exception as e:
        print(f"❌ Error with {company_name}: {e}")
    finally:
        # Always close the page, even if there was an error
        if page:
            try:
                await page.close()
            except:
                pass

    return result


# -----------------------------------------------------------
# MAIN EXECUTION
# -----------------------------------------------------------

async def main():

    print("🚀 Starting Enterprise Crawler...\n")

    df = pd.read_excel("companies.xlsx")
    results = []

    async with async_playwright() as p:

        browser = await p.chromium.launch(headless=False)

        # Process companies one by one sequentially
        for idx, row in df.iterrows():
            print(f"\n{'='*60}")
            print(f"Processing company {idx + 1} of {len(df)}")
            print(f"{'='*60}")
            
            # Scrape one company at a time
            result = await scrape_company(
                browser,
                row["company_name"],
                row["website"]
            )
            
            # Append result immediately
            results.append(result)
            
            # Save to Excel after each company is scraped
            try:
                output_df = pd.DataFrame(results)
                # Ensure columns are in the correct order
                output_df = output_df.reindex(columns=OUTPUT_COLUMNS)
                output_df.to_excel("output.xlsx", index=False)
                print(f"✅ Saved result for {row['company_name']} to output.xlsx")
                print(f"   📊 Total rows saved: {len(output_df)}")
                print(f"   📋 Columns: {list(output_df.columns)}")
            except Exception as e:
                print(f"❌ Error saving to Excel: {e}")
                import traceback
                traceback.print_exc()

        await browser.close()

    print("\n✅ Crawling Completed Successfully!")
    print("📁 Final data saved to output.xlsx")


if __name__ == "__main__":
    asyncio.run(main())
