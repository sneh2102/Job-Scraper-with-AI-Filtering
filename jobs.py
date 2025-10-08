import logging
import traceback
import os
import json
import re
from datetime import date
import time
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font
from openpyxl.utils import get_column_letter
from tqdm import tqdm
from ai import OllamaAssistant
from jobs_scraper import *

# --------------------------- Config & Constants ---------------------------

required_columns = [
    "AI_recommendation",
    "company",
    "title",
    "link",
    "years_required",
    "description",
    "posted_date",
]

pd.set_option("display.max_rows", None)
pd.set_option("display.max_columns", None)
pd.set_option("display.width", None)
logging.basicConfig(level=logging.INFO)

excel_file = "jobs.xlsx"

PERSONAL_JOB_FINDER_PROMPT = """
You are my Personal IT Job Finder & Evaluator.

INPUTS
- JOB:
  - title: {title}
  - description: {description}

- RESUME:
{resume_text}

GOAL
Evaluate whether I should apply to this job by analyzing both the job description and my resume.
You must consider:
1. Technical relevance (same tech stack or domain)
2. Required years of experience vs my experience (assume I have 2 years)
3. The role level (junior / mid / senior)
4. The overall alignment between job requirements and my background.

-----------------------------------------------------
EVALUATION LOGIC
-----------------------------------------------------

1️⃣ FIELD FILTER:
   - ✅ Accept jobs only if they clearly belong to Information Technology, Software Development, Data, Cloud, AI/ML, DevOps, Cybersecurity, or related technical domains.
   - 🚫 Reject jobs in Business, Marketing, Finance, HR, Sales, Consulting, or Operations unless they have a strong software/technical component.

2️⃣ EXPERIENCE CHECK:
   - Extract the required years of experience from the job description.
   - Compare it with my experience (2 years).
   - If the job asks for:
       - ≤ 2 years → treat as GOOD MATCH.
       - 3–4 years → MAYBE (stretch but possible if skills match strongly).
       - > 4 years → NO (too senior).
       - Not mentioned → neutral, base verdict on technical skills.

3️⃣ TECHNOLOGY & SKILLS MATCH:
   - Identify major technologies, frameworks, or tools from the JD.
   - Match them with my resume’s stack (React, Node.js, AWS, Python, SQL, Kubernetes, Docker, Terraform, LangChain, ML/AI, etc.).
   - If ≥70% of them appear in my resume → strong technical match.
   - If 40–69% → partial match.
   - If <40% → poor match.

4️⃣ FINAL DECISION MATRIX:
   - Strong technical match + good/neutral experience → verdict = "yes"
   - Partial technical match OR slightly higher experience (4–5 yrs) → verdict = "maybe"
   - Non-technical OR experience gap >2 years OR different domain → verdict = "no"

-----------------------------------------------------
OUTPUT FORMAT (STRICT)
-----------------------------------------------------
Return ONLY a valid JSON object with **no extra text or explanation**, no backticks.

{
  "verdict": "<yes|no|maybe>",
  "years_required": "<number or 'unspecified'>",
  "reasoning": "<very short one-line reason>"
}
"""



# --------------------------- Helpers ---------------------------

def load_env_file(file_path):
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            if line.strip() and not line.startswith("#") and not line.startswith(";"):
                key, value = line.strip().split("=", 1)
                os.environ[key] = value


def load_resume_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        logging.warning("Could not load resume text at %s; proceeding with empty resume.", path)
        return ""


def format_prompt(template: str, **kwargs) -> str:
    """Safely substitute placeholders while keeping other braces literal.

    Escapes all braces first, then reinstates placeholders like {title}, {description}, {resume_text}.
    """
    escaped = template.replace("{", "{{").replace("}", "}}")
    for k, v in kwargs.items():
        escaped = escaped.replace(f"{{{{{k}}}}}", str(v))
    return escaped


