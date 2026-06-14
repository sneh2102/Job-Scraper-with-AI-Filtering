"""
Resume Pipeline
==============
Reads jobs.xlsx, finds every row where AI_recommendation = "yes",
runs Resume Builder and ATS Checker in a feedback loop,
compiles PDFs and saves to outputs/Company/Position/

Usage:
    python pipeline.py
"""
import os
import re
import json
import logging
import time
import pandas as pd

from agents.api_client import RotatingOllamaClient
from agents.resume_builder import ResumeBuilderAgent
from agents.ats_checker import ATSCheckerAgent
from utils.latex_compiler import (
    compile_latex_to_pdf,
    save_cover_letter_pdf,
    is_pdflatex_available,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("pipeline")

MAX_ATS_ITERATIONS = 2
ATS_PASS_THRESHOLD = 85


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def load_env(path: str = ".env"):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()


def load_app_config() -> dict:
    try:
        if os.path.exists("app_config.json"):
            with open("app_config.json", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("Could not load app_config.json: %s", e)
    return {}


def collect_ollama_keys() -> list[str]:
    keys = []
    i = 1
    while True:
        key = os.getenv(f"OLLAMA_API_KEY_{i}")
        if not key:
            break
        keys.append(key)
        i += 1
    single = os.getenv("OLLAMA_API_KEY")
    if single and single not in keys:
        keys.append(single)
    if not keys:
        raise EnvironmentError("No OLLAMA_API_KEY_N entries found in .env")
    logger.info("Loaded %d Ollama API key(s).", len(keys))
    return keys


def load_text_file(path: str, label: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        logger.warning("Could not load %s at %s: %s", label, path, e)
        return ""


def sanitize_folder_name(name: str) -> str:
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name[:60] or "Unknown"


def build_output_path(base_dir: str, company: str, title: str, filename: str) -> str:
    return os.path.join(
        base_dir,
        sanitize_folder_name(company),
        sanitize_folder_name(title),
        filename,
    )


# ══════════════════════════════════════════════════════════════
# LATEX BODY EXTRACTION / REASSEMBLY
# ══════════════════════════════════════════════════════════════

def _extract_body(latex: str) -> dict:
    """
    Extract all sections from assembled LaTeX generically.
    Handles both standard sections and any custom sections.
    """
    from agents.resume_builder import LATEX_PREAMBLE, FIXED_HEADER, FIXED_EDUCATION

    body = latex.replace(LATEX_PREAMBLE, "").replace("\\end{document}", "").strip()

    all_matches = list(re.finditer(r'\\section\{([^}]+)\}', body))
    logger.info("Sections found: %s", [m.group(1) for m in all_matches])

    if not all_matches:
        return {
            "header": body, "education": "", "skills": "", "experience": "", "projects": ""
        }

    # Display name → section_id mapping (lowercase)
    name_to_id = {
        "education":       "education",
        "technical skills": "skills",
        "skills":           "skills",
        "experience":       "experience",
        "work experience":  "experience",
        "relevant projects": "projects",
        "projects":         "projects",
    }
    try:
        if os.path.exists("app_config.json"):
            with open("app_config.json", encoding="utf-8") as f:
                cfg_data = json.load(f)
            for cs in cfg_data.get("custom_sections", []):
                cs_id   = cs.get("id", "")
                cs_name = cs.get("name", "").lower()
                if cs_id and cs_name:
                    name_to_id[cs_name] = cs_id
    except Exception:
        pass

    header = body[:all_matches[0].start()].strip() or FIXED_HEADER

    sections: dict = {"header": header}
    for i, match in enumerate(all_matches):
        display = match.group(1)
        sec_id  = name_to_id.get(display.lower(), display.lower().replace(" ", "_"))
        end_idx = all_matches[i + 1].start() if i + 1 < len(all_matches) else len(body)
        sections[sec_id] = body[match.start():end_idx].strip()

    sections.setdefault("education",  FIXED_EDUCATION)
    sections.setdefault("skills",     "")
    sections.setdefault("experience", "")
    sections.setdefault("projects",   "")

    logger.info("Extracted section keys: %s", [k for k in sections if k != "header"])
    return sections


def _reassemble_latex(body: dict) -> str:
    """Reassemble LaTeX from sections, respecting section_order from app_config."""
    from agents.resume_builder import LATEX_PREAMBLE

    order = ["education", "skills", "experience", "projects"]
    try:
        if os.path.exists("app_config.json"):
            with open("app_config.json", encoding="utf-8") as f:
                cfg = json.load(f)
            saved_order = (
                cfg.get("section_order")
                or cfg.get("pipeline", {}).get("section_order", [])
            )
            if saved_order:
                order = list(saved_order)
    except Exception:
        pass

    # Append any custom section keys present in body that aren't in order
    base_keys = {"header", "education", "skills", "experience", "projects"}
    for key in body:
        if key not in base_keys and key not in order and body[key].strip():
            order.append(key)

    result = LATEX_PREAMBLE + "\n\n" + body.get("header", "")
    for key in order:
        content = body.get(key, "")
        if content:
            result += "\n\n" + content
    result += "\n\n\\end{document}"
    return result


# ══════════════════════════════════════════════════════════════
# CORE JOB PROCESSOR
# ══════════════════════════════════════════════════════════════

def process_job(row, builder, checker, output_base, use_pdflatex, use_jd_location=True, default_location="Canada",
                max_iterations: int = None, pass_threshold: int = None):
    _max_iter  = max_iterations if max_iterations is not None else MAX_ATS_ITERATIONS
    _threshold = pass_threshold if pass_threshold is not None else ATS_PASS_THRESHOLD

    best_score     = 0
    no_improve     = 0
    MAX_NO_IMPROVE = 2

    company     = str(row.get("company",     "Unknown_Company"))
    title       = str(row.get("title",       "Unknown_Position"))
    description = row.get("description",     "")

    if not description or str(description).strip() in ("nan", "None", ""):
        description = (
            f"Software engineering role at {company}. "
            f"Looking for a skilled developer with strong problem-solving skills."
        )
        logger.warning("No description for %s @ %s — using fallback", title, company)
    else:
        description = str(description).strip()

    logger.info("=" * 60)
    logger.info("Processing: %s @ %s", title, company)
    logger.info("=" * 60)

    latex, cover_letter = builder.build(
        title=title, company=company, description=description,
        location=str(row.get("location", "")),
                use_jd_location=use_jd_location, default_location=default_location    )

    ats_result  = {}
    final_score = 0

    for iteration in range(1, _max_iter + 1):
        logger.info("ATS iteration %d / %d", iteration, _max_iter)
        try:
            ats_result  = checker.check(title=title, description=description, latex=latex)
            final_score = ats_result["score"]
            sections    = ats_result.get("section_scores", {})

            logger.info(
                "ATS Score: %d/100 | Skills: %d | Exp: %d | Projects: %d | Pass: %s",
                final_score,
                sections.get("skills",     0),
                sections.get("experience", 0),
                sections.get("projects",   0),
                ats_result["pass"],
            )

            if ats_result.get("missing_keywords"):
                logger.info("Missing: %s", ", ".join(ats_result["missing_keywords"][:8]))

            if ats_result.get("pass") or final_score >= _threshold:
                logger.info("✅ ATS passed with score %d", final_score)
                break

            if iteration == _max_iter:
                logger.warning("Max iterations reached. Best score: %d", final_score)
                break

            sections_to_fix = ats_result.get("sections_to_rewrite", [])
            if not sections_to_fix:
                logger.info("No sections flagged — stopping early")
                break

            if final_score > best_score:
                best_score = final_score
                no_improve = 0
            else:
                no_improve += 1
                logger.warning("Score stuck (%d → %d). No-improve %d/%d",
                               best_score, final_score, no_improve, MAX_NO_IMPROVE)
                if no_improve >= MAX_NO_IMPROVE:
                    logger.warning("Stopping early — score stuck at %d", best_score)
                    break

            logger.info("Rebuilding sections: %s", sections_to_fix)
            body = _extract_body(latex)

            for section in sections_to_fix:
                feedback = ats_result.get(f"{section}_feedback", "")
                if not feedback or feedback == "Retry — JSON parse failed":
                    continue

                body_key = {
                    "skills": "skills", "experience": "experience", "projects": "projects"
                }.get(section, section)

                current_section_latex = body.get(body_key, "")
                logger.info("Rebuilding '%s' | feedback: %s", section, feedback[:100])

                new_section = builder.rebuild_section(
                    section=section,
                    title=title,
                    company=company,
                    description=description,
                    feedback=feedback,
                    current_latex=current_section_latex,
                )

                if new_section.strip():
                    body[body_key] = new_section
                else:
                    logger.warning("Rebuild of '%s' returned empty — keeping original", section)

            latex = _reassemble_latex(body)

        except Exception as e:
            logger.error("ATS iteration %d failed: %s", iteration, e)
            final_score = final_score or 70
            break

    if not latex:
        return {"company": company, "title": title, "score": 0, "status": "failed",
                "resume_path": "", "cover_path": ""}

    resume_name = os.getenv("RESUME_FILENAME",       "Resume")
    cover_name  = os.getenv("COVER_LETTER_FILENAME", "Cover_Letter")
    logger.info("Saving as: %s.pdf / %s.pdf", resume_name, cover_name)

    tex_path        = build_output_path(output_base, company, title, f"{resume_name}.tex")
    resume_pdf_path = build_output_path(output_base, company, title, f"{resume_name}.pdf")
    cover_pdf_path  = build_output_path(output_base, company, title, f"{cover_name}.pdf")

    os.makedirs(os.path.dirname(tex_path), exist_ok=True)
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(latex)

    resume_ok = compile_latex_to_pdf(latex, resume_pdf_path) if use_pdflatex else False
    cover_ok  = save_cover_letter_pdf(cover_letter, cover_pdf_path)

    return {
        "company":     company,
        "title":       title,
        "score":       final_score,
        "status":      "done" if resume_ok else "tex_only",
        "resume_path": resume_pdf_path if resume_ok else tex_path,
        "cover_path":  cover_pdf_path  if cover_ok  else cover_pdf_path.replace(".pdf", ".txt"),
    }


# ══════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════

def main(stop_event=None):
    global MAX_ATS_ITERATIONS, ATS_PASS_THRESHOLD

    load_env(".env")

    app_cfg  = load_app_config()
    pipe_cfg = app_cfg.get("pipeline", {})

    excel_path    = os.getenv("EXCEL_PATH",    pipe_cfg.get("excel_path",    "jobs.xlsx"))
    output_dir    = os.getenv("OUTPUT_DIR",    pipe_cfg.get("output_dir",    "outputs"))
    resume_path   = os.getenv("RESUME_PATH",   pipe_cfg.get("resume_path",   "resume.txt"))
    projects_path = os.getenv("PROJECTS_PATH", pipe_cfg.get("projects_path", "Projects.txt"))
    model         = os.getenv("MODEL",         app_cfg.get("model", {}).get("name", "gemma4:31b-cloud"))

    max_iterations = int(pipe_cfg.get("max_ats_iterations", 2))
    pass_threshold = int(pipe_cfg.get("ats_pass_threshold", 85))
    MAX_ATS_ITERATIONS = max_iterations
    ATS_PASS_THRESHOLD = pass_threshold
    logger.info("ATS config — max iterations: %d | pass threshold: %d",
                max_iterations, pass_threshold)

    resume_filename = pipe_cfg.get("resume_filename", "Resume")
    cover_filename  = pipe_cfg.get("cover_letter_filename", "Cover_Letter")
    os.environ["RESUME_FILENAME"]       = resume_filename
    os.environ["COVER_LETTER_FILENAME"] = cover_filename
    logger.info("Output filenames — resume: %s.pdf | cover: %s.pdf",
                resume_filename, cover_filename)

    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    config_keys = app_cfg.get("model", {}).get("api_keys", [])
    if config_keys:
        for i, key in enumerate(config_keys, 1):
            os.environ[f"OLLAMA_API_KEY_{i}"] = key

    api_keys = collect_ollama_keys()
    client   = RotatingOllamaClient(api_keys=api_keys, model=model)

    existing_resume = load_text_file(resume_path,   "resume")
    projects_text   = load_text_file(projects_path, "projects")

    builder = ResumeBuilderAgent(client, projects_text, existing_resume)
    checker = ATSCheckerAgent(client)

    use_pdflatex = is_pdflatex_available()
    if not use_pdflatex:
        logger.warning("pdflatex not found — resumes saved as .tex only")

    df       = pd.read_excel(excel_path, engine="openpyxl")
    yes_jobs = df[df["AI_recommendation"].str.lower() == "yes"].reset_index(drop=True)
    logger.info("Found %d jobs with verdict = yes", len(yes_jobs))

    if yes_jobs.empty:
        logger.info("Nothing to process.")
        return

    results = []
    for idx, row in yes_jobs.iterrows():
        if stop_event and stop_event.is_set():
            logger.info("🛑 Pipeline stopped by user.")
            break
        try:
            result = process_job(
                row, builder, checker, output_dir, use_pdflatex, use_jd_location=pipe_cfg.get("use_jd_location", True), 
                default_location=pipe_cfg.get("default_location", "Canada"),                max_iterations=max_iterations,
                pass_threshold=pass_threshold,
            )
            result["job_url"]  = str(row.get("link",     ""))
            result["location"] = str(row.get("location", ""))
            results.append(result)
            logger.info("[%d/%d] %s @ %s | Score: %s | Status: %s",
                        idx + 1, len(yes_jobs),
                        result["title"], result["company"],
                        result["score"], result["status"])
        except Exception as e:
            logger.error("Unhandled error on job %d: %s", idx, e)
            results.append({
                "company": row.get("company", ""),
                "title":   row.get("title",   ""),
                "score":   0, "status": "error",
            })
        time.sleep(1)

    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 60)
    for r in results:
        logger.info("%-45s | Score: %3s | %s",
                    f"{r['title']} @ {r['company']}"[:45],
                    r.get("score", "n/a"), r.get("status", "unknown"))
    passed = sum(1 for r in results if r.get("status") == "done")
    failed = sum(1 for r in results if r.get("status") in ("failed", "error", "tex_only"))
    logger.info("Done: %d | Failed: %d | Total: %d", passed, failed, len(results))
    logger.info("Output folder: %s", os.path.abspath(output_dir))


if __name__ == "__main__":
    main()