# agents/resume_builder.py
import re
import json
import os
import logging
from datetime import date
from agents.api_client import RotatingOllamaClient
from ai import load_profile
from setup_wizard import build_fixed_header

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# LATEX PREAMBLE — never changes, never configurable
# ══════════════════════════════════════════════════════════════

LATEX_PREAMBLE = r"""
\documentclass[letterpaper,10pt]{article}
\usepackage[empty]{fullpage}
\usepackage{titlesec}
\usepackage[usenames,dvipsnames]{color}
\usepackage{verbatim}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\usepackage{fancyhdr}
\usepackage[english]{babel}
\usepackage{tabularx}
\usepackage{fontawesome5}
\usepackage{multicol}
\setlength{\multicolsep}{-3.0pt}
\setlength{\columnsep}{-1pt}
\input{glyphtounicode}
\pagestyle{fancy}
\fancyhf{}
\fancyfoot{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}
\setlength{\footskip}{4pt}
\addtolength{\oddsidemargin}{-0.6in}
\addtolength{\evensidemargin}{-0.5in}
\addtolength{\textwidth}{1.19in}
\addtolength{\topmargin}{-.7in}
\addtolength{\textheight}{1.4in}
\urlstyle{same}
\raggedbottom
\raggedright
\setlength{\tabcolsep}{0in}
\titleformat{\section}{\vspace{-4pt}\scshape\raggedright\large\bfseries}{}{0em}{}[\color{black}\titlerule \vspace{-5pt}]
\pdfgentounicode=1
\newcommand{\resumeItem}[1]{\item\small{#1 \vspace{-2pt}}}
\newcommand{\resumeSubheading}[4]{
  \vspace{-2pt}\item
    \begin{tabular*}{1.0\textwidth}[t]{l@{\extracolsep{\fill}}r}
      \textbf{#1} & \textbf{\small #2} \\
      \textit{\small#3} & \textit{\small #4} \\
    \end{tabular*}\vspace{-7pt}
}
\newcommand{\resumeProjectHeading}[2]{
    \item
    \begin{tabular*}{1\textwidth}{l@{\extracolsep{\fill}}r}
      \small#1 & \textbf{\small #2}\\
    \end{tabular*}\vspace{-7pt}
}
\newcommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=0.0in, label={}]}
\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}\vspace{-5pt}}
\begin{document}
"""

# ══════════════════════════════════════════════════════════════
# FIXED HEADER & EDUCATION — set by setup_wizard from profile
# Can be overridden by setup_wizard.py at runtime
# ══════════════════════════════════════════════════════════════

FIXED_HEADER = r"""
\begin{center}
    {\Huge \scshape Your Name} \\ \vspace{6pt}
    \vspace{2pt}
    \href{tel:+10000000000}{\raisebox{-0.2\height}\faPhone\ \underline{+1 (000) 000-0000}} ~
    \href{mailto:your@email.com}{\raisebox{-0.2\height}\faEnvelope\ \underline{your@email.com}}
\end{center}
\vspace{2pt}
"""

FIXED_EDUCATION = r"""
\section{Education}
\resumeSubHeadingListStart
  \resumeSubheading{Your Degree}{Start -- End}{Your University}{City, Province}
\resumeSubHeadingListEnd
"""

# ══════════════════════════════════════════════════════════════
# SYSTEM PROMPTS — hardcoded, enforce LaTeX output format
# These are NEVER user-editable. They define the output contract.
# ══════════════════════════════════════════════════════════════

_SYSTEM_SKILLS = """
You are an expert resume writer. Output ONLY raw LaTeX — no backticks, no explanation.
Generate ONLY the TECHNICAL SKILLS section body.

OUTPUT FORMAT CONTRACT (never deviate):
\\section{Technical Skills}
 \\begin{itemize}[leftmargin=0.15in, label={}]
    \\small{\\item{
     \\textbf{Category 1}{: tool1, tool2, tool3} \\\\
     \\textbf{Category 2}{: tool1, tool2, tool3} \\\\
     ... (5-6 categories)
    }}
 \\end{itemize}

ABSOLUTE RULES:
- NO \\documentclass, NO \\usepackage, NO \\begin{document}, NO \\end{document}
- All % → \\%, all & → \\&
- No em dashes, no ->, no <>, no arrows
- Output the \\section{Technical Skills} block ONLY
"""

