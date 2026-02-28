import os
import httpx
import dotenv

dotenv.load_dotenv()
# -----------------------------------------------------------
# LLM / GROQ CONFIG (FILL THESE IN)
# -----------------------------------------------------------

# TODO: Put your Groq API key and model name here.
# Example model name placeholder: "llama-3.1-70b-versatile"

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL_NAME = os.getenv("GROQ_MODEL_NAME")


async def preprocess_about_with_llm(
    company_name: str,
    company_website: str,
    about_text: str,
) -> str | None:

    # You can adjust this instruction to change how the summary looks.
    system_prompt = (
        "You are a senior business analyst, market intelligence expert, and "
        "AI strategy consultant. You generate concise, structured company "
        "intelligence reports from limited web data."
    )

    # Use placeholder tokens so we don't conflict with JSON braces.
    user_prompt_template = """
Company Name: <<COMPANY_NAME>>
Company Website: <<COMPANY_WEBSITE>>
Source Data (About Us and related content):
<<ABOUT_TEXT>>

You are an enterprise intelligence analyst.

Your task is to generate a structured 360° company intelligence report strictly in JSON format.

CRITICAL RULES:
- Return strictly valid JSON.
- Do NOT include markdown or explanations.
- All fields must be present exactly as defined.
- If information is explicitly stated in the source, use it.
- If not explicitly stated but can be reasonably inferred based on industry norms, business model patterns, or company type, provide a clearly reasoned inference.
- Only return null when no reasonable inference can be made.
- Do NOT fabricate specific executive names, funding amounts, acquisition details, or dated events.
- Strategic analysis and AI opportunity mapping may include expert inference.

Return a single JSON object with the following structure:

{
  "company_overview": {
    "summary":"string",
    "mission_positioning":"string",
    "target_customers_industries":"string",
    "geographic_presence":"string",
    "growth_stage":"string"
  },
  "business_model": {
    "core_model":"string",
    "monetization_strategy":"string",
    "pricing_model":"string",
    "revenue_streams_primary":"string",
    "revenue_streams_secondary":"string",
    "distribution_channels":"string",
    "key_cost_drivers":"string"
  },
  "products_services": {
    "core_offerings":"string",
    "supporting_services":"string",
    "technology_infrastructure":"string",
    "technology_data_layer":"string",
    "technology_ai_ml":"string",
    "technology_security":"string",
    "competitive_advantages":"string",
    "ecosystem_integrations":"string"
  },
  "operational_footprint": {
    "key_operational_areas":"string",
    "supply_chain_characteristics":"string",
    "partnerships_alliances":"string",
    "regulatory_environment":"string"
  },
  "ai_ml_opportunity_map": {
    "customer_experience":"string",
    "sales_marketing":"string",
    "operations":"string",
    "supply_chain":"string",   
    "finance":"string",
    "risk_compliance":"string",
    "product_innovation":"string",
    "executive_decision_intelligence":"string"
  },
  "leadership": {
    "executives":"string"
  },
  "strategic_developments": {
    "recent_news":"string",
    "partnerships": null,
    "acquisitions":"string",
    "funding": null,
    "product_launches": null,
    "strategic_initiatives":"string",
    "market_expansion": null,
    "regulatory_developments": null
  },
  "strategic_outlook": {
    "near_term_priorities":"string",
    "key_risks":"string",
    "growth_opportunities":"string",
    "ai_transformation_readiness":"string",
    "overall_assessment":"string"
  },
  "executive_brief":"string"
}
"""

    user_prompt = (
        user_prompt_template
        .replace("<<COMPANY_NAME>>", company_name or "")
        .replace("<<COMPANY_WEBSITE>>", company_website or "")
        .replace("<<ABOUT_TEXT>>", about_text or "")
    )

    # If the user has not configured the Groq details yet, skip gracefully.
    if (
        not GROQ_API_KEY
        or not GROQ_MODEL_NAME
        or "YOUR_GROQ" in GROQ_API_KEY
        or "YOUR_GROQ" in GROQ_MODEL_NAME
    ):
        print("ℹ️  GROQ_API_KEY or GROQ_MODEL_NAME not set; skipping LLM preprocessing.")
        return None

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GROQ_MODEL_NAME,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.2,
                },
            )

        resp.raise_for_status()
        data = resp.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        return content or None

    except Exception as e:
        print(f"⚠️  LLM preprocessing failed: {e}")
        return None