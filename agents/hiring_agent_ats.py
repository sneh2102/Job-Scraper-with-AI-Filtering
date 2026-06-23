# agents/hiring_agent_ats.py
"""
Drop-in replacement for ATSCheckerAgent that uses the hiring-agent's
holistic resume-quality evaluation criteria (self projects, production
experience, technical skills) instead of job-specific ATS scoring.

Each category returns both `evidence` (what's there) and `feedback`
(specific rewrite instructions the resume builder can act on).

Model: gemma4:31b-cloud (Ollama cloud).
"""

import json
import re
import logging
import time
import requests as _requests
from agents.api_client import RotatingOllamaClient

logger = logging.getLogger(__name__)

# ── System message ───────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are an expert technical recruiter evaluating resumes. Provide accurate, objective evaluations based on the given criteria.

**CRITICAL: You are NOT writing a resume summary. You are SCORING a resume.**

**SCORES MUST NEVER DEPEND ON:**
- Candidate's name, gender, or personal demographic information
- College, university, or educational institution name
- CGPA, GPA, or academic grades
- City, location, or geographical information

**EVALUATION MUST BE BASED ONLY ON:**
- Technical skills and programming languages
- Project complexity and real-world impact
- Work experience and production-level contributions
- Problem-solving demonstrated in projects

**MANDATORY: You MUST always fill ALL THREE categories: self_projects, production, technical_skills.**

- For self_projects: Assess project complexity and impact. Simple tutorial projects (todo lists, calculators, basic CRUD apps) should receive LOW SCORES. Complex projects with real-world impact, multiple technologies, or measurable outcomes should receive HIGH SCORES.

- For production: Analyze work and volunteer sections for real-world, internship, or production experience. Give extra points for founder roles or early-stage engineer roles at startups.

- For technical_skills: Analyze skills sections and evidence of technical breadth or problem-solving in projects, work, or competitions.

**FEEDBACK FIELD RULES** (CRITICAL):
For each score category write a `feedback` string with SPECIFIC, ACTIONABLE rewrite instructions:
- Name the EXACT bullet, role, or project to change (e.g. "TeleAI bullet 2", "Post-Quantum project")
- Say EXACTLY what to add, remove, or rewrite (e.g. "Add throughput metric like 50,000 req/sec")
- Use imperative language: Add / Replace / Rewrite / Remove
- If the section already scores 90%+ of its max, write: "Section is strong — no major rewrites needed."

Respond with ONLY valid JSON. No other text.

{
    "scores": {
        "self_projects":    {"score": 0, "max": 45, "evidence": "what is present and why", "feedback": "specific rewrite instructions"},
        "production":       {"score": 0, "max": 40, "evidence": "what is present and why", "feedback": "specific rewrite instructions"},
        "technical_skills": {"score": 0, "max": 15, "evidence": "what is present and why", "feedback": "specific rewrite instructions"}
    },
    "bonus_points": {"total": 0, "breakdown": "string"},
    "deductions":   {"total": 0, "reasons": "string"},
    "key_strengths":         ["strength1", "strength2"],
    "areas_for_improvement": ["improvement1", "improvement2"]
}"""

# ── User prompt template ─────────────────────────────────────────────────────

_USER_PROMPT_TEMPLATE = """Evaluate this resume and score it across three categories. For each category provide both evidence (what you found) and feedback (specific rewrite instructions).

## SCORING

### Self Projects (0-45 points)
- HIGH (30-45): Complex, real-world projects with measurable outcomes, multiple technologies
- MEDIUM (15-29): Moderate complexity, good documentation, multiple features
- LOW (1-14): Simple tutorial projects (todo lists, calculators, basic CRUD, weather apps)
- ZERO: No projects or only extremely basic ones

### Production Experience (0-40 points)
Score work/volunteer sections. Give extra credit for startup founder/early engineer roles.

### Technical Skills (0-15 points)
Score breadth and depth of technical skills demonstrated.

## BONUS (max 20 pts)
+5 GSoC, +3-5 startup founder/co-founder, +2 portfolio website, +1 LinkedIn profile.

## DEDUCTIONS
-2 to -5 if only tutorial projects. -3 to -5 per project without any link.

## FEEDBACK INSTRUCTIONS
feedback must be SPECIFIC:
- BAD: "Improve the projects section"
- GOOD: "Replace the Weather App project with a Kafka streaming pipeline. Add a throughput metric (e.g. 10,000 events/sec) to the TeleAI bullet 2. Add live demo links to Post-Quantum and QRNG projects."

Return ONLY this JSON (no markdown, no extra text):