_SYSTEM_EXPERIENCE = """
You are an expert resume writer and career strategist.
Output ONLY raw LaTeX — no backticks, no explanation.
Generate ONLY the EXPERIENCE section body.

OUTPUT FORMAT CONTRACT (never deviate):
\\section{Experience}
\\resumeSubHeadingListStart
  \\resumeSubheading{Job Title}{Start Date -- End Date}{Company Name}{Location}
  \\resumeItemListStart
    \\resumeItem{bullet text spanning exactly 2 full lines with a \\textbf{metric}}
    ...
  \\resumeItemListEnd
\\resumeSubHeadingListEnd

ABSOLUTE RULES:
- NO \\documentclass, NO \\usepackage, NO \\begin{document}, NO \\end{document}
- Every bullet = exactly 2 full lines. NEVER one-liners.
- Every bullet has a specific number/metric
- \\textbf{} on 2-3 key terms per bullet only
- All % → \\%, all & → \\&
- No em dashes, no ->, no <>, no arrows
- Output the \\section{Experience} block ONLY
"""

_SYSTEM_PROJECTS = """
You are an expert resume writer. Output ONLY raw LaTeX — no backticks, no explanation.
Generate ONLY the RELEVANT PROJECTS section body.

OUTPUT FORMAT CONTRACT (never deviate):
\\section{Relevant Projects}
\\resumeSubHeadingListStart
  \\resumeProjectHeading{\\textbf{Project Name} $|$ \\emph{Tech1, Tech2, Tech3}}{{}}
  \\resumeItemListStart
    \\resumeItem{bullet 1}
    \\resumeItem{bullet 2}
    \\resumeItem{bullet 3}
  \\resumeItemListEnd
\\resumeSubHeadingListEnd

ABSOLUTE RULES:
- NO \\documentclass, NO \\usepackage, NO \\begin{document}, NO \\end{document}
- 3-4 projects, 2-3 bullets each
- Every bullet has a specific number/metric
- All % → \\%, all & → \\&
- No em dashes, no ->, no <>, no arrows
- Output the \\section{Relevant Projects} block ONLY
"""

_SYSTEM_COVER_LETTER = """
You are an expert cover letter writer.
Output ONLY the plain text cover letter — no LaTeX, no backticks, no JSON, no explanation.
4 paragraphs maximum. Semi-formal, honest, human tone.
NEVER use em dashes (—), ->, =>, <>, or any arrow symbols.
"""

_SYSTEM_SURGICAL = """
You are a resume editor making precise surgical edits to existing LaTeX.
Apply ONLY the requested changes. Do NOT rewrite or regenerate anything else.
Keep all company names, role titles, dates, and structure exactly as-is.
Output ONLY the corrected LaTeX section — no backticks, no explanation.
CRITICAL: NO \\documentclass, NO \\usepackage, NO \\begin{document}, NO \\end{document}.
"""

# ══════════════════════════════════════════════════════════════
# DEFAULT USER PROMPTS — used as fallback if app_config.json
# has no prompts. These are the detailed versions.
# ══════════════════════════════════════════════════════════════

_DEFAULT_PROMPT_SKILLS = """You are an expert resume writer specializing in ATS optimization.
Output ONLY raw LaTeX for the Technical Skills section.

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
1. Extract EVERY distinct technical skill, tool, framework, platform in the JD.
2. Map each JD keyword to the candidate's existing skills.
3. Create 5-6 categories matching JD domain terminology exactly.
4. FRONT-LOAD: Put the most JD-relevant keywords FIRST in each category.
5. Include JD-specific tools even if candidate used equivalents.
6. Category names should mirror JD language exactly.

RULES:
- All % → \\%, all & → \\&
- No special chars: no ->, no <>, no em dashes
- Use exact JD terminology where possible
- 8-12 items per category maximum"""

