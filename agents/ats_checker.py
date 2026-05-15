# agents/ats_checker.py
import json
import re
import os
import time
import logging
import requests as _requests
from agents.api_client import RotatingOllamaClient

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# SYSTEM PROMPT — hardcoded, enforces JSON output contract
# ══════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """You are a Fortune 500 ATS system. Score the resume against the job description.
Return ONLY a JSON object — no backticks, no markdown, no explanation outside JSON.
Start your response with { and end with }.

OUTPUT FORMAT:
{
  "score": 75,
  "keyword_coverage_pct": 70,
  "pass": false,
  "total_jd_keywords": 20,
  "matched_keywords": 14,
  "missing_keywords": ["keyword1", "keyword2"],
  "section_scores": {"skills": 80, "experience": 70, "projects": 75},
  "sections_to_rewrite": ["experience"],
  "skills_feedback": "Add Terraform to Cloud. Add Datadog to Tools.",
  "experience_feedback": "TeleAI bullet 2: add event-driven metric.",
  "projects_feedback": "Replace weakest project with Kafka streaming project.",
  "cover_letter_feedback": "",
  "suggestions": ["Add Terraform", "Add CI/CD metrics", "Replace weakest project"]
}

SCORING RULES:
- Keyword Coverage 40pts: technical JD keywords found in resume (equivalents count)
  Postgres=SQL, React=Frontend, AWS=GCP, Docker=containers, K8s=orchestration
- Experience Alignment 25pts: max 8pt deduction for 3yr vs 5yr gap only
- Skills Section 20pts: skill categories mirror JD technical domains
- Impact/Metrics 15pts: quantified bullets score higher

IMPORTANT:
- Only count TECHNICAL skills as missing keywords — ignore soft skills, mission statements,
  company values (e.g. "Professional Networking", "Economic Opportunity" are NOT missing keywords)
- sections_to_rewrite: only include sections scoring below 75
- feedback fields: plain English ONLY, no LaTeX, no backslashes"""

# ══════════════════════════════════════════════════════════════
# DEFAULT USER PROMPT
# ══════════════════════════════════════════════════════════════

_DEFAULT_USER_PROMPT = """Score this resume against the job. Pass = 85+.

JOB TITLE: {title}

JOB DESCRIPTION:
{description}

RESUME (plain text):
{latex}