{{
    "scores": {{
        "self_projects":    {{"score": 0, "max": 45, "evidence": "string", "feedback": "specific instructions"}},
        "production":       {{"score": 0, "max": 40, "evidence": "string", "feedback": "specific instructions"}},
        "technical_skills": {{"score": 0, "max": 15, "evidence": "string", "feedback": "specific instructions"}}
    }},
    "bonus_points": {{"total": 0, "breakdown": "string"}},
    "deductions":   {{"total": 0, "reasons": "string"}},
    "key_strengths":         ["strength1", "strength2"],
    "areas_for_improvement": ["improvement1", "improvement2"]
}}

Resume to evaluate:

{resume_text}"""


# ══════════════════════════════════════════════════════════════
# HIRING AGENT ATS CHECKER
# ══════════════════════════════════════════════════════════════

class HiringAgentATSChecker:
    """
    Evaluates a resume using the hiring-agent's holistic quality rubric.
    Implements the same .check() interface as ATSCheckerAgent so it can
    be swapped in without changing pipeline.py's call sites.

    Each returned dict includes *_feedback keys with specific rewrite
    instructions the ResumeBuilderAgent can act on directly.
    """

    def __init__(self, client: RotatingOllamaClient):
        self.client = client

    def check(self, title: str, description: str, latex: str) -> dict:
        logger.info("HiringAgentATS: evaluating resume quality for '%s'", title)
        plain_text = self._latex_to_text(latex)

        for attempt in range(1, 4):
            try:
                if attempt > 1:
                    wait = attempt * 2
                    logger.info("HiringAgentATS retry %d/3 — waiting %ds…", attempt, wait)
                    time.sleep(wait)
                else:
                    time.sleep(0.3)

                raw = self._call_api(plain_text)

                if not raw or len(raw.strip()) < 10:
                    logger.warning("HiringAgentATS attempt %d: empty response", attempt)
                    continue

                eval_data = self._parse_response(raw)
                result    = self._map_to_ats_format(eval_data)

                if result["score"] > 0:
                    logger.info(
                        "HiringAgentATS attempt %d OK — score: %d | pass: %s",
                        attempt, result["score"], result["pass"],
                    )
                    # Log feedback so it appears in the pipeline log
                    for key in ("skills_feedback", "experience_feedback", "projects_feedback"):
                        fb = result.get(key, "")
                        if fb:
                            logger.info("  %s: %s", key, fb[:120])
                    return result

                logger.warning("HiringAgentATS attempt %d: score=0 after parse", attempt)

            except Exception as exc:
                err = str(exc)
                logger.warning("HiringAgentATS attempt %d failed: %s", attempt, err[:100])
                if any(x in err.lower() for x in ["429", "401", "403", "rate"]):
                    idx = (self.client.current_index + 1) % len(self.client.api_keys)
                    self.client.current_index = idx
                    self.client._build_client()
                    logger.info("Rotated to key index %d", idx)

        logger.warning("HiringAgentATS: all attempts failed — fallback score 70")
        return self._fallback(70)

    # ── Internal ───────────────────────────────────────────────

    def _call_api(self, resume_text: str) -> str:
        user_msg = _USER_PROMPT_TEMPLATE.format(resume_text=resume_text)
        payload  = {
            "model": self.client.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "num_predict": 2048,
                "temperature": 0.1,
                "num_ctx":     16384,
            },
        }
        api_key = self.client.api_keys[self.client.current_index]
        resp = _requests.post(
            "https://ollama.com/api/chat",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            timeout=120,
        )
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}: {resp.text[:150]}")
        data    = resp.json()
        content = data.get("message", {}).get("content", "")
        if not content:
            raise Exception(f"Empty content. Keys: {list(data.keys())}")
        return content.strip()

    @staticmethod
    def _parse_response(text: str) -> dict:
        txt = text.strip()
        if "<think>" in txt:
            end = txt.find("</think>")
            if end != -1:
                txt = txt[end + 8:]
        if "```" in txt:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", txt, re.IGNORECASE)
            if m:
                txt = m.group(1).strip()
        start = txt.find("{")
        end   = txt.rfind("}")
        if start != -1 and end > start:
            txt = txt[start:end + 1]
        txt = re.sub(r",\s*([}\]])", r"\1", txt)
        try:
            return json.loads(txt)
        except Exception:
            logger.warning("HiringAgentATS: JSON parse failed on raw text")
            return {}

    @staticmethod
    def _map_to_ats_format(eval_data: dict) -> dict:
        if not eval_data:
            return HiringAgentATSChecker._fallback(70)

        scores     = eval_data.get("scores", {})
        bonus      = float(eval_data.get("bonus_points", {}).get("total", 0))
        deductions = float(eval_data.get("deductions",   {}).get("total", 0))

        self_proj = float(scores.get("self_projects",    {}).get("score", 0))
        prod      = float(scores.get("production",       {}).get("score", 0))
        tech      = float(scores.get("technical_skills", {}).get("score", 0))

        # Max possible: 45 + 40 + 15 + 20 bonus = 120
        raw_total  = self_proj + prod + tech + bonus - deductions
        raw_total  = max(0.0, min(120.0, raw_total))
        normalized = int(round((raw_total / 120.0) * 100))

        # Per-section 0-100 scores
        skills_pct = int(round((tech      / 15.0) * 100))
        exp_pct    = int(round((prod      / 40.0) * 100))
        proj_pct   = int(round((self_proj / 45.0) * 100))

        section_scores = {
            "skills":     min(100, skills_pct),
            "experience": min(100, exp_pct),
            "projects":   min(100, proj_pct),
        }

        sections_to_rewrite = [k for k, v in section_scores.items() if v < 75]

        improvements = eval_data.get("areas_for_improvement", [])

        # Use `feedback` (actionable instructions) as the rebuild prompt,
        # falling back to `evidence` if feedback wasn't returned.
        def _get_feedback(cat: str) -> str:
            cat_data = scores.get(cat, {})
            fb = cat_data.get("feedback", "").strip()
            if not fb or fb.lower().startswith("section is strong"):
                return cat_data.get("evidence", "")
            return fb

        skills_fb  = _get_feedback("technical_skills")
        exp_fb     = _get_feedback("production")
        proj_fb    = _get_feedback("self_projects")

        if improvements:
            improvement_text = "\n\nAdditional improvements:\n- " + "\n- ".join(improvements)
            if "skills" in sections_to_rewrite:
                skills_fb += improvement_text
            if "experience" in sections_to_rewrite:
                exp_fb += improvement_text
            if "projects" in sections_to_rewrite:
                proj_fb += improvement_text

        return {
            "score":                normalized,
            "keyword_coverage_pct": skills_pct,
            "pass":                 normalized >= 85,
            "total_jd_keywords":    0,
            "matched_keywords":     0,
            "missing_keywords":     [],
            "section_scores":       section_scores,
            "sections_to_rewrite":  sections_to_rewrite,
            "skills_feedback":      skills_fb,
            "experience_feedback":  exp_fb,
            "projects_feedback":    proj_fb,
            "cover_letter_feedback": "",
            "suggestions":          improvements,
        }

    @staticmethod
    def _latex_to_text(latex: str) -> str:
        """Convert LaTeX resume to plain text."""
        body = latex
        for marker in ["\\begin{center}", "\\section{"]:
            idx = latex.find(marker)
            if idx > 0:
                body = latex[idx:]
                break

        text = body
        text = re.sub(r'\\textbf\{([^}]+)\}',    r'\1', text)
        text = re.sub(r'\\textit\{([^}]+)\}',    r'\1', text)
        text = re.sub(r'\\emph\{([^}]+)\}',      r'\1', text)
        text = re.sub(r'\\underline\{([^}]+)\}', r'\1', text)
        text = re.sub(r'\\small\{([^}]+)\}',     r'\1', text)
        text = re.sub(r'\\href\{[^}]+\}\{([^}]+)\}', r'\1', text)
        text = re.sub(r'\\section\{([^}]+)\}',   r'\n\n=== \1 ===\n', text)
        text = re.sub(r'\\resumeItem\{((?:[^{}]|\{[^{}]*\})*)\}', r'- \1', text)
        text = re.sub(
            r'\\resumeSubheading\{([^}]+)\}\{([^}]+)\}\{([^}]+)\}\{([^}]+)\}',
            r'\3, \1 (\2)', text)
        text = re.sub(
            r'\\resumeProjectHeading\{([^}]+)\}\{([^}]+)\}',
            r'Project: \1 (\2)', text)
        text = re.sub(r'\\[a-zA-Z]+\*?\{[^}]*\}', ' ', text)
        text = re.sub(r'\\[a-zA-Z]+\*?',           ' ', text)
        text = re.sub(r'\{|\}',                     ' ', text)
        text = re.sub(r'\$[^$]*\$',                 ' ', text)
        text = re.sub(r'\$|\[|\]',                  ' ', text)
        text = re.sub(r'[ \t]+',   ' ',   text)
        text = re.sub(r'\n{3,}', '\n\n',  text)
        return text.strip()

    @staticmethod
    def _fallback(score: int = 70) -> dict:
        return {
            "score":                score,
            "keyword_coverage_pct": 55,
            "pass":                 score >= 85,
            "total_jd_keywords":    0,
            "matched_keywords":     0,
            "missing_keywords":     [],
            "section_scores":       {"skills": score, "experience": score, "projects": score},
            "sections_to_rewrite":  [],
            "skills_feedback":      "",
            "experience_feedback":  "",
            "projects_feedback":    "",
            "cover_letter_feedback": "",
            "suggestions":          [],
        }