_DEFAULT_PROMPT_EXPERIENCE = """You are an expert resume writer and career strategist.
Output ONLY raw LaTeX for the Experience section.

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
For each role, write FABRICATED bullets FIRST, then REAL bullets.

FABRICATED bullets must:
- Directly match a JD requirement that real experience doesn't cover
- Sound 100% realistic — specific domain, realistic metrics, believable scope
- Use EXACT JD keywords naturally woven in
- Be indistinguishable from real bullets
- Have concrete numbers: team sizes (3-8 people), percentages (15-65%), time saved

REAL bullets must:
- Be rewritten to use JD terminology where possible
- Keep core achievement but rephrase with JD keywords

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ROLES — KEEP EXACTLY AS SHOWN (name, title, dates LOCKED)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{experience_roles}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BULLET RULES (NON-NEGOTIABLE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- EVERY bullet = exactly 2 full lines in LaTeX. Never one-liners.
- EVERY bullet has a specific metric (%, count, time, scale)
- Use \\textbf{{}} on 2-3 key terms per bullet only
- Start each bullet with a strong action verb
- All % → \\%, all & → \\&"""

_DEFAULT_PROMPT_PROJECTS = """You are an expert resume writer specializing in project showcasing.
Output ONLY raw LaTeX for the Relevant Projects section.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JOB TITLE:   {title}
COMPANY:     {company}
JOB DESCRIPTION:
{description}

CANDIDATE'S EXISTING RESUME (reference for tech stack):
{existing_resume}

AVAILABLE PROJECTS (select 3-4 most relevant):
{projects}

ATS FEEDBACK (MUST address every point):
{ats_feedback}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Identify top 5 technical requirements from JD.
2. Select 3-4 projects from the list that best demonstrate those requirements.
3. If a critical JD skill has NO matching project, FABRICATE a realistic project.
4. For each project, write 2-3 bullets:
   Bullet 1: Problem + technology + scale
   Bullet 2: Technical implementation + specific JD tool
   Bullet 3: Measurable outcome (performance, users, accuracy)

BULLET RULES:
- Every bullet = 2 full lines minimum
- Every bullet has a specific number/metric
- Use \\textbf{{}} on project name and 1-2 key technologies
- All % → \\%, all & → \\&

PROJECT LINKING RULE:
- Each project entry in the AVAILABLE PROJECTS list contains a URL.
- If the prompt template asks for \\href{{url}}, replace 'url' with the ACTUAL URL from the project data.
- DO NOT write the word "url" or "link" in the LaTeX; use the real GitHub link.
"""

_DEFAULT_PROMPT_COVER_LETTER = """You are writing a cover letter for {candidate_name}.
Output ONLY the plain text cover letter.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JOB TITLE:   {title}
COMPANY:     {company}
JOB DESCRIPTION:
{description}

CANDIDATE'S RESUME (reference for real experience):
{existing_resume}

TODAY'S DATE: {today}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TONE GUIDELINES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Semi-formal but genuinely human
- Reference SPECIFIC things from the JD
- Tell small stories — one concrete moment, not just lists
- Each letter unique — different angle, different story

NEVER USE:
- Em dashes (—) anywhere
- Arrow symbols (->, =>, <>)
- Corporate filler phrases
- Bullet points
- More than 4 paragraphs

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXACT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{candidate_name}
{candidate_phone}
{candidate_email}

{today}

Hiring Manager,
{company}
[Extract city from JD. If remote/unclear: Canada]

Subject: Application for {title}

Dear Hiring Manager,

[PARAGRAPH 1 — 3-5 sentences: What attracted you to this role. Reference one concrete JD detail.]

[PARAGRAPH 2 — 4-6 sentences: 2-3 specific examples from experience matching JD. Real technologies naturally. At least one specific number.]

[PARAGRAPH 3 — 3-4 sentences: Learning approach — building side projects, open-source preference. Honest and specific.]

[PARAGRAPH 4 — 2-3 sentences: Why this company specifically. Confident close.]

Warm regards,
{candidate_name}
{candidate_email}

Plain text ONLY. No formatting symbols."""