Focus ONLY on technical skills when listing missing_keywords.
Ignore soft skills and company mission statements.
Return ONLY the JSON object."""


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def _load_ats_prompt() -> str:
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app_config.json"
    )
    try:
        if os.path.exists(config_path):
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            p = data.get("prompts", {}).get("ats_checker", "")
            if p:
                return p
    except Exception as e:
        logger.warning("Could not load ATS prompt: %s", e)
    return _DEFAULT_USER_PROMPT


def _smart_trim(text: str) -> str:
    """
    Keep all section headers and first 3 bullets per role/project.
    Ensures ALL sections (including Projects) are always included.
    Never cuts off at a fixed character limit.
    """
    lines        = text.split("\n")
    result       = []
    bullet_count = 0

    for line in lines:
        stripped = line.strip()

        # Always keep section headers
        if stripped.startswith("=== ") and stripped.endswith(" ==="):
            result.append(line)
            bullet_count = 0
            continue

        # Keep role/project headings (e.g. "Nova Scotia Health, Support Consultant (Feb 2026)")
        if stripped.startswith("Project:") or (
            len(stripped) < 120 and
            "," in stripped and
            "(" in stripped and
            not stripped.startswith("-")
        ):
            result.append(line)
            bullet_count = 0
            continue

        # Keep first 3 bullets per role/project
        if stripped.startswith("- "):
            if bullet_count < 3:
                result.append(line)
            bullet_count += 1
            continue

        # Keep everything else (skills lines, empty lines, etc.)
        if stripped:
            result.append(line)
        elif result and result[-1] != "":
            result.append("")  # preserve paragraph breaks

    trimmed = "\n".join(result)

    # Safety limit
    if len(trimmed) > 5000:
        trimmed = trimmed[:5000] + "\n... [trimmed]"

    return trimmed


# ══════════════════════════════════════════════════════════════
# ATS CHECKER AGENT
# ══════════════════════════════════════════════════════════════

class ATSCheckerAgent:
    def __init__(self, client: RotatingOllamaClient):
        self.client = client

    def check(self, title: str, description: str, latex: str) -> dict:
        logger.info("ATS checker: scoring resume for '%s'", title)

        plain_resume = self._latex_to_text(latex)
        desc_trimmed = description[:1200] if len(description) > 1200 else description
        user_prompt  = _load_ats_prompt()

        # Safe string replacement — never breaks on JSON braces in prompt
        formatted_user = (
            user_prompt
            .replace("{title}",       str(title))
            .replace("{description}", str(desc_trimmed))
            .replace("{latex}",       str(plain_resume))
        )

        logger.info("ATS input sizes — resume: %d chars | desc: %d chars",
                    len(plain_resume), len(desc_trimmed))

        # ── Retry loop — 3 attempts with backoff ─────────────
        for attempt in range(1, 4):
            try:
                if attempt > 1:
                    wait = attempt * 2
                    logger.info("ATS retry %d/3 — waiting %ds...", attempt, wait)
                    time.sleep(wait)
                else:
                    time.sleep(0.3)

                response = self._direct_http(
                    system=_SYSTEM_PROMPT,
                    user=formatted_user,
                    api_key=self.client.api_keys[self.client.current_index],
                    model=self.client.model,
                )

                logger.info("ATS raw response [%d chars]: %s",
                            len(response), response[:150])

                if not response or len(response.strip()) < 10:
                    logger.warning("ATS attempt %d: empty/short response", attempt)
                    continue

                stripped = response.strip()
                if "{" not in stripped or "}" not in stripped:
                    logger.warning("ATS attempt %d: no JSON found — response: %s",
                                   attempt, stripped[:80])
                    continue

                result = self._parse(response)
                if result["score"] > 0:
                    logger.info("ATS attempt %d succeeded — score: %d",
                                attempt, result["score"])
                    return result

                logger.warning("ATS attempt %d: score=0 after parse", attempt)

            except Exception as e:
                err_str = str(e)
                logger.warning("ATS attempt %d failed: %s", attempt, err_str[:100])

                # Rotate key on rate limit
                if any(x in err_str.lower() for x in ["429", "401", "403", "rate"]):
                    idx = (self.client.current_index + 1) % len(self.client.api_keys)
                    self.client.current_index = idx
                    self.client._build_client()
                    logger.info("Rotated to key index %d", idx)

        logger.warning("ATS: all 3 attempts failed — fallback score 70")
        return self._fallback(70)

    # ── Direct HTTP — bypasses Ollama Python library ──────────
    def _direct_http(self, system: str, user: str,
                     api_key: str, model: str) -> str:
        """
        Direct requests call to Ollama API.
        Bypasses the Ollama Python library which raises partial
        JSON responses as exceptions for structured outputs.
        """
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "stream": False,
            "options": {
                "num_predict": 1024,
                "temperature": 0.1,
                "num_ctx":     8192,
            },
        }

        resp = _requests.post(
            "https://ollama.com/api/chat",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            timeout=90,
        )

        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}: {resp.text[:150]}")

        data    = resp.json()
        content = data.get("message", {}).get("content", "")

        if not content:
            raise Exception(f"Empty content in response. Keys: {list(data.keys())}")

        return content.strip()

    # ── LaTeX → plain text ─────────────────────────────────────
    @staticmethod
    def _latex_to_text(latex: str) -> str:
        """
        Convert LaTeX resume to clean plain text.
        Reduces ~9000 char LaTeX to ~2000 chars while preserving
        ALL sections including Projects.
        """
        # Skip preamble, start from content
        body = latex
        for marker in ["\\begin{center}", "\\section{"]:
            idx = latex.find(marker)
            if idx > 0:
                body = latex[idx:]
                break

        text = body

        # Preserve content inside commands
        text = re.sub(r'\\textbf\{([^}]+)\}',    r'\1', text)
        text = re.sub(r'\\textit\{([^}]+)\}',    r'\1', text)
        text = re.sub(r'\\emph\{([^}]+)\}',      r'\1', text)
        text = re.sub(r'\\underline\{([^}]+)\}', r'\1', text)
        text = re.sub(r'\\small\{([^}]+)\}',     r'\1', text)
        text = re.sub(r'\\href\{[^}]+\}\{([^}]+)\}', r'\1', text)

        # Section headers → readable markers
        text = re.sub(r'\\section\{([^}]+)\}', r'\n\n=== \1 ===\n', text)

        # Resume items → bullet points
        text = re.sub(
            r'\\resumeItem\{((?:[^{}]|\{[^{}]*\})*)\}',
            r'- \1', text
        )

        # Job headings → readable format
        text = re.sub(
            r'\\resumeSubheading\{([^}]+)\}\{([^}]+)\}\{([^}]+)\}\{([^}]+)\}',
            r'\3, \1 (\2)', text
        )

        # Project headings
        text = re.sub(
            r'\\resumeProjectHeading\{([^}]+)\}\{([^}]+)\}',
            r'Project: \1 (\2)', text
        )

        # Remove all remaining LaTeX commands
        text = re.sub(r'\\[a-zA-Z]+\*?\{[^}]*\}', ' ', text)
        text = re.sub(r'\\[a-zA-Z]+\*?',           ' ', text)
        text = re.sub(r'\{|\}',                     ' ', text)
        text = re.sub(r'\$[^$]*\$',                 ' ', text)
        text = re.sub(r'\$|\[|\]',                  ' ', text)

        # Clean whitespace
        text = re.sub(r'[ \t]+',   ' ',   text)
        text = re.sub(r'\n{3,}', '\n\n',  text)
        text = text.strip()

        # Smart trim — keeps all sections, limits bullets per role
        if len(text) > 2500:
            text = _smart_trim(text)

        return text

    # ── Fallback ──────────────────────────────────────────────
    @staticmethod
    def _fallback(score: int = 70) -> dict:
        return {
            "score":                score,
            "keyword_coverage_pct": 55,
            "pass":                 score >= 85,
            "total_jd_keywords":    0,
            "matched_keywords":     0,
            "missing_keywords":     [],
            "section_scores":       {
                "skills":     score,
                "experience": score,
                "projects":   score,
            },
            "sections_to_rewrite":  [],
            "skills_feedback":      "",
            "experience_feedback":  "",
            "projects_feedback":    "",
            "cover_letter_feedback": "",
            "suggestions":          [],
        }

    # ── JSON parser ───────────────────────────────────────────
    @staticmethod
    def _parse(text: str) -> dict:
        if not text or len(text.strip()) < 5:
            return ATSCheckerAgent._fallback(70)

        txt = text.strip()

        # Strip markdown fences
        if "```" in txt:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", txt, re.IGNORECASE)
            if m:
                txt = m.group(1).strip()

        # Extract JSON object boundaries
        start = txt.find("{")
        end   = txt.rfind("}")
        if start != -1 and end > start:
            txt = txt[start:end + 1]

        # Fix trailing commas
        txt = re.sub(r",\s*([}\]])", r"\1", txt)

        # Strategy 1: direct parse
        try:
            return ATSCheckerAgent._build(json.loads(txt))
        except Exception:
            pass

        # Strategy 2: sanitize backslashes then parse
        try:
            return ATSCheckerAgent._build(
                json.loads(ATSCheckerAgent._sanitize(txt))
            )
        except Exception:
            pass

        # Strategy 3: regex extraction
        logger.warning("ATS: JSON parse failed — using regex extraction")
        return ATSCheckerAgent._regex_extract(text)

    @staticmethod
    def _build(data: dict) -> dict:
        score = int(data.get("score", 70))
        return {
            "score":                score,
            "keyword_coverage_pct": int(data.get("keyword_coverage_pct", 0)),
            "pass":                 bool(data.get("pass", False)) or score >= 85,
            "total_jd_keywords":    int(data.get("total_jd_keywords", 0)),
            "matched_keywords":     int(data.get("matched_keywords", 0)),
            "missing_keywords":     data.get("missing_keywords", []),
            "section_scores":       data.get("section_scores", {}),
            "sections_to_rewrite":  data.get("sections_to_rewrite", []),
            "skills_feedback":      str(data.get("skills_feedback",      "")),
            "experience_feedback":  str(data.get("experience_feedback",  "")),
            "projects_feedback":    str(data.get("projects_feedback",    "")),
            "cover_letter_feedback":str(data.get("cover_letter_feedback","")),
            "suggestions":          data.get("suggestions", []),
        }

    @staticmethod
    def _regex_extract(text: str) -> dict:
        def get_int(pat, default=0):
            m = re.search(pat, text)
            return int(m.group(1)) if m else default

        def get_str(pat, default=""):
            m = re.search(pat, text, re.DOTALL)
            return m.group(1).strip() if m else default

        def get_list(pat):
            m = re.search(pat, text, re.DOTALL)
            return re.findall(r'"([^"]+)"', m.group(1)) if m else []

        score = get_int(r'"score"\s*:\s*(\d+)', 0)
        return {
            "score":                score,
            "keyword_coverage_pct": get_int(r'"keyword_coverage_pct"\s*:\s*(\d+)', 0),
            "pass":                 score >= 85,
            "total_jd_keywords":    get_int(r'"total_jd_keywords"\s*:\s*(\d+)', 0),
            "matched_keywords":     get_int(r'"matched_keywords"\s*:\s*(\d+)', 0),
            "missing_keywords":     get_list(r'"missing_keywords"\s*:\s*\[([^\]]*)\]'),
            "section_scores": {
                "skills":     get_int(r'"skills"\s*:\s*(\d+)',     score),
                "experience": get_int(r'"experience"\s*:\s*(\d+)', score),
                "projects":   get_int(r'"projects"\s*:\s*(\d+)',   score),
            },
            "sections_to_rewrite":  get_list(r'"sections_to_rewrite"\s*:\s*\[([^\]]*)\]'),
            "skills_feedback":      get_str(r'"skills_feedback"\s*:\s*"([^"]*)"',     ""),
            "experience_feedback":  get_str(r'"experience_feedback"\s*:\s*"([^"]*)"', ""),
            "projects_feedback":    get_str(r'"projects_feedback"\s*:\s*"([^"]*)"',   ""),
            "cover_letter_feedback": "",
            "suggestions":          get_list(r'"suggestions"\s*:\s*\[([^\]]*)\]'),
        }

    @staticmethod
    def _sanitize(s: str) -> str:
        result = []
        in_str = False
        i = 0
        while i < len(s):
            c = s[i]
            if c == '"' and (i == 0 or s[i-1] != '\\'):
                in_str = not in_str
                result.append(c)
            elif in_str and c == '\\':
                nxt = s[i+1] if i+1 < len(s) else ''
                if nxt in ('"', '\\', 'n', 'r', 't', 'b', 'f', '/', 'u'):
                    result.append(c)
                else:
                    result.append('\\\\')
            else:
                result.append(c)
            i += 1
        return ''.join(result)