def load_df():
    if os.path.exists(excel_file):
        df = pd.read_excel(excel_file, engine="openpyxl")
        # Ensure required columns exist; backfill missing ones instead of erroring
        for col in required_columns:
            if col not in df.columns:
                # Use sensible defaults for missing historical columns
                if col in ("keywords_required", "keywords_missing"):
                    df[col] = ""
                else:
                    df[col] = ""
        return df
    else:
        return pd.DataFrame(columns=required_columns)


def parse_json_response(response_text: str):
    """
    Robust JSON extraction:
    - Accept raw JSON or fenced ```json blocks
    - Remove trailing commas before closing } or ]
    """
    try:
        txt = response_text.strip()

        # If fenced, extract the inside
        if txt.startswith("```"):
            m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", txt, re.IGNORECASE)
            if m:
                txt = m.group(1).strip()

        # Remove trailing commas like {...,} or [...,]
        txt = re.sub(r",\s*([}\]])", r"\1", txt)

        parsed = json.loads(txt)

        verdict = str(parsed.get("verdict", "")).lower().strip()
        years_required = str(parsed.get("years_required", "unspecified")).strip()

        if verdict not in {"yes", "no", "maybe", "maybe+"}:
            raise ValueError(f"Invalid verdict: {verdict}")

        return verdict, "", years_required

    except Exception as e:
        logging.error("Invalid or unparsable JSON from model:\n%s", response_text)
        raise e


def quick_keyword_hit_rate(keywords_required, resume_text: str) -> str:
    """
    Very lightweight coverage metric: % of required keywords that appear in resume (case-insensitive).
    """
    if not keywords_required:
        return "0% (0/0)"
    rlow = resume_text.lower()
    hits = 0
    for kw in keywords_required:
        # Split on slashes or commas to allow simple alternates like "React/Next.js"
        alts = re.split(r"[\/,]| or ", kw.lower())
        alts = [a.strip() for a in alts if a.strip()]
        if any(a in rlow for a in alts):
            hits += 1
    pct = int(round(100.0 * hits / len(keywords_required)))
    return f"{pct}% ({hits}/{len(keywords_required)})"


def beautify_excel(path: str = None):
    target_path = path or excel_file
    wb = load_workbook(target_path)
    ws = wb.active

    # Header styling
    if ws.max_row >= 1:
        for cell in ws[1]:
            cell.font = Font(bold=True)

    # Auto filter
    ws.auto_filter.ref = ws.dimensions

    # Color fills for recommendations
    red_fill = PatternFill(start_color="FFCCCC", end_color="FFCCCC", fill_type="solid")
    green_fill = PatternFill(start_color="CCFFCC", end_color="CCFFCC", fill_type="solid")
    yellow_fill = PatternFill(start_color="FFFFCC", end_color="FFFFCC", fill_type="solid")

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
        for cell in row:
            # Column A = AI_recommendation
            if cell.column_letter == "A":
                if str(cell.value).lower() == "no":
                    cell.fill = red_fill
                elif str(cell.value).lower() in {"yes", "maybe+"}:
                    cell.fill = green_fill
                elif str(cell.value).lower() not in {"yes", "no"}:
                    cell.fill = yellow_fill
            # Column D = link (hyperlink)
            if cell.column_letter == "D" and cell.value:
                cell.hyperlink = cell.value
                cell.style = "Hyperlink"

    # Approximate auto-size columns
    for col_idx in range(1, ws.max_column + 1):
        col_letter = get_column_letter(col_idx)
        max_len = 0
        for cell in ws[col_letter]:
            try:
                val = str(cell.value) if cell.value is not None else ""
            except Exception:
                val = ""
            if len(val) > max_len:
                max_len = len(val)
        # clamp width to reasonable range
        ws.column_dimensions[col_letter].width = max(10, min(60, max_len + 2))

    wb.save(target_path)