# ══════════════════════════════════════════════════════════════
# CONFIG LOADER — loads user prompts from app_config.json
# Falls back to detailed defaults if not found
# ══════════════════════════════════════════════════════════════

def _load_user_prompts() -> dict:
    """
    Load configurable user prompt templates from app_config.json.
    Falls back to hardcoded defaults if file missing or prompts empty.
    """
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app_config.json"
    )
    try:
        if os.path.exists(config_path):
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            prompts = data.get("prompts", {})
            if prompts:
                logger.debug("Loaded prompts from app_config.json")
                return prompts
    except Exception as e:
        logger.warning("Could not load prompts from app_config.json: %s", e)
    logger.debug("Using default hardcoded prompts")
    return {}


def _load_experience_roles() -> str:
    """Load work experience roles from app_config.json for injection into prompts."""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app_config.json"
    )
    try:
        if os.path.exists(config_path):
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            roles = data.get("experience_roles", [])
            if roles:
                lines = []
                for i, r in enumerate(roles, 1):
                    lines.append(
                        f"Role {i}: {r.get('title','')} @ {r.get('company','')} | {r.get('dates','')}\n"
                        f"→ {r.get('total_bullets', 4)} bullets: "
                        f"{r.get('fabricated_bullets', 2)} fabricated + "
                        f"{r.get('real_bullets', 2)} real ({r.get('domain','')} domain)"
                    )
                return "\n".join(lines)
    except Exception:
        pass
    return (
        "Role 1: Job Title @ Company Name | Start – End\n→ 4 bullets: 2 fabricated + 2 real"
    )


def _load_profile() -> dict:
    """Load user profile for cover letter personalisation."""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app_config.json"
    )
    defaults = {
        "full_name": "Candidate Name",
        "phone":     "+91 000-000-0000",
        "email":     "candidate@email.com",
    }
    try:
        if os.path.exists(config_path):
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            profile = data.get("profile", {})
            defaults.update({k: v for k, v in profile.items() if v})
    except Exception:
        pass
    return defaults


# Load once at import time
_CONFIG_PROMPTS   = _load_user_prompts()
PROMPT_SKILLS     = _CONFIG_PROMPTS.get("skills_section")     or _DEFAULT_PROMPT_SKILLS
PROMPT_EXPERIENCE = _CONFIG_PROMPTS.get("experience_section") or _DEFAULT_PROMPT_EXPERIENCE
PROMPT_PROJECTS   = _CONFIG_PROMPTS.get("projects_section")   or _DEFAULT_PROMPT_PROJECTS
PROMPT_COVER_LETTER = _CONFIG_PROMPTS.get("cover_letter")     or _DEFAULT_PROMPT_COVER_LETTER


# ══════════════════════════════════════════════════════════════
# RESUME BUILDER AGENT
# ══════════════════════════════════════════════════════════════

