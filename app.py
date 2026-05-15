"""
JobHunter — Windows Desktop Application
========================================
pip install customtkinter pillow
python app.py
"""
import sys
import os

# Fix paths when running as PyInstaller exe
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

os.chdir(BASE_DIR)
CONFIG_FILE = os.path.join(BASE_DIR, "app_config.json")
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
import threading
import queue
import json
import os
import sys
import logging
import time
from datetime import datetime
from pathlib import Path
from setup_wizard import check_and_run_setup, ProfileTab, load_profile

# ── App theme ─────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

CONFIG_FILE = "app_config.json"

# ══════════════════════════════════════════════════════════════
# PASTE THIS INTO app.py — REPLACE THE ENTIRE DEFAULT_CONFIG
# ══════════════════════════════════════════════════════════════

DEFAULT_CONFIG = {
    "scraper": {
        "sites": "indeed,glassdoor,jobright",
        "search_term": "Software Developer",
        "location": "Canada",
        "country_indeed": "canada",
        "hours_old": "72",
        "results_wanted": "20",
        "is_remote": False,
    },
    "model": {
        "name": "gemma4:31b-cloud",
        "api_keys": [],
        "use_cloud": True,
        "num_predict": 16384,
        "num_ctx": 32768,
        "temperature": 0.3,
    },
    "pipeline": {
        "max_ats_iterations": 3,
        "ats_pass_threshold": 85,
        "output_dir": "outputs",
        "excel_path": "jobs.xlsx",
        "resume_path": "resume.txt",
        "projects_path": "Projects.txt",
        "resume_filename": "Sneh_Resume",
        "cover_letter_filename": "Sneh_Cover_Letter",
    },
    "google": {
        "enabled": False,
        "spreadsheet_id": "",
        "drive_folder": "Job Applications",
        "sheet_tab": "Sheet1",
    },
    "prompts": {

# ══════════════════════════════════════════════════════════════
# PROMPT 1: JOB SCREENER
# ══════════════════════════════════════════════════════════════
"job_screener": """You are a ruthless but contextually aware IT job screener.
Your job is to evaluate whether Sneh Patel should apply to this position.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CANDIDATE PROFILE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Name:       Sneh Patel
Experience: ~3 years (internships + full-time combined)
Education:  Master of Applied Computer Science — Dalhousie University (2025)
            B.Tech Computer Engineering — GTU India (2023)
Location:   Halifax, NS, Canada — open to Remote, Hybrid, Relocation across Canada
Core Stack: Python, Java, TypeScript, JavaScript, React, Next.js, Node.js, FastAPI,
            AWS, GCP, Docker, Kubernetes, PostgreSQL, MongoDB, Redis,
            LangChain, Terraform, Apache Kafka, Spark, Airflow
Domains:    Full-Stack Development, Cloud/DevOps, Data Engineering,
            AI/ML Integration, IT Support, Systems Analysis, Cybersecurity

STRONG FIT FOR:
- Software Developer / Engineer (any stack)
- Full Stack Developer
- Backend / Frontend Developer
- Data Engineer / Analyst
- Cloud / DevOps Engineer
- AI / ML Engineer
- IT Support / Systems Analyst
- Junior to Mid-level roles (0-5 years required)

NOT A FIT FOR:
- Pure Manual QA / Testing (no coding)
- Hardware / Embedded / FPGA Engineering
- Marketing, Sales, HR, Finance, Non-technical
- Roles requiring 6+ years experience
- Roles requiring specific certifications Sneh doesn't have (PMP, CPA, etc.)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INPUTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JOB TITLE: {title}
JOB DESCRIPTION: {description}
RESUME SUMMARY: {resume_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EVALUATION STEPS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 1 — DOMAIN CHECK
Accept if role is in: Software Dev, Data Eng, Cloud, DevOps, AI/ML, IT Support, Cybersecurity.
Reject immediately (verdict=no) if: Marketing, HR, Sales, Manual QA, Hardware, non-technical.

STEP 2 — EXPERIENCE CHECK
Extract required years from JD ("X+ years", "minimum X", "X-Y years experience").
0-4 yrs → PASS | 5 yrs → BORDERLINE | 6+ yrs → FAIL | Not mentioned → NEUTRAL
LIBERAL RULE: If candidate has equivalent project/academic experience, give benefit of doubt.

STEP 3 — SKILLS MATCH (BE LIBERAL WITH EQUIVALENTS)
List every technical skill/tool/framework in the JD.
Count each as matched if Sneh has it OR a clear equivalent:
  PostgreSQL ≈ MySQL ≈ SQL | AWS ≈ GCP ≈ Azure | React ≈ Vue ≈ Angular
  Docker ≈ containerization | Kubernetes ≈ container orchestration
score = matched / total_jd_skills * 100
70%+ = Strong | 45-69% = Partial | <45% = Weak

STEP 4 — SENIORITY CALIBRATION
Junior/Entry/Associate/New Grad → BONUS (raise verdict one level if borderline)
Mid/Intermediate/no label → NEUTRAL
Senior/Lead/Staff/Principal/Manager → PENALTY (lower verdict one level)

STEP 5 — FINAL VERDICT
PASS + Strong + Any → yes
PASS + Partial + Junior/Mid → yes
PASS + Partial + Senior → maybe
PASS + Weak + Junior → maybe
PASS + Weak + Mid/Senior → no
BORDERLINE + Strong + Junior/Mid → maybe
BORDERLINE + anything else → no
FAIL + anything → no

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT — return ONLY valid JSON, no markdown, no backticks
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{"verdict": "yes or maybe or no", "years_required": "number or range", "role_level": "junior or mid or senior", "skills_match_pct": 75, "matched_skills": ["Python", "React"], "missing_skills": ["Go", "Terraform"], "reasoning": "Strong match on full-stack skills. Missing Terraform but compensated by Docker/K8s experience."}""",

# ══════════════════════════════════════════════════════════════
# PROMPT 2: SKILLS SECTION
# ══════════════════════════════════════════════════════════════
"skills_section": """You are an expert resume writer specializing in ATS optimization.
Output ONLY raw LaTeX for the Technical Skills section.
NO \\documentclass, NO \\usepackage, NO \\begin{{document}}, NO \\end{{document}}.
Output ONLY the \\section{{Technical Skills}} block — nothing else.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JOB TITLE:   {title}
COMPANY:     {company}
JOB DESCRIPTION:
{description}

CANDIDATE'S EXISTING SKILLS (from resume):
{existing_resume}

ATS FEEDBACK FROM PREVIOUS ATTEMPT (MUST address every point):
{ats_feedback}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Read the JD carefully. Extract EVERY distinct technical skill, tool, framework, platform, methodology mentioned.
2. Map each JD keyword to the candidate's existing skills.
3. Create 5-6 categories that match JD domain terminology exactly.
4. FRONT-LOAD: Put the most JD-relevant keywords FIRST in each category.
5. Include JD-specific tools even if candidate used equivalents (show both if possible).
6. Category names should mirror JD language (e.g. if JD says "Cloud Infrastructure" use that, not "Cloud").

CATEGORY EXAMPLES BY DOMAIN:
- Languages: Python, Java, TypeScript, JavaScript, Go, SQL, Bash
- Frontend: React, Next.js, TypeScript, HTML5, CSS3, Tailwind CSS
- Backend: Node.js, FastAPI, Spring Boot, REST APIs, GraphQL, Microservices
- Cloud & DevOps: AWS (EC2, S3, Lambda, RDS), Docker, Kubernetes, Terraform, CI/CD, GitHub Actions
- Data & AI: PostgreSQL, MongoDB, Redis, Apache Kafka, Spark, LangChain, pandas, scikit-learn
- Tools: Git, JIRA, Linux, VS Code, Postman, Jupyter

RULES:
- All % → \\%, all & → \\&
- No special chars: no ->, no <>, no em dashes
- Use exact JD terminology where possible
- 8-12 items per category maximum

OUTPUT FORMAT:
\\section{{Technical Skills}}
 \\begin{{itemize}}[leftmargin=0.15in, label={{}}]
    \\small{{\\item{{
     \\textbf{{[Category 1]}}{{: tool1, tool2, tool3, tool4}} \\\\
     \\textbf{{[Category 2]}}{{: tool1, tool2, tool3, tool4}} \\\\
     \\textbf{{[Category 3]}}{{: tool1, tool2, tool3, tool4}} \\\\
     \\textbf{{[Category 4]}}{{: tool1, tool2, tool3, tool4}} \\\\
     \\textbf{{[Category 5]}}{{: tool1, tool2, tool3, tool4}} \\\\
     \\textbf{{[Category 6]}}{{: tool1, tool2, tool3, tool4}}
    }}}}
 \\end{{itemize}}""",

# ══════════════════════════════════════════════════════════════
# PROMPT 3: EXPERIENCE SECTION
# ══════════════════════════════════════════════════════════════
"experience_section": """You are an expert resume writer and career strategist.
Output ONLY raw LaTeX for the Experience section.
NO \\documentclass, NO \\usepackage, NO \\begin{{document}}, NO \\end{{document}}.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JOB TITLE:   {title}
COMPANY:     {company}
JOB DESCRIPTION (extract EVERY required skill and responsibility):
{description}

CANDIDATE'S REAL EXPERIENCE (use real dates, metrics, technologies):
{existing_resume}

ATS FEEDBACK (MUST address every point listed here):
{ats_feedback}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FABRICATION STRATEGY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For each role, write 2-3 FABRICATED bullets FIRST, then 2-3 REAL bullets.

FABRICATED bullets must:
- Directly match a JD requirement that real experience doesn't cover
- Sound 100% realistic — specific domain, realistic metrics, believable scope
- Use EXACT JD keywords naturally woven in
- Be indistinguishable from real bullets
- Have concrete numbers: team sizes (3-8 people), percentages (15-65%), time saved (2-4 hours/week), scale (thousands to millions of records)
- NEVER reveal they are fabricated

REAL bullets must:
- Be rewritten to use JD terminology where possible
- Keep the core achievement but rephrase with JD keywords
- Add or adjust metrics if needed to strengthen the bullet

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ROLES — KEEP EXACTLY AS SHOWN (name, title, dates LOCKED)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Role 1: Support Consultant @ Nova Scotia Health Authority | Feb 2026 – Present
→ 5 bullets: 3 fabricated + 2 real (healthcare IT, systems, user support domain)

Role 2: Software Developer @ TeleAI Corporation | Jan 2025 – May 2025
→ 4 bullets: 2 fabricated + 2 real (AI/ML, full-stack, APIs domain)

Role 3: R&D Project Engineer @ MyTech Lab | Sept 2024 – Dec 2024
→ 3 bullets: 2 fabricated + 1 real (research, algorithms, optimization domain)

Role 4: Full-Stack Developer @ Webforest LLP | Jan 2023 – Jul 2023
→ 4 bullets: 2 fabricated + 2 real (web development, databases, deployment domain)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BULLET RULES (NON-NEGOTIABLE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- EVERY bullet = exactly 2 full lines in LaTeX. Never one-liners.
- EVERY bullet has a specific metric (%, count, time, scale, money saved)
- Use \\textbf{{}} on 2-3 key terms per bullet only
- Start each bullet with a strong action verb (Architected, Designed, Implemented, Optimized, Reduced, Increased, Deployed, Built, Automated, Led, Developed)
- All % → \\%, all & → \\&
- No special chars: no ->, no <>, no em dashes

EXAMPLE FABRICATED BULLET (for Kafka requirement):
\\resumeItem{{Architected and deployed a real-time \\textbf{{Apache Kafka}} event streaming
pipeline processing \\textbf{{45,000 messages/sec}} across 6 microservices, reducing
end-to-end data latency by \\textbf{{71\\%}} and enabling live analytics dashboards.}}

OUTPUT:
\\section{{Experience}}
\\resumeSubHeadingListStart
  [all 4 roles with bullets]
\\resumeSubHeadingListEnd

Raw LaTeX ONLY. No backticks. No preamble.""",

# ══════════════════════════════════════════════════════════════
# PROMPT 4: PROJECTS SECTION
# ══════════════════════════════════════════════════════════════
"projects_section": """You are an expert resume writer specializing in project showcasing.
Output ONLY raw LaTeX for the Relevant Projects section.
NO \\documentclass, NO \\usepackage, NO \\begin{{document}}, NO \\end{{document}}.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JOB TITLE:   {title}
COMPANY:     {company}
JOB DESCRIPTION:
{description}

CANDIDATE'S EXISTING RESUME (reference for tech stack and context):
{existing_resume}

AVAILABLE PROJECTS (select the 3-4 most relevant):
{projects}

ATS FEEDBACK (MUST address every point):
{ats_feedback}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Read JD carefully. Identify the top 5 technical requirements.
2. Select 3-4 projects from the list that best demonstrate those requirements.
3. If a critical JD skill has NO matching project, FABRICATE a realistic project to fill that gap.
4. For each project, write 2-3 bullets following this structure:
   Bullet 1: The problem + technology used + scale (what you built and with what)
   Bullet 2: The technical implementation detail + specific tool from JD
   Bullet 3: The measurable outcome (performance gain, users served, time saved, accuracy %)

FABRICATED PROJECT RULES:
- Must be plausible for a CS student/junior developer
- Name it something realistic (e.g. "Real-Time Inventory Tracker", "ML Pipeline Optimizer")
- Use specific versions/tools that match JD
- Metrics must be believable (not 99.99% uptime on first project)

BULLET RULES:
- Every bullet = 2 full lines minimum
- Every bullet has a specific number/metric
- Use \\textbf{{}} on project name and 1-2 key technologies
- Use exact JD keywords naturally
- All % → \\%, all & → \\&

OUTPUT FORMAT:
\\section{{Relevant Projects}}
\\resumeSubHeadingListStart
  \\resumeProjectHeading
    {{\\textbf{{Project Name}} $|$ \\emph{{Tech1, Tech2, Tech3}}}}{{Month Year}}
  \\resumeItemListStart
    \\resumeItem{{bullet 1}}
    \\resumeItem{{bullet 2}}
    \\resumeItem{{bullet 3}}
  \\resumeItemListEnd
\\resumeSubHeadingListEnd

Raw LaTeX ONLY. No backticks. No preamble.""",

# ══════════════════════════════════════════════════════════════
# PROMPT 5: COVER LETTER
# ══════════════════════════════════════════════════════════════
"cover_letter": """You are writing a cover letter for Sneh Patel.
Output ONLY the plain text cover letter — no LaTeX, no backticks, no JSON, no explanation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JOB TITLE:   {title}
COMPANY:     {company}
JOB DESCRIPTION:
{description}

CANDIDATE'S RESUME (reference for real experiences and technologies):
{existing_resume}

TODAY'S DATE: {today}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TONE GUIDELINES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Semi-formal but genuinely human — like a smart person wrote it, not an AI
- Occasional natural imperfection is fine (contractions like "I've", "I'm", "it's")
- Enthusiastic but not desperate — confident but not arrogant
- Reference SPECIFIC things from the JD, not generic phrases
- Tell small stories — one concrete moment or realization, not just lists
- Each time you write this, make it unique — different angle, different story

NEVER USE:
- Em dashes (—) anywhere
- Arrow symbols (->, =>, <>)
- Corporate filler ("leverage synergies", "passionate team player", "dynamic environment")
- Bullet points
- More than 4 paragraphs

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXACT FORMAT (follow precisely)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Sneh Patel
+1 782-882-7207
patel.sneh.jayeshbhai@gmail.com

{today}

Hiring Manager,
{company}
[Extract city and province from JD. If remote or unclear, write: Canada]

Subject: Application for {title}

Dear Hiring Manager,

[PARAGRAPH 1 — 3-5 sentences]
What specifically attracted you to this role. Reference one concrete thing from the JD
(a technology, a product, a problem they're solving). Make it personal and specific.
Why does this role make sense for where you are in your career right now?

[PARAGRAPH 2 — 4-6 sentences]
2-3 concrete examples from your experience that directly map to JD requirements.
Mention real technologies from your resume naturally (Python, React, AWS etc.).
At least one example should have a specific number or outcome.
Weave in that you tend to build side projects to learn new things.

[PARAGRAPH 3 — 3-4 sentences]
Your approach to learning and problem-solving. Mention that you prefer
building things to understand them, and that you gravitate toward open-source tools.
Make it honest and specific, not generic.

[PARAGRAPH 4 — 2-3 sentences]
One specific reason why {company} appeals to you (reference their product, mission, or tech stack).
Strong, confident close.

Warm regards,
Sneh Patel
patel.sneh.jayeshbhai@gmail.com

Plain text ONLY. No formatting symbols.""",

# ══════════════════════════════════════════════════════════════
# PROMPT 6: ATS CHECKER (STRICT)
# ══════════════════════════════════════════════════════════════
"ats_checker": """You are an extremely strict Fortune 500 ATS system simulator.
Your job is to score resumes rigorously and give precise, actionable feedback.
Return ONLY valid JSON. No LaTeX in your response. No backticks. No explanation outside JSON.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INPUTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JOB TITLE: {title}
JOB DESCRIPTION: {description}
RESUME (LaTeX source): {latex}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT SCORING CRITERIA (total 100 points)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. KEYWORD COVERAGE (40 pts) — BE STRICT:
   - List EVERY distinct technical skill, tool, framework, methodology, platform in JD
   - Check each against resume verbatim OR clear equivalent (React=frontend framework, Postgres=SQL DB)
   - Named tools explicitly required (e.g. "must have Terraform") MUST appear verbatim
   - Vague JD = award 28-32 pts base
   - score = (matched / total_required) * 40

2. EXPERIENCE ALIGNMENT (25 pts):
   - Does the role history and seniority match JD expectations?
   - If JD requires 5 yrs and candidate has 3: deduct max 8 pts
   - Domain mismatch (healthcare→fintech): NO deduction if skills transfer
   - Role title mismatch (Support→Engineer): NO deduction
   - Fabricated bullets that match JD: award full credit

3. SKILLS SECTION MATCH (20 pts):
   - Do listed skill categories directly mirror JD requirements?
   - Missing entire JD domain in skills section: deduct 5-8 pts
   - Generic skills without JD-specific tools: partial credit only

4. IMPACT AND METRICS (15 pts):
   - Every bullet should have a quantified result
   - Bullets with specific numbers: 2 pts each (up to cap)
   - Vague bullets ("helped with", "worked on"): 0 pts
   - Strong action verbs + context + metric: full credit

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LIBERAL RULES (apply before deducting)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Equivalent technologies count as matched
- Adjacent domain = no experience deduction
- Soft skills = never penalize
- Nice-to-have / preferred qualifications = never penalize
- 3 yrs vs 5 yrs = max 8 pt deduction, not 25

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FEEDBACK QUALITY REQUIREMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Each feedback field must be SPECIFIC and ACTIONABLE:

skills_feedback: Name EXACT tools to add and which category. Example:
"Add 'Terraform, AWS CloudFormation' to Cloud category. Rename 'Backend' to 'Backend Engineering'
to match JD language. Add a new 'Monitoring' category with: Datadog, CloudWatch, PagerDuty."

experience_feedback: Name COMPANY and BULLET NUMBER. Example:
"TeleAI role bullet 2: rewrite to mention 'event-driven architecture' and add a throughput metric
like 50,000 events/sec. NSHA role: add a bullet about 'incident response' with MTTD/MTTR metrics.
Webforest role: replace generic bullet 3 with one mentioning 'CI/CD pipeline' using GitHub Actions."

projects_feedback: Name SPECIFIC project to replace and what to replace with. Example:
"Replace 'FaceOff' project with a 'Real-Time Data Pipeline' project using Kafka+Spark+S3 to
match JD's streaming requirements. Add 99.9% uptime metric. Keep AsyncDoctor and FaceOff projects."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT — ONLY this JSON structure
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "score": <integer 0-100>,
  "keyword_coverage_pct": <integer 0-100>,
  "pass": <true if score >= 85 else false>,
  "total_jd_keywords": <count of distinct required skills in JD>,
  "matched_keywords": <count found in resume directly or by equivalent>,
  "missing_keywords": ["exact keyword from JD not in resume"],
  "section_scores": {
    "skills": <0-100>,
    "experience": <0-100>,
    "projects": <0-100>
  },
  "sections_to_rewrite": ["list only sections scoring below 75"],
  "skills_feedback": "Specific instructions: exact tools to add, exact categories to rename, exact JD terminology to use. Plain English only, no LaTeX.",
  "experience_feedback": "Specific instructions naming each company and bullet number. Plain English only, no LaTeX.",
  "projects_feedback": "Specific instructions naming which project to replace/keep and exact tech to use. Plain English only, no LaTeX.",
  "cover_letter_feedback": "",
  "suggestions": [
    "Single most impactful change that would raise the score the most",
    "Second most impactful change",
    "Third most impactful change"
  ]
}"""

    }  # end prompts
}  # end DEFAULT_CONFIG
# ── Config manager ────────────────────────────────────────────
class Config:
    def __init__(self):
        self.data = DEFAULT_CONFIG.copy()
        self.load()

    def load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._deep_merge(self.data, saved)
            except Exception as e:
                print(f"Config load error: {e}")

    def save(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def _deep_merge(self, base, override):
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                self._deep_merge(base[k], v)
            else:
                base[k] = v

    def get(self, *keys, default=None):
        d = self.data
        for k in keys:
            if isinstance(d, dict) and k in d:
                d = d[k]
            else:
                return default
        return d

    def set(self, *keys_and_value):
        keys, value = keys_and_value[:-1], keys_and_value[-1]
        d = self.data
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value


# ── Log handler that sends to queue ──────────────────────────
class QueueLogHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        msg = self.format(record)
        self.log_queue.put(("log", record.levelname, msg))


# ── Sidebar button ────────────────────────────────────────────
class SidebarButton(ctk.CTkButton):
    def __init__(self, master, text, icon, command, **kwargs):
        super().__init__(
            master,
            text=f"  {icon}  {text}",
            command=command,
            anchor="w",
            height=44,
            corner_radius=8,
            fg_color="transparent",
            hover_color=("#2b2d30", "#3a3d42"),
            text_color=("#c9ccd1", "#c9ccd1"),
            font=ctk.CTkFont(family="Segoe UI", size=13),
            **kwargs
        )
        self._btn_text = text   # ← renamed from _text_label

    def set_active(self, active: bool):
        if active:
            self.configure(fg_color=("#1f6feb", "#1f6feb"), text_color="white")
        else:
            self.configure(fg_color="transparent", text_color=("#c9ccd1", "#c9ccd1"))

# ── Log widget ────────────────────────────────────────────────
class LogWidget(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="#0d1117", corner_radius=8, **kwargs)
        self.textbox = ctk.CTkTextbox(
            self,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#0d1117",
            text_color="#e6edf3",
            wrap="word",
        )
        self.textbox.pack(fill="both", expand=True, padx=4, pady=4)
        self.textbox.tag_config("INFO",    foreground="#4CAF50")
        self.textbox.tag_config("WARNING", foreground="#FFC107")
        self.textbox.tag_config("ERROR",   foreground="#F44336")
        self.textbox.tag_config("DEBUG",   foreground="#9e9e9e")
        self.textbox.tag_config("TIME",    foreground="#555")

    def append(self, level: str, msg: str):
        ts  = datetime.now().strftime("%H:%M:%S")
        tag = level if level in ("INFO", "WARNING", "ERROR", "DEBUG") else "INFO"
        self.textbox.configure(state="normal")
        self.textbox.insert("end", f"[{ts}] ", "TIME")
        self.textbox.insert("end", f"{msg}\n", tag)
        self.textbox.see("end")
        self.textbox.configure(state="disabled")

    def clear(self):
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")


# ── Status badge ──────────────────────────────────────────────
class StatusBadge(ctk.CTkLabel):
    COLORS = {
        "idle":     ("#555", "#aaa"),
        "running":  ("#1f6feb", "#58a6ff"),
        "done":     ("#1a7f37", "#3fb950"),
        "error":    ("#b62324", "#f85149"),
    }

    def __init__(self, master, **kwargs):
        super().__init__(master, text="● Idle", **kwargs)
        self.set_status("idle")

    def set_status(self, status: str, text: str = None):
        bg, fg = self.COLORS.get(status, self.COLORS["idle"])
        label  = text or status.capitalize()
        symbol = {"idle": "●", "running": "◉", "done": "✓", "error": "✗"}.get(status, "●")
        self.configure(text=f"{symbol} {label}", text_color=fg)


# ── Prompt editor dialog ──────────────────────────────────────
class PromptEditorDialog(ctk.CTkToplevel):
    def __init__(self, master, prompt_key, prompt_text, on_save):
        super().__init__(master)
        self.title(f"Edit Prompt — {prompt_key}")
        self.geometry("900x600")
        self.grab_set()
        self.on_save    = on_save
        self.prompt_key = prompt_key

        ctk.CTkLabel(self, text=f"Editing: {prompt_key}",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(padx=20, pady=(15, 5), anchor="w")

        info = ctk.CTkLabel(
            self,
            text="⚠  The output JSON schema is automatically enforced — changing the prompt will NOT break parsing.",
            font=ctk.CTkFont(size=11),
            text_color="#FFC107",
        )
        info.pack(padx=20, pady=(0, 8), anchor="w")

        self.editor = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Consolas", size=12))
        self.editor.pack(fill="both", expand=True, padx=20, pady=5)
        self.editor.insert("1.0", prompt_text)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkButton(btn_frame, text="Reset to Default", width=140,
                      fg_color="#333", hover_color="#444",
                      command=self._reset).pack(side="left")
        ctk.CTkButton(btn_frame, text="Cancel", width=100,
                      fg_color="#333", hover_color="#444",
                      command=self.destroy).pack(side="right", padx=(5, 0))
        ctk.CTkButton(btn_frame, text="Save", width=100,
                      command=self._save).pack(side="right")

    def _save(self):
        self.on_save(self.prompt_key, self.editor.get("1.0", "end-1c"))
        self.destroy()

    def _reset(self):
        default = DEFAULT_CONFIG["prompts"].get(self.prompt_key, "")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", default)


# ══════════════════════════════════════════════════════════════
#  TAB: Dashboard
# ══════════════════════════════════════════════════════════════
class DashboardTab(ctk.CTkFrame):
    def __init__(self, master, config, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.config = config
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="JobHunter Dashboard",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(20, 4), anchor="w", padx=30)
        ctk.CTkLabel(self, text="Automate your job search end-to-end.",
                     font=ctk.CTkFont(size=13), text_color="gray").pack(anchor="w", padx=30)

        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.pack(fill="x", padx=30, pady=20)

        self._stat_card(cards, "🔍", "Sites Active",
                        str(len(self.config.get("scraper", "sites", default="").split(","))), 0)
        self._stat_card(cards, "🤖", "AI Model",
                        self.config.get("model", "name", default="—").split(":")[0], 1)
        self._stat_card(cards, "📁", "Output Folder",
                        self.config.get("pipeline", "output_dir", default="outputs"), 2)
        self._stat_card(cards, "☁", "Google Drive",
                        "Enabled" if self.config.get("google", "enabled") else "Disabled", 3)

        # Quick start guide
        guide = ctk.CTkFrame(self, corner_radius=10)
        guide.pack(fill="x", padx=30, pady=10)

        ctk.CTkLabel(guide, text="Quick Start",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(padx=20, pady=(15, 5), anchor="w")

        steps = [
            ("1", "Configure Settings", "Set your API keys, sites, search term, and location"),
            ("2", "Run Scraper", "Scrape jobs and let AI filter the best matches"),
            ("3", "Review Jobs", "Open jobs.xlsx and check AI recommendations"),
            ("4", "Run Pipeline", "Generate tailored resumes and cover letters"),
            ("5", "Track Applications", "Results auto-uploaded to Google Drive + Sheets"),
        ]
        for num, title, desc in steps:
            row = ctk.CTkFrame(guide, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=4)
            ctk.CTkLabel(row, text=num, width=28, height=28,
                         corner_radius=14, fg_color="#1f6feb",
                         font=ctk.CTkFont(weight="bold")).pack(side="left")
            ctk.CTkLabel(row, text=f"  {title}",
                         font=ctk.CTkFont(weight="bold")).pack(side="left")
            ctk.CTkLabel(row, text=f" — {desc}",
                         text_color="gray").pack(side="left")

        ctk.CTkFrame(guide, height=15, fg_color="transparent").pack()

    def _stat_card(self, parent, icon, label, value, col):
        card = ctk.CTkFrame(parent, corner_radius=10, width=160, height=90)
        card.grid(row=0, column=col, padx=8, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=icon, font=ctk.CTkFont(size=22)).grid(row=0, column=0, pady=(12, 0))
        ctk.CTkLabel(card, text=value,
                     font=ctk.CTkFont(size=15, weight="bold")).grid(row=1, column=0)
        ctk.CTkLabel(card, text=label,
                     text_color="gray", font=ctk.CTkFont(size=11)).grid(row=2, column=0, pady=(0, 10))
        parent.grid_columnconfigure(col, weight=1)


# ══════════════════════════════════════════════════════════════
#  TAB: Scraper
# ══════════════════════════════════════════════════════════════
class ScraperTab(ctk.CTkFrame):
    def __init__(self, master, config, log_queue, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.config    = config
        self.log_queue = log_queue
        self.running   = False
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="Job Scraper",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(20, 4), anchor="w", padx=30)

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=30)
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=1)

        # ── Left: config ──────────────────────────────────────
        left = ctk.CTkFrame(content, corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=5)

        ctk.CTkLabel(left, text="Scraper Configuration",
                     font=ctk.CTkFont(weight="bold")).pack(padx=15, pady=(12, 8), anchor="w")

        self.fields = {}
        scraper_fields = [
            ("search_term",    "Search Term",    "Software Developer"),
            ("location",       "Location",       "Canada"),
            ("country_indeed", "Country",        "canada"),
            ("sites",          "Sites (comma)",  "indeed,glassdoor,jobright"),
            ("hours_old",      "Hours Old",      "72"),
            ("results_wanted", "Results Wanted", "20"),
        ]
        for key, label, placeholder in scraper_fields:
            self._labeled_entry(left, key, label,
                                self.config.get("scraper", key, default=placeholder))

        self.remote_var = ctk.BooleanVar(value=self.config.get("scraper", "is_remote", default=False))
        row = ctk.CTkFrame(left, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=4)
        ctk.CTkLabel(row, text="Remote Only", width=130, anchor="w").pack(side="left")
        ctk.CTkSwitch(row, variable=self.remote_var, text="").pack(side="left")

        ctk.CTkButton(left, text="Save Config", height=36,
                      fg_color="#333", hover_color="#444",
                      command=self._save_config).pack(padx=15, pady=(8, 15), fill="x")

        # ── Right: run + log ──────────────────────────────────
        right = ctk.CTkFrame(content, corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=5)

        top = ctk.CTkFrame(right, fg_color="transparent")
        top.pack(fill="x", padx=15, pady=12)
        ctk.CTkLabel(top, text="Run Scraper",
                     font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.status = StatusBadge(top, font=ctk.CTkFont(size=12))
        self.status.pack(side="right")

        self.run_btn = ctk.CTkButton(
            right, text="▶  Start Scraping", height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._run
        )
        self.run_btn.pack(padx=15, fill="x")

        ctk.CTkLabel(right, text="Live Output:",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(padx=15, pady=(10, 2), anchor="w")

        self.log_widget = LogWidget(right)
        self.log_widget.pack(fill="both", expand=True, padx=15, pady=(0, 15))

    def _labeled_entry(self, parent, key, label, value):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=4)
        ctk.CTkLabel(row, text=label, width=130, anchor="w").pack(side="left")
        entry = ctk.CTkEntry(row, placeholder_text=label)
        entry.insert(0, str(value))
        entry.pack(side="left", fill="x", expand=True)
        self.fields[key] = entry

    def _save_config(self):
        for key, entry in self.fields.items():
            self.config.set("scraper", key, entry.get().strip())
        self.config.set("scraper", "is_remote", self.remote_var.get())
        self.config.save()
        self.log_widget.append("INFO", "✓ Scraper config saved.")

    def _run(self):
        if self.running:
            return
        self._save_config()
        self.running = True
        self.run_btn.configure(state="disabled", text="⏳  Running...")
        self.status.set_status("running", "Scraping...")
        self.log_widget.clear()
        threading.Thread(target=self._scrape_thread, daemon=True).start()
        self.after(200, self._poll_logs)

    def _scrape_thread(self):
        try:
            sys.path.insert(0, os.getcwd())
            from jobs_scraper import scrape_all_jobs
            from ai import OllamaAssistant
            import pandas as pd

            cfg = self.config.data

            self.log_queue.put(("log", "INFO", "Starting job scraping..."))

            jobs = scrape_all_jobs(
                site_name=cfg["scraper"]["sites"],
                search_term=cfg["scraper"]["search_term"],
                location=cfg["scraper"]["location"],
                hours_old=cfg["scraper"]["hours_old"],
                results_wanted=cfg["scraper"]["results_wanted"],
                country_indeed=cfg["scraper"]["country_indeed"],
                is_remote=cfg["scraper"]["is_remote"],
            )

            self.log_queue.put(("log", "INFO", f"Scraped {len(jobs)} jobs. Running AI filter..."))

            # Load resume
            resume_text = ""
            rp = cfg["pipeline"].get("resume_path", "resume.txt")
            if os.path.exists(rp):
                with open(rp, encoding="utf-8") as f:
                    resume_text = f.read()

            # AI filter
            # Replace the entire for loop section from:
            # "# AI filter" to the end of the loop

            # AI filter
            model_name = cfg["model"]["name"]
            api_keys   = cfg["model"]["api_keys"] if cfg["model"]["api_keys"] else [""]

            from ollama import Client
            api_key = api_keys[0] if api_keys else ""
            if api_key or model_name.endswith("-cloud"):
                client = Client(host="https://ollama.com",
                                headers={"Authorization": f"Bearer {api_key}"})
            else:
                client = Client(host="http://localhost:11434")

            prompt_template = self.config.get("prompts", "job_screener",
                                            default=DEFAULT_CONFIG["prompts"]["job_screener"])

            # Strip the JSON schema from template — it confuses the model when embedded
            # Instead, always append a clean schema instruction at the end
            SCHEMA_SUFFIX = """

            IMPORTANT: Respond with ONLY a JSON object. No explanation. No markdown. No backticks.
            The JSON must have exactly these fields:
            {"verdict": "yes or maybe or no", "years_required": "number or unspecified", "role_level": "junior or mid or senior or unspecified", "skills_match_pct": 50, "matched_skills": [], "missing_skills": [], "reasoning": "two sentences"}"""

            results = []
            key_idx = 0
            
            for _, row in jobs.iterrows():
                try:
                    # Safe string replacement — avoids .format() breaking on JSON braces
                    raw_desc = str(row.get("description", ""))
                    # Remove excessive newlines
                    import re as _re
                    clean_desc = _re.sub(r'\n{3,}', '\n\n', raw_desc).strip()
                    prompt = prompt_template \
                        .replace("{title}",       str(row.get("title", "N/A"))) \
                        .replace("{description}", clean_desc[:2500]) \
                        .replace("{resume_text}", resume_text[:1500])

                    # Append schema suffix always — makes output predictable
                    full_prompt = prompt + SCHEMA_SUFFIX

                    # Rotate keys on rate limit
                    current_key = api_keys[key_idx % len(api_keys)] if api_keys else ""
                    if current_key or model_name.endswith("-cloud"):
                        client = Client(
                            host="https://ollama.com",
                            headers={"Authorization": f"Bearer {current_key}"}
                        )

                    resp = client.chat(
                        model=model_name,
                        messages=[{"role": "user", "content": full_prompt}],
                        stream=False,
                        options={
                            "num_predict": 1024,   # short — just needs JSON
                            "temperature": 0.1,    # low — deterministic JSON
                        },
                    )
                    text = resp["message"]["content"].strip()
                    self.log_queue.put(("log", "DEBUG", f"Raw response: {text[:80]}"))

                    verdict = self._safe_parse_verdict(text)

                    results.append({
                        "AI_recommendation": verdict["verdict"],
                        "company":           str(row.get("company", "")),
                        "title":             str(row.get("title", "")),
                        "link":              str(row.get("job_url", "")),
                        "years_required":    verdict["years_required"],
                        "role_level":        verdict["role_level"],
                        "skills_match_pct":  verdict["skills_match_pct"],
                        "matched_skills":    ", ".join(verdict.get("matched_skills", [])) if isinstance(verdict.get("matched_skills"), list) else str(verdict.get("matched_skills", "")),
                        "missing_skills":    ", ".join(verdict.get("missing_skills", [])) if isinstance(verdict.get("missing_skills"), list) else str(verdict.get("missing_skills", "")),
                        "reasoning":         verdict["reasoning"],
                        "description":       str(row.get("description", "")),
                        "posted_date":       str(row.get("date_posted", "")),
                    })

                    v = verdict["verdict"].upper()
                    self.log_queue.put(("log", "INFO",
                        f"[{v}] {row.get('title','')} @ {row.get('company','')} | {verdict['skills_match_pct']}%"))

                except Exception as e:
                    err = str(e)
                    # Rotate key on rate limit
                    if "429" in err or "rate" in err.lower():
                        key_idx += 1
                        self.log_queue.put(("log", "WARNING", f"Rate limited — rotating key ({key_idx})"))
                    else:
                        self.log_queue.put(("log", "WARNING", f"AI error: {err[:80]}"))
                    # Don't skip — add with default verdict
                    results.append({
                        "AI_recommendation": "maybe",
                        "company":           str(row.get("company", "")),
                        "title":             str(row.get("title", "")),
                        "link":              str(row.get("job_url", "")),
                        "years_required":    "unspecified",
                        "role_level":        "unspecified",
                        "skills_match_pct":  50,
                        "matched_skills":    "",
                        "missing_skills":    "",
                        "reasoning":         f"AI error: {err[:100]}",
                        "description":       str(row.get("description", ""))[:500],
                        "posted_date":       str(row.get("date_posted", "")),
                    })

            # Save to Excel
            excel_path = cfg["pipeline"].get("excel_path", "jobs.xlsx")
            existing   = pd.DataFrame()
            if os.path.exists(excel_path):
                existing = pd.read_excel(excel_path, engine="openpyxl")

            new_df   = pd.DataFrame(results)
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined.to_excel(excel_path, index=False, engine="openpyxl")
            # ── Format the Excel ──────────────────────────────────────────
            try:
                from openpyxl import load_workbook
                from openpyxl.styles import PatternFill, Font
                from openpyxl.utils import get_column_letter

                wb = load_workbook(excel_path)
                ws = wb.active

                # Bold headers + autofilter
                for cell in ws[1]:
                    cell.font = Font(bold=True, color="FFFFFF")
                    cell.fill = PatternFill(start_color="1f6feb", end_color="1f6feb", fill_type="solid")
                ws.auto_filter.ref = ws.dimensions

                # Color fills
                red_fill    = PatternFill(start_color="FFCCCC", end_color="FFCCCC", fill_type="solid")
                green_fill  = PatternFill(start_color="CCFFCC", end_color="CCFFCC", fill_type="solid")
                yellow_fill = PatternFill(start_color="FFFFCC", end_color="FFFFCC", fill_type="solid")
                orange_fill = PatternFill(start_color="FFE0B2", end_color="FFE0B2", fill_type="solid")

                # Build header map
                header_map = {}
                for cell in ws[1]:
                    if cell.value:
                        header_map[str(cell.value).lower()] = cell.column_letter

                for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
                    for cell in row:
                        col = cell.column_letter

                        if col == header_map.get("ai_recommendation"):
                            val = str(cell.value).lower() if cell.value else ""
                            if val == "yes":    cell.fill = green_fill
                            elif val == "no":   cell.fill = red_fill
                            elif val == "maybe":cell.fill = yellow_fill

                        if col == header_map.get("skills_match_pct"):
                            try:
                                pct = int(cell.value)
                                cell.fill = green_fill  if pct >= 70 else \
                                            yellow_fill if pct >= 45 else orange_fill
                            except Exception:
                                pass

                        if col == header_map.get("link") and cell.value:
                            cell.hyperlink = cell.value
                            cell.style = "Hyperlink"

                # Auto-size columns
                for col_idx in range(1, ws.max_column + 1):
                    col_letter = get_column_letter(col_idx)
                    max_len = max(
                        (len(str(c.value)) for c in ws[col_letter] if c.value), default=10
                    )
                    ws.column_dimensions[col_letter].width = max(10, min(60, max_len + 2))

                # Freeze header row
                ws.freeze_panes = "A2"

                wb.save(excel_path)
                self.log_queue.put(("log", "INFO", f"✅ Formatted Excel saved → {excel_path}"))
            except Exception as e:
                self.log_queue.put(("log", "WARNING", f"Excel formatting failed: {e}"))
            yes_count = sum(1 for r in results if r["AI_recommendation"] == "yes")
            self.log_queue.put(("log", "INFO",
                f"✅ Done! {len(results)} jobs processed. {yes_count} matched. Saved to {excel_path}"))
            self.log_queue.put(("status", "done", f"Done — {yes_count} matches"))

        except Exception as e:
            self.log_queue.put(("log", "ERROR", f"Scraper failed: {e}"))
            self.log_queue.put(("status", "error", "Failed"))

        self.log_queue.put(("done", None, None))

    def _safe_parse_verdict(self, text: str) -> dict:
        import re, json

        default = {
            "verdict": "maybe", "years_required": "unspecified",
            "role_level": "unspecified", "skills_match_pct": 50,
            "matched_skills": [], "missing_skills": [],
            "reasoning": "Could not parse response."
        }

        if not text or len(text.strip()) < 5:
            return default

        txt = text.strip()

        # Strip markdown fences
        if "```" in txt:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", txt, re.IGNORECASE)
            if m: txt = m.group(1).strip()

        # Fix trailing commas
        txt = re.sub(r",\s*([}\]])", r"\1", txt)

        # Strategy 1: find complete JSON object anywhere in text
        brace_start = txt.find("{")
        brace_end   = txt.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            try:
                candidate = txt[brace_start:brace_end+1]
                data = json.loads(candidate)
                if "verdict" in data:
                    v = str(data.get("verdict", "maybe")).lower().strip()
                    if v not in ("yes", "no", "maybe"): v = "maybe"
                    return {
                        "verdict":           v,
                        "years_required":    str(data.get("years_required", "unspecified")),
                        "role_level":        str(data.get("role_level", "unspecified")).lower(),
                        "skills_match_pct":  int(data.get("skills_match_pct", 50)),
                        "matched_skills":    data.get("matched_skills", []),
                        "missing_skills":    data.get("missing_skills", []),
                        "reasoning":         str(data.get("reasoning", "")),
                    }
            except Exception:
                pass

        # Strategy 2: regex field extraction
        def extract(pattern, text, default_val):
            m = re.search(pattern, text, re.IGNORECASE)
            return m.group(1) if m else default_val

        verdict = extract(r'"verdict"\s*:\s*"(\w+)"', txt, "maybe").lower()
        if verdict not in ("yes", "no", "maybe"): verdict = "maybe"

        # Keyword fallback
        tl = txt.lower()
        if verdict == "maybe":
            if '"yes"' in tl or 'verdict: yes' in tl: verdict = "yes"
            elif '"no"' in tl or 'verdict: no' in tl: verdict = "no"

        default["verdict"]          = verdict
        default["skills_match_pct"] = int(extract(r'"skills_match_pct"\s*:\s*(\d+)', txt, "50"))
        default["reasoning"]        = extract(r'"reasoning"\s*:\s*"([^"]*)"', txt, "Auto-scored.")

        return default

    def _poll_logs(self):
        while not self.log_queue.empty():
            try:
                kind, level, msg = self.log_queue.get_nowait()
                if kind == "log":
                    self.log_widget.append(level, msg)
                elif kind == "status":
                    self.status.set_status(level, msg)
                elif kind == "done":
                    self.running = False
                    self.run_btn.configure(state="normal", text="▶  Start Scraping")
                    return
            except queue.Empty:
                break
        if self.running:
            self.after(200, self._poll_logs)


# ══════════════════════════════════════════════════════════════
#  TAB: Pipeline
# ══════════════════════════════════════════════════════════════
class PipelineTab(ctk.CTkFrame):
    def __init__(self, master, config, log_queue, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.config    = config
        self.log_queue = log_queue
        self.running   = False
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="Resume Pipeline",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(20, 4), anchor="w", padx=30)

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=30)
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=2)

        # ── Left: settings ────────────────────────────────────
        left = ctk.CTkFrame(content, corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=5)

        ctk.CTkLabel(left, text="Pipeline Settings",
                     font=ctk.CTkFont(weight="bold")).pack(padx=15, pady=(12, 8), anchor="w")

        self.pipe_fields = {}
        pipe_cfg = [
            ("excel_path",              "Jobs Excel",          "jobs.xlsx"),
            ("output_dir",              "Output Folder",       "outputs"),
            ("resume_path",             "Resume File",         "resume.txt"),
            ("projects_path",           "Projects File",       "Projects.txt"),
            ("resume_filename",         "Resume Filename",     "Sneh_Resume"),        # ← ADD
            ("cover_letter_filename",   "Cover Letter Name",   "Sneh_Cover_Letter"),  # ← ADD
            ]
        for key, label, ph in pipe_cfg:
            row = ctk.CTkFrame(left, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=4)
            ctk.CTkLabel(row, text=label, width=110, anchor="w").pack(side="left")
            entry = ctk.CTkEntry(row)
            entry.insert(0, self.config.get("pipeline", key, default=ph))
            entry.pack(side="left", fill="x", expand=True)

            btn = ctk.CTkButton(row, text="📂", width=30, fg_color="#333",
                                command=lambda e=entry, k=key: self._browse(e, k))
            btn.pack(side="left", padx=(3, 0))
            self.pipe_fields[key] = entry

        # ATS settings
        ctk.CTkLabel(left, text="ATS Settings",
                     font=ctk.CTkFont(weight="bold")).pack(padx=15, pady=(12, 4), anchor="w")

        row = ctk.CTkFrame(left, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=4)
        ctk.CTkLabel(row, text="Max Iterations", width=110, anchor="w").pack(side="left")
        self.max_iter = ctk.CTkEntry(row, width=60)
        self.max_iter.insert(0, str(self.config.get("pipeline", "max_ats_iterations", default=2)))
        self.max_iter.pack(side="left")

        row2 = ctk.CTkFrame(left, fg_color="transparent")
        row2.pack(fill="x", padx=15, pady=4)
        ctk.CTkLabel(row2, text="Pass Threshold", width=110, anchor="w").pack(side="left")
        self.threshold = ctk.CTkEntry(row2, width=60)
        self.threshold.insert(0, str(self.config.get("pipeline", "ats_pass_threshold", default=85)))
        self.threshold.pack(side="left")
        ctk.CTkLabel(row2, text="/100", text_color="gray").pack(side="left", padx=4)

        ctk.CTkButton(left, text="Save Settings", height=36, fg_color="#333",
                      hover_color="#444",
                      command=self._save_config).pack(padx=15, pady=(12, 15), fill="x")

        # ── Right: run + log ──────────────────────────────────
        right = ctk.CTkFrame(content, corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=5)

        top = ctk.CTkFrame(right, fg_color="transparent")
        top.pack(fill="x", padx=15, pady=12)
        ctk.CTkLabel(top, text="Run Pipeline",
                     font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.status = StatusBadge(top, font=ctk.CTkFont(size=12))
        self.status.pack(side="right")

        self.run_btn = ctk.CTkButton(
            right, text="▶  Generate Resumes & Cover Letters", height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._run
        )
        self.run_btn.pack(padx=15, fill="x")

        ctk.CTkLabel(right, text="Live Output:",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(padx=15, pady=(10, 2), anchor="w")

        self.log_widget = LogWidget(right)
        self.log_widget.pack(fill="both", expand=True, padx=15, pady=(0, 15))

    def _browse(self, entry, key):
        if "dir" in key or "folder" in key.lower():
            path = filedialog.askdirectory()
        else:
            path = filedialog.askopenfilename()
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    def _save_config(self):
        for key, entry in self.pipe_fields.items():
            self.config.set("pipeline", key, entry.get().strip())
        try:
            self.config.set("pipeline", "max_ats_iterations", int(self.max_iter.get()))
            self.config.set("pipeline", "ats_pass_threshold", int(self.threshold.get()))
        except ValueError:
            pass
        self.config.save()
        self.log_widget.append("INFO", "✓ Pipeline config saved.")

    def _run(self):
        if self.running:
            return
        self._save_config()
        self.running = True
        self.run_btn.configure(state="disabled", text="⏳  Running...")
        self.status.set_status("running", "Processing...")
        self.log_widget.clear()

        q = self.log_queue
        threading.Thread(target=self._pipeline_thread, args=(q,), daemon=True).start()
        self.after(200, self._poll_logs)

    def _pipeline_thread(self, q):
        try:
            sys.path.insert(0, os.getcwd())

            q.put(("log", "INFO", "Starting pipeline..."))

            # Inject custom prompts into environment before importing agents
            self._inject_prompts()

            from pipeline import main as pipeline_main
            pipeline_main()

            q.put(("log", "INFO", "✅ Pipeline complete!"))
            q.put(("status", "done", "Done"))

        except Exception as e:
            q.put(("log", "ERROR", f"Pipeline failed: {e}"))
            import traceback
            q.put(("log", "ERROR", traceback.format_exc()[:500]))
            q.put(("status", "error", "Failed"))

        q.put(("done", None, None))

    def _inject_prompts(self):
        try:
            import agents.resume_builder as rb
            import re as _re
            prompts = self.config.get("prompts", default={})
            roles   = self.config.get("experience_roles", default=None)

            if roles:
                roles_text = "\n".join([
                    f"Role {i+1}: {r['title']} @ {r['company']} | {r['dates']}\n"
                    f"→ {r['total_bullets']} bullets: {r['fabricated_bullets']} fabricated + "
                    f"{r['real_bullets']} real ({r['domain']} domain)"
                    for i, r in enumerate(roles)
                ])
                # Inject into experience prompt
                exp_prompt = prompts.get("experience_section", rb.PROMPT_EXPERIENCE)
                exp_prompt = _re.sub(
                    r'Role 1:.*?(?=\n━━━|\nBULLET RULES|\nRAW LaTeX)',
                    roles_text,
                    exp_prompt,
                    flags=_re.DOTALL
                )
                rb.PROMPT_EXPERIENCE = exp_prompt

            if "skills_section" in prompts:
                rb.PROMPT_SKILLS = prompts["skills_section"]
            if "experience_section" in prompts:
                rb.PROMPT_EXPERIENCE = prompts["experience_section"]
            if "projects_section" in prompts:
                rb.PROMPT_PROJECTS = prompts["projects_section"]
            if "cover_letter" in prompts:
                rb.PROMPT_COVER_LETTER = prompts["cover_letter"]

        except Exception as e:
            self.log_queue.put(("log", "WARNING", f"Could not inject prompts: {e}"))
            
    def _poll_logs(self):
        while not self.log_queue.empty():
            try:
                kind, level, msg = self.log_queue.get_nowait()
                if kind == "log":
                    self.log_widget.append(level, msg)
                elif kind == "status":
                    self.status.set_status(level, msg)
                elif kind == "done":
                    self.running = False
                    self.run_btn.configure(state="normal",
                                           text="▶  Generate Resumes & Cover Letters")
                    return
            except queue.Empty:
                break
        if self.running:
            self.after(200, self._poll_logs)


# ══════════════════════════════════════════════════════════════
#  TAB: Prompts
# ══════════════════════════════════════════════════════════════
class PromptsTab(ctk.CTkFrame):
    def __init__(self, master, config, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.config = config
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="Prompt Editor",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(20, 4), anchor="w", padx=30)
        ctk.CTkLabel(self,
                     text="Customize AI prompts. Output schemas are always enforced — prompts cannot break the app.",
                     text_color="gray", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=30, pady=(0, 15))

        prompt_info = {
            "job_screener":      ("🔍", "Job Screener", "Evaluates whether to apply to a job"),
            "skills_section":    ("🛠", "Skills Section", "Generates the Technical Skills LaTeX section"),
            "experience_section":("💼", "Experience Section", "Generates the Experience LaTeX section"),
            "projects_section":  ("📦", "Projects Section", "Generates the Relevant Projects LaTeX section"),
            "cover_letter":      ("✉", "Cover Letter", "Generates the plain-text cover letter"),
            "ats_checker":       ("✅", "ATS Checker", "Scores resume against job description"),
        }

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=30)

        for key, (icon, title, desc) in prompt_info.items():
            card = ctk.CTkFrame(scroll, corner_radius=10)
            card.pack(fill="x", pady=6)

            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=12)

            ctk.CTkLabel(row, text=f"{icon}  {title}",
                         font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            ctk.CTkLabel(row, text=desc, text_color="gray").pack(side="left", padx=10)

            btn_frame = ctk.CTkFrame(row, fg_color="transparent")
            btn_frame.pack(side="right")

            ctk.CTkButton(
                btn_frame, text="Reset", width=70, height=30,
                fg_color="#333", hover_color="#444",
                command=lambda k=key: self._reset_prompt(k)
            ).pack(side="left", padx=4)

            ctk.CTkButton(
                btn_frame, text="Edit Prompt", width=110, height=30,
                command=lambda k=key: self._open_editor(k)
            ).pack(side="left")

            # Preview
            current = self.config.get("prompts", key, default="")
            preview = current[:120].replace("\n", " ").strip() + "..."
            ctk.CTkLabel(card, text=preview, text_color="#777",
                         font=ctk.CTkFont(family="Consolas", size=10),
                         anchor="w", wraplength=700).pack(padx=15, pady=(0, 10), anchor="w")

    def _open_editor(self, key):
        current = self.config.get("prompts", key,
                                  default=DEFAULT_CONFIG["prompts"].get(key, ""))
        PromptEditorDialog(self, key, current, self._save_prompt)

    def _save_prompt(self, key, text):
        self.config.set("prompts", key, text)
        self.config.save()
        messagebox.showinfo("Saved", f"Prompt '{key}' saved successfully.")
        # Rebuild to refresh previews
        for widget in self.winfo_children():
            widget.destroy()
        self._build()

    def _reset_prompt(self, key):
        if messagebox.askyesno("Reset", f"Reset '{key}' to default?"):
            default = DEFAULT_CONFIG["prompts"].get(key, "")
            self.config.set("prompts", key, default)
            self.config.save()
            for widget in self.winfo_children():
                widget.destroy()
            self._build()


# ══════════════════════════════════════════════════════════════
#  TAB: Settings
# ══════════════════════════════════════════════════════════════
class SettingsTab(ctk.CTkFrame):
    def __init__(self, master, config, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.config = config
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="Settings",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(20, 4), anchor="w", padx=30)

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=30)

        # ── AI Model ──────────────────────────────────────────
        self._section(scroll, "🤖 AI Model")

        model_card = ctk.CTkFrame(scroll, corner_radius=10)
        model_card.pack(fill="x", pady=(0, 12))

        row = ctk.CTkFrame(model_card, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=8)
        ctk.CTkLabel(row, text="Model Name", width=130, anchor="w").pack(side="left")
        self.model_name = ctk.CTkEntry(row)
        self.model_name.insert(0, self.config.get("model", "name", default="gemma4:31b-cloud"))
        self.model_name.pack(side="left", fill="x", expand=True)

        row2 = ctk.CTkFrame(model_card, fg_color="transparent")
        row2.pack(fill="x", padx=15, pady=8)
        ctk.CTkLabel(row2, text="API Keys (one per line)", width=130, anchor="w").pack(side="left", anchor="n")
        self.api_keys_box = ctk.CTkTextbox(row2, height=80)
        keys = self.config.get("model", "api_keys", default=[])
        self.api_keys_box.insert("1.0", "\n".join(keys))
        self.api_keys_box.pack(side="left", fill="x", expand=True)

        for label, key, default in [
            ("Context Window", "num_ctx", "32768"),
            ("Max Tokens", "num_predict", "16384"),
            ("Temperature", "temperature", "0.3"),
        ]:
            r = ctk.CTkFrame(model_card, fg_color="transparent")
            r.pack(fill="x", padx=15, pady=4)
            ctk.CTkLabel(r, text=label, width=130, anchor="w").pack(side="left")
            e = ctk.CTkEntry(r, width=100)
            e.insert(0, str(self.config.get("model", key, default=default)))
            e.pack(side="left")
            setattr(self, f"model_{key}", e)

        ctk.CTkButton(model_card, text="Save Model Settings", height=36,
                      command=self._save_model).pack(padx=15, pady=(8, 15), fill="x")

        # ── Google Integration ────────────────────────────────
        self._section(scroll, "☁ Google Drive & Sheets")

        google_card = ctk.CTkFrame(scroll, corner_radius=10)
        google_card.pack(fill="x", pady=(0, 12))

        g_row = ctk.CTkFrame(google_card, fg_color="transparent")
        g_row.pack(fill="x", padx=15, pady=8)
        ctk.CTkLabel(g_row, text="Enable Integration", width=140, anchor="w").pack(side="left")
        self.google_enabled = ctk.BooleanVar(
            value=self.config.get("google", "enabled", default=False))
        ctk.CTkSwitch(g_row, variable=self.google_enabled, text="").pack(side="left")

        self.google_fields = {}
        google_cfg = [
            ("spreadsheet_id", "Spreadsheet ID", "1LedHC091RPLwoDcByN8xo..."),
            ("drive_folder",   "Drive Folder",   "Job Applications"),
            ("sheet_tab",      "Sheet Tab",      "Sheet1"),
        ]
        for key, label, ph in google_cfg:
            r = ctk.CTkFrame(google_card, fg_color="transparent")
            r.pack(fill="x", padx=15, pady=4)
            ctk.CTkLabel(r, text=label, width=140, anchor="w").pack(side="left")
            e = ctk.CTkEntry(r, placeholder_text=ph)
            e.insert(0, self.config.get("google", key, default=""))
            e.pack(side="left", fill="x", expand=True)
            self.google_fields[key] = e

        btn_row = ctk.CTkFrame(google_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=15, pady=(8, 15))
        ctk.CTkButton(btn_row, text="Save Google Settings", height=36,
                      command=self._save_google).pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(btn_row, text="Test Auth", height=36, width=100,
              fg_color="#333", hover_color="#444",
              command=self._test_google_auth).pack(side="left")

        # ── Appearance ────────────────────────────────────────
        self._section(scroll, "🎨 Appearance")
        app_card = ctk.CTkFrame(scroll, corner_radius=10)
        app_card.pack(fill="x", pady=(0, 12))
        r = ctk.CTkFrame(app_card, fg_color="transparent")
        r.pack(fill="x", padx=15, pady=12)
        ctk.CTkLabel(r, text="Theme", width=100, anchor="w").pack(side="left")
        self.theme = ctk.CTkOptionMenu(r, values=["dark", "light", "system"],
                                       command=lambda v: ctk.set_appearance_mode(v))
        self.theme.pack(side="left")
        ctk.CTkFrame(app_card, height=8, fg_color="transparent").pack()

    def _section(self, parent, title):
        ctk.CTkLabel(parent, text=title,
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", pady=(12, 4))

    def _save_model(self):
        self.config.set("model", "name", self.model_name.get().strip())
        keys_raw = self.api_keys_box.get("1.0", "end").strip()
        keys = [k.strip() for k in keys_raw.splitlines() if k.strip()]
        self.config.set("model", "api_keys", keys)
        for attr in ("num_ctx", "num_predict", "temperature"):
            try:
                val = getattr(self, f"model_{attr}").get()
                self.config.set("model", attr, float(val) if "." in val else int(val))
            except ValueError:
                pass
        self.config.save()
        messagebox.showinfo("Saved", "Model settings saved.")

    def _save_google(self):
        self.config.set("google", "enabled", self.google_enabled.get())
        for key, entry in self.google_fields.items():
            self.config.set("google", key, entry.get().strip())
        self.config.save()
        messagebox.showinfo("Saved", "Google settings saved.")

    def _test_google_auth(self):
        try:
            sys.path.insert(0, os.getcwd())
            from google_integration import _get_service
            drive = _get_service("drive", "v3")
            about = drive.about().get(fields="user").execute()
            email = about["user"]["emailAddress"]
            messagebox.showinfo("✅ Connected", f"Google auth successful!\nConnected as: {email}")
        except Exception as e:
            messagebox.showerror("Auth Failed", f"Google auth failed:\n{e}\n\nMake sure credentials.json is in project folder.")

# ══════════════════════════════════════════════════════════════
#  TAB: Logs
# ══════════════════════════════════════════════════════════════
class LogsTab(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._build()

    def _build(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=30, pady=(20, 8))

        ctk.CTkLabel(header, text="Application Logs",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")

        ctk.CTkButton(header, text="Clear", width=80, height=32,
                      fg_color="#333", hover_color="#444",
                      command=self.clear).pack(side="right")

        self.log_widget = LogWidget(self)
        self.log_widget.pack(fill="both", expand=True, padx=30, pady=(0, 20))

    def append(self, level, msg):
        self.log_widget.append(level, msg)

    def clear(self):
        self.log_widget.clear()

class ResumeTab(ctk.CTkFrame):
    def __init__(self, master, config, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.config   = config
        self.exp_rows = []
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="Resume & Projects",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                     pady=(20, 4), anchor="w", padx=30)
        ctk.CTkLabel(self,
                     text="Edit your resume, projects, and work experience used by the pipeline.",
                     text_color="gray", font=ctk.CTkFont(size=12)).pack(
                     anchor="w", padx=30, pady=(0, 12))

        # ── Tabview for sub-sections ──────────────────────────
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=30, pady=(0, 20))

        self.tabview.add("📄 Resume Text")
        self.tabview.add("📦 Projects")
        self.tabview.add("💼 Work Experience")

        self._build_resume_tab()
        self._build_projects_tab()
        self._build_experience_tab()

    # ── Resume text ───────────────────────────────────────────
    def _build_resume_tab(self):
        tab = self.tabview.tab("📄 Resume Text")

        header = ctk.CTkFrame(tab, fg_color="transparent")
        header.pack(fill="x", pady=(8, 4))
        ctk.CTkLabel(header, text="Paste your full resume text here",
                     text_color="gray", font=ctk.CTkFont(size=11)).pack(side="left")
        ctk.CTkButton(header, text="Load File", width=90, height=28,
                      fg_color="#333", hover_color="#444",
                      command=self._load_resume).pack(side="right", padx=4)
        ctk.CTkButton(header, text="💾 Save", width=80, height=28,
                      command=self._save_resume).pack(side="right")

        self.resume_box = ctk.CTkTextbox(
            tab, font=ctk.CTkFont(family="Consolas", size=11), wrap="word")
        self.resume_box.pack(fill="both", expand=True, pady=(4, 0))

        rp = self.config.get("pipeline", "resume_path", default="resume.txt")
        if os.path.exists(rp):
            with open(rp, "r", encoding="utf-8") as f:
                self.resume_box.insert("1.0", f.read())

    # ── Projects ──────────────────────────────────────────────
    def _build_projects_tab(self):
        tab = self.tabview.tab("📦 Projects")

        header = ctk.CTkFrame(tab, fg_color="transparent")
        header.pack(fill="x", pady=(8, 4))
        ctk.CTkLabel(header, text="List your projects — one per section",
                     text_color="gray", font=ctk.CTkFont(size=11)).pack(side="left")
        ctk.CTkButton(header, text="Load File", width=90, height=28,
                      fg_color="#333", hover_color="#444",
                      command=self._load_projects).pack(side="right", padx=4)
        ctk.CTkButton(header, text="💾 Save", width=80, height=28,
                      command=self._save_projects).pack(side="right")

        self.projects_box = ctk.CTkTextbox(
            tab, font=ctk.CTkFont(family="Consolas", size=11), wrap="word")
        self.projects_box.pack(fill="both", expand=True, pady=(4, 0))

        pp = self.config.get("pipeline", "projects_path", default="Projects.txt")
        if os.path.exists(pp):
            with open(pp, "r", encoding="utf-8") as f:
                self.projects_box.insert("1.0", f.read())

    # ── Work Experience ───────────────────────────────────────
    def _build_experience_tab(self):
        tab = self.tabview.tab("💼 Work Experience")

        info = ctk.CTkLabel(tab,
            text="Define your work history. These are injected into the experience prompt automatically.",
            text_color="gray", font=ctk.CTkFont(size=11))
        info.pack(anchor="w", pady=(8, 4))

        # Scrollable container for experience rows
        self.exp_scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.exp_scroll.pack(fill="both", expand=True, pady=(4, 8))

        # Load saved experience or use defaults
        saved_exp = self.config.get("experience_roles", default=None)
        if saved_exp:
            roles = saved_exp
        else:
            roles = [
                {
                    "title":       "Support Consultant",
                    "company":     "Nova Scotia Health Authority",
                    "dates":       "Feb 2026 – Present",
                    "domain":      "healthcare IT, systems, user support",
                    "total_bullets":  5,
                    "real_bullets":   2,
                    "fabricated_bullets": 3,
                },
                {
                    "title":       "Software Developer",
                    "company":     "TeleAI Corporation",
                    "dates":       "Jan 2025 – May 2025",
                    "domain":      "AI/ML, full-stack, APIs",
                    "total_bullets":  4,
                    "real_bullets":   2,
                    "fabricated_bullets": 2,
                },
                {
                    "title":       "R&D Project Engineer",
                    "company":     "MyTech Lab",
                    "dates":       "Sept 2024 – Dec 2024",
                    "domain":      "research, algorithms, optimization",
                    "total_bullets":  3,
                    "real_bullets":   1,
                    "fabricated_bullets": 2,
                },
                {
                    "title":       "Full-Stack Developer",
                    "company":     "Webforest LLP",
                    "dates":       "Jan 2023 – Jul 2023",
                    "domain":      "web development, databases, deployment",
                    "total_bullets":  4,
                    "real_bullets":   2,
                    "fabricated_bullets": 2,
                },
            ]

        self.exp_rows = []
        for role in roles:
            self._add_experience_row(role)

        # Bottom buttons
        btn_frame = ctk.CTkFrame(tab, fg_color="transparent")
        btn_frame.pack(fill="x", pady=4)
        ctk.CTkButton(btn_frame, text="+ Add Role", width=110, height=32,
                      fg_color="#333", hover_color="#444",
                      command=lambda: self._add_experience_row()).pack(side="left")
        ctk.CTkButton(btn_frame, text="💾 Save All", width=110, height=32,
                      command=self._save_experience).pack(side="right")

    def _add_experience_row(self, role: dict = None):
        role = role or {
            "title": "", "company": "", "dates": "",
            "domain": "", "total_bullets": 4,
            "real_bullets": 2, "fabricated_bullets": 2,
        }

        card = ctk.CTkFrame(self.exp_scroll, corner_radius=8)
        card.pack(fill="x", pady=5)

        # Row index label
        idx = len(self.exp_rows) + 1
        ctk.CTkLabel(card, text=f"Role {idx}",
                     font=ctk.CTkFont(weight="bold"),
                     text_color="#58a6ff").pack(anchor="w", padx=12, pady=(8, 4))

        fields = {}

        # Title + Company on same line
        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=3)
        row1.grid_columnconfigure(1, weight=1)
        row1.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(row1, text="Job Title", width=80, anchor="w").grid(row=0, column=0, sticky="w")
        fields["title"] = ctk.CTkEntry(row1)
        fields["title"].insert(0, role.get("title", ""))
        fields["title"].grid(row=0, column=1, sticky="ew", padx=(4, 12))

        ctk.CTkLabel(row1, text="Company", width=70, anchor="w").grid(row=0, column=2, sticky="w")
        fields["company"] = ctk.CTkEntry(row1)
        fields["company"].insert(0, role.get("company", ""))
        fields["company"].grid(row=0, column=3, sticky="ew", padx=(4, 0))

        # Dates + Domain on same line
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=3)
        row2.grid_columnconfigure(1, weight=1)
        row2.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(row2, text="Dates", width=80, anchor="w").grid(row=0, column=0, sticky="w")
        fields["dates"] = ctk.CTkEntry(row2, placeholder_text="Jan 2024 – Dec 2024")
        fields["dates"].insert(0, role.get("dates", ""))
        fields["dates"].grid(row=0, column=1, sticky="ew", padx=(4, 12))

        ctk.CTkLabel(row2, text="Domain", width=70, anchor="w").grid(row=0, column=2, sticky="w")
        fields["domain"] = ctk.CTkEntry(row2, placeholder_text="e.g. AI/ML, full-stack, APIs")
        fields["domain"].insert(0, role.get("domain", ""))
        fields["domain"].grid(row=0, column=3, sticky="ew", padx=(4, 0))

        # Bullet counts
        row3 = ctk.CTkFrame(card, fg_color="transparent")
        row3.pack(fill="x", padx=12, pady=(3, 8))

        for col, (label, key, default) in enumerate([
            ("Total Bullets",      "total_bullets",      4),
            ("Real Bullets",       "real_bullets",       2),
            ("Fabricated Bullets", "fabricated_bullets", 2),
        ]):
            ctk.CTkLabel(row3, text=label, anchor="w").grid(row=0, column=col*2, padx=(0 if col==0 else 16, 4), sticky="w")
            e = ctk.CTkEntry(row3, width=50)
            e.insert(0, str(role.get(key, default)))
            e.grid(row=0, column=col*2+1, sticky="w")
            fields[key] = e

        # Delete button
        del_btn = ctk.CTkButton(row3, text="✕ Remove", width=90, height=26,
                                fg_color="#6e1a1a", hover_color="#8b2121",
                                command=lambda c=card, f=fields: self._remove_role(c, f))
        del_btn.grid(row=0, column=6, padx=(20, 0))
        row3.grid_columnconfigure(6, weight=1)

        self.exp_rows.append(fields)

    def _remove_role(self, card, fields):
        self.exp_rows = [r for r in self.exp_rows if r is not fields]
        card.destroy()

    def _save_experience(self):
        roles = []
        for fields in self.exp_rows:
            try:
                roles.append({
                    "title":             fields["title"].get().strip(),
                    "company":           fields["company"].get().strip(),
                    "dates":             fields["dates"].get().strip(),
                    "domain":            fields["domain"].get().strip(),
                    "total_bullets":     int(fields["total_bullets"].get() or 4),
                    "real_bullets":      int(fields["real_bullets"].get() or 2),
                    "fabricated_bullets":int(fields["fabricated_bullets"].get() or 2),
                })
            except Exception:
                pass
        self.config.set("experience_roles", roles)
        self.config.save()

        # Also rebuild the experience prompt with new roles
        self._inject_roles_into_prompt(roles)
        messagebox.showinfo("Saved", f"Saved {len(roles)} work experience roles.")

    def _inject_roles_into_prompt(self, roles: list):
        """Rebuild the experience prompt roles section from saved roles."""
        roles_text = "\n".join([
            f"Role {i+1}: {r['title']} @ {r['company']} | {r['dates']}\n"
            f"→ {r['total_bullets']} bullets: {r['fabricated_bullets']} fabricated + "
            f"{r['real_bullets']} real ({r['domain']} domain)"
            for i, r in enumerate(roles)
        ])

        current_prompt = self.config.get("prompts", "experience_section", default="")

        # Replace the roles section between the markers
        import re as _re
        new_prompt = _re.sub(
            r'(ROLES — KEEP EXACTLY AS SHOWN.*?\n━+\n)(.*?)(━━━\nBULLET RULES)',
            lambda m: m.group(1) + roles_text + "\n\n" + m.group(3),
            current_prompt,
            flags=_re.DOTALL
        )

        if new_prompt != current_prompt:
            self.config.set("prompts", "experience_section", new_prompt)
        else:
            # Fallback — append roles to prompt if markers not found
            self.config.set("experience_roles", roles)

        self.config.save()

    # ── File helpers ──────────────────────────────────────────
    def _load_resume(self):
        path = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if path:
            with open(path, "r", encoding="utf-8") as f:
                self.resume_box.delete("1.0", "end")
                self.resume_box.insert("1.0", f.read())
            self.config.set("pipeline", "resume_path", path)
            self.config.save()

    def _save_resume(self):
        path = self.config.get("pipeline", "resume_path", default="resume.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.resume_box.get("1.0", "end-1c"))
        messagebox.showinfo("Saved", f"Resume saved → {path}")

    def _load_projects(self):
        path = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if path:
            with open(path, "r", encoding="utf-8") as f:
                self.projects_box.delete("1.0", "end")
                self.projects_box.insert("1.0", f.read())
            self.config.set("pipeline", "projects_path", path)
            self.config.save()

    def _save_projects(self):
        path = self.config.get("pipeline", "projects_path", default="Projects.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.projects_box.get("1.0", "end-1c"))
        messagebox.showinfo("Saved", f"Projects saved → {path}")
# ══════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ══════════════════════════════════════════════════════════════
class JobHunterApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("JobHunter")
        self.geometry("1280x800")
        self.minsize(1000, 650)

        self.config    = Config()
        self.log_queue = queue.Queue()

        # Setup logging
        handler = QueueLogHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(name)s — %(message)s"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

        # ← ADD THIS
        check_and_run_setup(self, self.config, on_complete=self._build_ui)
        # Only build UI if already configured (wizard calls on_complete itself)
        if self.config.get("setup_complete", default=False):
            self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Sidebar ───────────────────────────────────────────
        sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color="#161b22")
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_rowconfigure(10, weight=1)

        # Logo
        logo = ctk.CTkFrame(sidebar, fg_color="transparent")
        logo.grid(row=0, column=0, padx=16, pady=(20, 8), sticky="ew")
        ctk.CTkLabel(logo, text="JobHunter",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color="#58a6ff").pack(side="left")
        ctk.CTkLabel(logo, text=" v1.0",
                     font=ctk.CTkFont(size=11),
                     text_color="#666").pack(side="left", pady=(4, 0))

        ctk.CTkFrame(sidebar, height=1, fg_color="#21262d").grid(
            row=1, column=0, sticky="ew", padx=12, pady=4)

        nav_items = [
            ("Dashboard",  "🏠"),
            ("Scraper",    "🔍"),
            ("Pipeline",   "⚙"),
            ("Profile",    "👤"),   # ← ADD
            ("Resume",     "📄"),
            ("Prompts",    "✏"),
            ("Settings",   "⚙"),
            ("Logs",       "📋"),
        ]

        self.nav_buttons = {}
        for i, (name, icon) in enumerate(nav_items):
            btn = SidebarButton(sidebar, name, icon, lambda n=name: self._show_tab(n))
            btn.grid(row=i+2, column=0, padx=8, pady=2, sticky="ew")
            self.nav_buttons[name] = btn

        sidebar.grid_columnconfigure(0, weight=1)

        # Version info at bottom
        ctk.CTkLabel(sidebar, text="Built for Sneh Patel",
                     font=ctk.CTkFont(size=10), text_color="#444").grid(
            row=11, column=0, padx=16, pady=(0, 8), sticky="sw")

        # ── Content area ──────────────────────────────────────
        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color="#0d1117")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        # Build all tabs
        self.tabs = {
            "Dashboard": DashboardTab(self.content, self.config),
            "Scraper":   ScraperTab(self.content, self.config, self.log_queue),
            "Pipeline":  PipelineTab(self.content, self.config, self.log_queue),
            "Profile":   ProfileTab(self.content, self.config),   # ← ADD
            "Resume":    ResumeTab(self.content, self.config),
            "Prompts":   PromptsTab(self.content, self.config),
            "Settings":  SettingsTab(self.content, self.config),
            "Logs":      LogsTab(self.content),
        }
    
        for tab in self.tabs.values():
            tab.grid(row=0, column=0, sticky="nsew")

        self._show_tab("Dashboard")

    def _show_tab(self, name: str):
        for n, btn in self.nav_buttons.items():
            btn.set_active(n == name)
        for n, tab in self.tabs.items():
            if n == name:
                tab.tkraise()

    def _start_log_monitor(self):
        """Forward logs from queue to the Logs tab."""
        while not self.log_queue.empty():
            try:
                kind, level, msg = self.log_queue.get_nowait()
                if kind == "log":
                    self.tabs["Logs"].append(level, msg)
            except queue.Empty:
                break
        self.after(500, self._start_log_monitor)


# ── Entry point ───────────────────────────────────────────────
if __name__ == "__main__":
    app = JobHunterApp()
    app.mainloop()