def write_excel_safely(df: pd.DataFrame, path: str) -> str:
    """
    Attempt to write the Excel file to `path`.
    If the file is locked (e.g., open in Excel) and a PermissionError occurs,
    write to a timestamped fallback file next to it and return that path.
    """
    try:
        df.to_excel(path, index=False, engine="openpyxl")
        beautify_excel(path)
        return path
    except PermissionError:
        base, ext = os.path.splitext(path)
        fallback = f"{base}_{date.today().isoformat()}{ext}"
        logging.warning(
            "Permission denied writing %s. Is it open in Excel? Saving to %s instead.",
            path,
            fallback,
        )
        df.to_excel(fallback, index=False, engine="openpyxl")
        beautify_excel(fallback)
        return fallback


def send_with_retries(assistant, msg: str, tries: int = 3, backoff_sec: float = 1.5):
    last_err = None
    for attempt in range(1, tries + 1):
        try:
            return assistant.submit_message(msg)
        except Exception as e:
            last_err = e
            logging.warning("Model call failed (attempt %d/%d): %s", attempt, tries, e)
            time.sleep(backoff_sec * attempt)
    raise last_err


# --------------------------- Core Flow ---------------------------

def scrape_and_filter_ai(unique_urls, assistant, instructions, resume_text):
    offset = 0
    new_data = [0]
    df = pd.DataFrame(columns=required_columns)

    while len(new_data) > 0:
        try:
            logging.info(f"Offset of scraping is: {offset}")
            new_data = scrape_all_jobs(
                os.getenv("sites"),
                os.getenv("search_term"),
                os.getenv("location"),
                os.getenv("hours_old"),
                os.getenv("results_wanted"),
                offset,
            )
            logging.info(f"{len(new_data)} jobs scraped ")
        except Exception as e:
            logging.error("An error occurred while scraping: %s", e)
            logging.error("Stack trace: %s", traceback.format_exc())
            new_data = pd.DataFrame(columns=required_columns)

        for index, row in tqdm(new_data.iterrows(), total=len(new_data), desc="Analyzing Jobs"):
            try:
                job_url = row.get("job_url", "")
                if job_url in unique_urls:
                    continue

                msg = format_prompt(
                    PERSONAL_JOB_FINDER_PROMPT,
                    title=row.get("title", ""),
                    description=row.get("description", ""),
                    resume_text=resume_text,
                )

                ai_response = send_with_retries(assistant, msg, tries=3, backoff_sec=1.5)
                logging.info("Ollama response received.")

                verdict, explanation, years_required = parse_json_response(ai_response)

                new_row = {
                    "AI_recommendation": verdict,
                    "company": row.get("company", ""),
                    "title": row.get("title", ""),
                    "link": job_url,
                    "years_required": years_required,
                    "description": row.get("description", ""),
                    "posted_date": row.get("date_posted", ""),
                }
                df.loc[len(df)] = new_row
                unique_urls.add(job_url)

            except Exception as e:
                logging.error("An error occurred while sending to AI: %s", e)
                logging.error("Stack trace: %s", traceback.format_exc())

        offset += len(new_data)
        # Break after first page if your scraper returns everything at once; remove this to paginate fully
        break

    return df


def main():
    load_env_file(".env")
    data = load_df()
    unique_urls = set(data["link"])
    # You can still keep instructions.txt if you use it elsewhere, but the prompt is now internal
    try:
        with open("instructions.txt", "r", encoding="utf-8") as file:
            instructions = file.read()
    except Exception:
        instructions = ""

    resume_text = load_resume_text(os.getenv("RESUME_PATH", "instructions.txt"))

    # Better default model for balanced reasoning on 4GB VRAM (with CPU spill if needed)
    assistant = OllamaAssistant(model=os.getenv("model", "gemma3:4b"))
    logging.info(f"Ollama Assistant ready using model: {assistant.model}")

    new_df = scrape_and_filter_ai(unique_urls, assistant, instructions, resume_text)
    df = pd.concat([data, new_df], ignore_index=True)
    written_path = write_excel_safely(df, excel_file)
    logging.info(f"Excel written to: {written_path}")


if __name__ == "__main__":
    main()