class ResumeBuilderAgent:
    def __init__(self, client: RotatingOllamaClient, projects_text: str, existing_resume: str):
        self.client          = client
        self.projects_text   = projects_text
        self.existing_resume = existing_resume

    # ── Main build — Dynamic sections ──────────────────────────
    def build(self, title: str, company: str, description: str, ats_feedback="", location="", use_jd_location=True, default_location="Canada") -> tuple[str, str]:
        fb        = self._parse_ats_feedback(ats_feedback)
        safe_desc = self._safe(description)
        profile   = _load_profile()
        exp_roles = _load_experience_roles()

        # Reload prompts each call so live edits from app are picked up
        prompts       = _load_user_prompts()
        p_skills      = prompts.get("skills_section")     or PROMPT_SKILLS
        p_experience  = prompts.get("experience_section") or PROMPT_EXPERIENCE
        p_projects    = prompts.get("projects_section")   or PROMPT_PROJECTS
        p_cover       = prompts.get("cover_letter")       or PROMPT_COVER_LETTER

        # Build Header and Education from profile
        include_links = profile.get("include_links", True)
        if use_jd_location:
            location_override = self._extract_location(description, location)
            if not location_override:
                location_override = default_location
        else:
            location_override = default_location
        header = build_fixed_header(profile, location_override=location_override, include_links=include_links)

        edu_list = profile.get("education", [])
        if edu_list:
            edu_content = "\n".join([
                f"  \\resumeSubheading{{{e.get('degree','Your Degree')}}}{{{e.get('dates','Start -- End')}}}{{{e.get('institution','Your University')}}}{{{e.get('location','City, Province')}}}"
                for e in edu_list
            ])
            education = r"""
\section{Education}
\resumeSubHeadingListStart
""" + edu_content + r"""
\resumeSubHeadingListEnd
"""
        else:
            education = FIXED_EDUCATION

        # ── Standard Sections ─────────────────────────────────────
        section_map = {"education": education}

        logger.info("Building skills section...")
        section_map["skills"] = self._clean(self.client.complete(
            system=_SYSTEM_SKILLS,
            user=p_skills.format(
                title=title, company=company,
                description=safe_desc,
                existing_resume=self.existing_resume,
                ats_feedback=fb.get("skills", "None — first attempt."),
            ),
        ))

        logger.info("Building experience section...")
        section_map["experience"] = self._clean(self.client.complete(
            system=_SYSTEM_EXPERIENCE,
            user=p_experience.format(
                title=title, company=company,
                description=safe_desc,
                existing_resume=self.existing_resume,
                ats_feedback=fb.get("experience", "None — first attempt."),
                experience_roles=exp_roles,
            ),
        ))

        logger.info("Building projects section...")
        section_map["projects"] = self._clean(self.client.complete(
            system=_SYSTEM_PROJECTS,
            user=p_projects.format(
                title=title, company=company,
                description=safe_desc,
                projects=self.projects_text,
                existing_resume=self.existing_resume,
                ats_feedback=fb.get("projects", "None — first attempt."),
            ),
        ))

        # ── Custom Sections ──────────────────────────────────────
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app_config.json")
        custom_sections = []
        try:
            if os.path.exists(config_path):
                with open(config_path, encoding="utf-8") as f:
                    custom_sections = json.load(f).get("custom_sections", [])
        except Exception as e:
            logger.warning("Could not load custom sections: %s", e)

        for cs in custom_sections:
            cs_id = cs.get("id")
            if not cs_id: continue
            logger.info("Building custom section: %s", cs_id)

            # Use a generic feedback key if specific one doesn't exist
            cs_feedback = fb.get(cs_id, fb.get("skills", "None — first attempt."))

            section_content = self._clean(self.client.complete(
                system=cs.get("system_prompt", "You are an expert resume writer."),
                user=cs.get("user_prompt", "").format(
                    full_name=profile.get("full_name", "Your Name"),
                    title=title,
                    company=company,
                    description=safe_desc,
                    existing_resume=self.existing_resume,
                    ats_feedback=cs_feedback
                ),
            ))
            section_map[cs_id] = section_content

        logger.info("Building cover letter...")
        cover_letter = self.client.complete(
            system=_SYSTEM_COVER_LETTER,
            user=p_cover.format(
                title=title, company=company,
                description=safe_desc,
                existing_resume=self.existing_resume,
                today=date.today().strftime("%B %d, %Y"),
                candidate_name=profile.get("full_name", "Your Name"),
                candidate_phone=profile.get("phone", "+1 (000) 000-0000"),
                candidate_email=profile.get("email", "your@email.com"),
                full_name=profile.get("full_name", "Your Name"),
                phone=profile.get("phone", "+1 (000) 000-0000"),
                email=profile.get("email", "your@email.com"),
            ),
        ).strip()

        latex = self._assemble(header, education, section_map)
        logger.info("Resume assembled: %d chars | Cover: %d chars", len(latex), len(cover_letter))
        return latex, cover_letter

    # ── Surgical rebuild — one section only ──────────────────
    def rebuild_section(
        self,
        section: str,
        title: str,
        company: str,
        description: str,
        feedback: str,
        current_latex: str = "",
    ) -> str:
        logger.info("Surgical rebuild: '%s'", section)
        safe_desc = self._safe(description)

        if section == "skills":
            user = f"""CURRENT TECHNICAL SKILLS SECTION (edit ONLY this):
{current_latex}

JOB TITLE: {title}
JOB DESCRIPTION: {safe_desc}

EXACT FIXES TO APPLY:
{feedback}

RULES:
- Keep all existing categories and tools
- Only ADD missing keywords from feedback
- Do NOT remove anything
- All % → \\%, all & → \\&
- Output ONLY the \\section{{Technical Skills}} block"""

        elif section == "experience":
            exp_roles = _load_experience_roles()
            user = f"""CURRENT EXPERIENCE SECTION (surgical edits only):
{current_latex}

JOB TITLE: {title}
JOB DESCRIPTION: {safe_desc}

EXACT FIXES TO APPLY:
{feedback}

STRICT RULES:
- Company names, role titles, dates are LOCKED — do NOT change
- Only rewrite bullets mentioned in feedback
- Every bullet stays 2 full lines with a metric
- Output ONLY the \\section{{Experience}} block"""

        elif section == "projects":
            user = f"""CURRENT PROJECTS SECTION (surgical edits only):
{current_latex}

JOB TITLE: {title}
JOB DESCRIPTION: {safe_desc}

AVAILABLE PROJECTS FOR REPLACEMENT:
{self.projects_text}

EXACT FIXES TO APPLY:
{feedback}

RULES:
- Only modify/replace projects mentioned in feedback
- Keep other projects exactly as-is
- Every bullet has a metric
- Output ONLY the \\section{{Relevant Projects}} block"""

        else:
            cs_data = self._load_custom_section_data(section)
            if not cs_data:
                raise ValueError(f"Unknown section: {section}")
            profile = _load_profile()
            system = cs_data.get("system_prompt", _SYSTEM_SURGICAL)
            user_template = cs_data.get("user_prompt", "")
            try:
                user = user_template.format(
                    full_name=profile.get("full_name", "Your Name"),
                    title=title,
                    company=company,
                    description=safe_desc,
                    existing_resume=self.existing_resume,
                    ats_feedback=feedback,
                )
            except (KeyError, IndexError):
                user = (
                    f"Rewrite the {cs_data.get('name', section)} section.\n\n"
                    f"CURRENT:\n{current_latex}\n\n"
                    f"JOB TITLE: {title}\n"
                    f"ATS FEEDBACK:\n{feedback}"
                )
            result = self.client.complete(system=system, user=user)
            return self._clean(result)

        result = self.client.complete(system=_SYSTEM_SURGICAL, user=user)
        return self._clean(result)

    # ── Assembly ──────────────────────────────────────────────
    @staticmethod
    def _assemble(header, education, section_map) -> str:
        import json as _json
        import os as _os

        # Load section order from app_config.json
        # Check root-level first (set by ResumeOrderTab), then pipeline fallback
        order = ["education", "skills", "experience", "projects"]
        try:
            config_path = _os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                "app_config.json"
            )
            if _os.path.exists(config_path):
                with open(config_path, encoding="utf-8") as f:
                    cfg = _json.load(f)
                saved = (
                    cfg.get("section_order")
                    or cfg.get("pipeline", {}).get("section_order", [])
                )
                if saved:
                    order = list(saved)
        except Exception:
            pass

        # Always append any custom section keys from section_map that aren't
        # already in order — ensures newly added custom sections are included
        # even if the user hasn't re-saved from the Resume Order tab.
        base_keys = {"education", "skills", "experience", "projects"}
        for key in section_map:
            if key not in base_keys and key not in order and section_map[key].strip():
                order.append(key)

        result = LATEX_PREAMBLE + "\n\n" + header
        for key in order:
            content = section_map.get(key, "")
            if content.strip():
                result += "\n\n" + content
        result += "\n\n\\end{document}"
        return result
    

    # ── Location extractor ────────────────────────────────────
    @staticmethod
    def _extract_location(description: str, location_field: str = "") -> str | None:
        text_to_search = (description + " " + location_field).lower()
        city_map = {
            "toronto":       "Toronto, ON, Canada",
            "vancouver":     "Vancouver, BC, Canada",
            "calgary":       "Calgary, AB, Canada",
            "ottawa":        "Ottawa, ON, Canada",
            "montreal":      "Montreal, QC, Canada",
            "edmonton":      "Edmonton, AB, Canada",
            "winnipeg":      "Winnipeg, MB, Canada",
            "halifax":       "Halifax, NS, Canada",
            "waterloo":      "Waterloo, ON, Canada",
            "kitchener":     "Kitchener, ON, Canada",
            "moncton":       "Moncton, NB, Canada",
        }
        for city, formatted in city_map.items():
            if city in text_to_search:
                return formatted
        if any(x in text_to_search for x in ["remote", "canada-wide", "anywhere in canada", "work from home"]) and "canada" in text_to_search:
            return "Canada"
        return None

    # ── Helpers ───────────────────────────────────────────────
    @staticmethod
    def _safe(description: str) -> str:
        s = str(description).strip()
        return s if s and s not in ("nan", "None", "") else "Not provided"

    @staticmethod
    def _strip_backticks(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            m = re.search(r"```(?:latex|tex)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return text

    @staticmethod
    def _strip_to_body(text: str) -> str:
        """Remove any preamble the LLM accidentally adds."""
        text = text.replace("\\end{document}", "").strip()
        preamble_markers = [
            "\\documentclass", "\\usepackage", "\\pagestyle",
            "\\fancyhf", "\\addtolength", "\\titleformat",
            "\\newcommand", "\\setlength", "\\pdfgentounicode",
            "\\urlstyle", "\\raggedbottom", "\\input{glyph",
            "\\begin{document}",
        ]
        lines = text.split("\n")
        clean = []
        skip  = True
        for line in lines:
            if skip and any(x in line for x in preamble_markers):
                continue
            else:
                skip = False
                clean.append(line)
        return "\n".join(clean).strip()

    def _clean(self, text: str) -> str:
        return self._strip_to_body(self._strip_backticks(text))

    @staticmethod
    def _parse_ats_feedback(feedback) -> dict:
        if not feedback:
            return {"skills": "", "experience": "", "projects": ""}
        if isinstance(feedback, dict):
            result = {
                "skills":     feedback.get("skills_feedback",     ""),
                "experience": feedback.get("experience_feedback", ""),
                "projects":   feedback.get("projects_feedback",   ""),
            }
            skip = {"skills_feedback", "experience_feedback", "projects_feedback", "cover_letter_feedback"}
            for k, v in feedback.items():
                if k.endswith("_feedback") and k not in skip:
                    result[k[:-len("_feedback")]] = str(v)
            return result
        return {"skills": str(feedback), "experience": str(feedback), "projects": str(feedback)}

    @staticmethod
    def _load_custom_section_data(section_id: str) -> dict | None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app_config.json"
        )
        try:
            if os.path.exists(config_path):
                with open(config_path, encoding="utf-8") as f:
                    data = json.load(f)
                for cs in data.get("custom_sections", []):
                    if cs.get("id") == section_id:
                        return cs
        except Exception:
            pass
        return None