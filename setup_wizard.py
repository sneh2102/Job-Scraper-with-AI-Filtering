"""
setup_wizard.py
===============
Drop this file into Job-Scraper-with-AI-Filtering/
Then in app.py add at the bottom of __init__, before _build_ui():

    from setup_wizard import check_and_run_setup
    check_and_run_setup(self, self.config)

This module handles:
1. First-run setup wizard (multi-step)
2. ProfileTab class for ongoing profile editing
3. Dynamic resume header/education generation
4. All hardcoded names replaced with config values
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import os
import json


# ══════════════════════════════════════════════════════════════
#  DYNAMIC PROFILE HELPERS
#  Used by pipeline.py and resume_builder.py
# ══════════════════════════════════════════════════════════════

def load_profile(config_file="app_config.json") -> dict:
    """Load user profile from app_config.json."""
    defaults = {
        "full_name":      "Your Name",
        "phone":          "+1 000-000-0000",
        "email":          "your@email.com",
        "linkedin":       "linkedin.com/in/yourprofile",
        "github":         "github.com/yourusername",
        "location":       "Your City, Province, Country",
        "experience_yrs": "0",
        "education": [
            {
                "degree":      "Your Degree",
                "dates":       "Start Date -- End Date",
                "institution": "Your University",
                "location":    "City, Country",
            },
        ],
        "core_stack":     "Python, JavaScript, React, Node.js, AWS, Docker",
        "domains":        "Full-Stack Development, Cloud/DevOps",
        "not_fit_for":    "Pure QA, Manual Testing, Hardware Engineering, Non-technical",
        "job_titles":     "Software Developer, Full Stack Developer",
    }
    try:
        if os.path.exists(config_file):
            with open(config_file, encoding="utf-8") as f:
                data = json.load(f)
            profile = data.get("profile", {})
            for k, v in defaults.items():
                if k not in profile:
                    profile[k] = v
            return profile
    except Exception:
        pass
    return defaults


def build_fixed_header(profile: dict, location_override: str = None) -> str:
    """Generate the LaTeX header block from profile data."""
    name     = profile.get("full_name",  "Your Name")
    phone    = profile.get("phone",      "+1 000-000-0000")
    email    = profile.get("email",      "your@email.com")
    linkedin = profile.get("linkedin",   "")
    github   = profile.get("github",     "")
    location = location_override or profile.get("location",   "Your City, Province, Country")

    # Build contact line
    contact_parts = []
    if phone:
        ph_clean = phone.replace(" ", "").replace("-", "").replace("(","").replace(")","")
        contact_parts.append(
            f"\\href{{tel:{ph_clean}}}{{\\raisebox{{-0.2\\height}}\\faPhone*\\ \\underline{{{phone}}}}}"
        )
    if email:
        contact_parts.append(
            f"\\href{{mailto:{email}}}{{\\raisebox{{-0.2\\height}}\\faEnvelope\\ \\underline{{{email}}}}}"
        )
    if linkedin:
        handle = linkedin.split("/in/")[-1].strip("/") if "/in/" in linkedin else linkedin
        contact_parts.append(
            f"\\href{{https://{linkedin if linkedin.startswith('linkedin') else 'linkedin.com/in/'+handle}}}"
            f"{{\\raisebox{{-0.2\\height}}\\faLinkedin\\ \\underline{{{handle}}}}}"
        )
    if github:
        gh_handle = github.split("github.com/")[-1].strip("/") if "github.com" in github else github
        contact_parts.append(
            f"\\href{{https://github.com/{gh_handle}}}"
            f"{{\\raisebox{{-0.2\\height}}\\faGithub\\ \\underline{{{gh_handle}}}}}"
        )

    contact_line = " ~\n    ".join(contact_parts)

    return f"""
\\begin{{center}}
    {{\\Huge \\scshape {name}}} \\\\ \\vspace{{6pt}}
    \\faMapMarker*\\ {location} \\\\
    \\vspace{{2pt}}
    {contact_line}
\\end{{center}}
\\vspace{{2pt}}
"""


def build_fixed_education(profile: dict) -> str:
    """Generate the LaTeX education section from profile data."""
    edu_list = profile.get("education", [])
    if not edu_list:
        return ""

    items = []
    for edu in edu_list:
        degree      = edu.get("degree",      "Degree")
        dates       = edu.get("dates",       "")
        institution = edu.get("institution", "University")
        location    = edu.get("location",    "")
        items.append(
            f"  \\resumeSubheading{{{degree}}}{{{dates}}}{{{institution}}}{{{location}}}"
        )

    items_str = "\n".join(items)
    return f"""
\\section{{Education}}
\\resumeSubHeadingListStart
{items_str}
\\resumeSubHeadingListEnd
"""


def build_profile_prompt_context(profile: dict) -> str:
    """Build the candidate profile section for AI prompts."""
    return f"""Name:           {profile.get('full_name', 'Candidate')}
Experience:     ~{profile.get('experience_yrs', '3')} years
Education:      {' | '.join([e.get('degree','') + ' — ' + e.get('institution','') for e in profile.get('education', [])])}
Location:       {profile.get('location', 'Canada')} — open to Remote, Hybrid, Relocation
Core Stack:     {profile.get('core_stack', 'Python, JavaScript, React, AWS, Docker')}
Domains:        {profile.get('domains', 'Full-Stack Development, Cloud/DevOps')}
Job Targets:    {profile.get('job_titles', 'Software Developer, Full Stack Developer')}
NOT a fit for:  {profile.get('not_fit_for', 'Pure QA, Hardware Engineering')}"""


# ══════════════════════════════════════════════════════════════
#  SETUP WIZARD
# ══════════════════════════════════════════════════════════════

class SetupWizard(ctk.CTkToplevel):
    STEPS = [
        "Welcome",
        "Your Profile",
        "Education",
        "Work Experience",
        "AI Model",
        "Job Search",
        "Done",
    ]

    def __init__(self, master, config, on_complete):
        super().__init__(master)
        self.config      = config
        self.on_complete = on_complete
        self.step        = 0
        self.edu_rows    = []
        self.exp_rows    = []

        self.title("JobHunter — First Time Setup")
        self.geometry("780x620")
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._skip)

        self._build_shell()
        self._show_step(0)

    # ── Shell (sidebar + content) ─────────────────────────────
    def _build_shell(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        sidebar = ctk.CTkFrame(self, width=180, fg_color="#161b22", corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")

        ctk.CTkLabel(sidebar, text="Setup",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="#58a6ff").pack(padx=20, pady=(20, 15), anchor="w")

        self.step_labels = []
        for i, name in enumerate(self.STEPS):
            lbl = ctk.CTkLabel(sidebar, text=f"  {name}",
                               font=ctk.CTkFont(size=12),
                               text_color="#555", anchor="w", width=140)
            lbl.pack(padx=10, pady=3, anchor="w")
            self.step_labels.append(lbl)

        # Content
        self.content_frame = ctk.CTkFrame(self, fg_color="#0d1117", corner_radius=0)
        self.content_frame.grid(row=0, column=1, sticky="nsew")
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(0, weight=1)

        # Nav buttons
        nav = ctk.CTkFrame(self.content_frame, fg_color="#161b22", corner_radius=0)
        nav.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
        nav.grid_columnconfigure(1, weight=1)

        self.skip_btn = ctk.CTkButton(nav, text="Skip Setup", width=100, height=32,
                                       fg_color="#333", hover_color="#444",
                                       command=self._skip)
        self.skip_btn.grid(row=0, column=0, padx=12, pady=10)

        self.progress_lbl = ctk.CTkLabel(nav, text="Step 1 of 7",
                                          text_color="#555", font=ctk.CTkFont(size=11))
        self.progress_lbl.grid(row=0, column=1)

        self.back_btn = ctk.CTkButton(nav, text="← Back", width=90, height=32,
                                       fg_color="#333", hover_color="#444",
                                       command=self._back)
        self.back_btn.grid(row=0, column=2, padx=4, pady=10)

        self.next_btn = ctk.CTkButton(nav, text="Next →", width=100, height=32,
                                       command=self._next)
        self.next_btn.grid(row=0, column=3, padx=12, pady=10)

    def _update_sidebar(self):
        for i, lbl in enumerate(self.step_labels):
            if i < self.step:
                lbl.configure(text_color="#3fb950", font=ctk.CTkFont(size=12))
            elif i == self.step:
                lbl.configure(text_color="white", font=ctk.CTkFont(size=12, weight="bold"))
            else:
                lbl.configure(text_color="#555", font=ctk.CTkFont(size=12))

        self.progress_lbl.configure(text=f"Step {self.step+1} of {len(self.STEPS)}")
        self.back_btn.configure(state="normal" if self.step > 0 else "disabled")
        is_last = self.step == len(self.STEPS) - 1
        self.next_btn.configure(text="Finish ✓" if is_last else "Next →")

    def _show_step(self, step: int):
        # Clear content
        for w in self.content_frame.winfo_children():
            if w != self.content_frame.grid_slaves(row=1, column=0)[0] if self.content_frame.grid_slaves(row=1, column=0) else None:
                w.destroy()

        # Rebuild content
        for widget in self.content_frame.winfo_children():
            info = widget.grid_info()
            if info.get("row") == 0:
                widget.destroy()

        panel = ctk.CTkScrollableFrame(self.content_frame, fg_color="transparent")
        panel.grid(row=0, column=0, sticky="nsew", padx=25, pady=15)

        self._render_step(step, panel)
        self._update_sidebar()

    def _render_step(self, step: int, panel):
        builders = [
            self._step_welcome,
            self._step_profile,
            self._step_education,
            self._step_experience,
            self._step_model,
            self._step_search,
            self._step_done,
        ]
        builders[step](panel)

    # ── Step 0: Welcome ───────────────────────────────────────
    def _step_welcome(self, panel):
        ctk.CTkLabel(panel, text="👋 Welcome to JobHunter",
                     font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", pady=(10, 4))
        ctk.CTkLabel(panel,
                     text="Let's set up your profile in 5 minutes.\nThis will be saved — you won't need to do this again.",
                     text_color="gray", font=ctk.CTkFont(size=13), justify="left").pack(anchor="w", pady=(0, 20))

        for icon, title, desc in [
            ("🔍", "Smart Job Scraping",    "Scrapes Indeed, LinkedIn, Glassdoor, JobRight for matching jobs"),
            ("🤖", "AI Filtering",           "AI reads each JD and scores it against your profile"),
            ("📄", "Tailored Resumes",       "Generates a custom LaTeX resume for every job"),
            ("✅", "ATS Optimization",       "Iterative ATS scoring loop until 85%+ pass rate"),
            ("☁", "Google Drive Tracking",  "Auto-uploads to Drive and logs to your job tracker sheet"),
        ]:
            row = ctk.CTkFrame(panel, corner_radius=8)
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=icon, font=ctk.CTkFont(size=20), width=40).pack(side="left", padx=10, pady=10)
            col = ctk.CTkFrame(row, fg_color="transparent")
            col.pack(side="left", pady=8)
            ctk.CTkLabel(col, text=title, font=ctk.CTkFont(weight="bold"), anchor="w").pack(anchor="w")
            ctk.CTkLabel(col, text=desc, text_color="gray", anchor="w").pack(anchor="w")

    # ── Step 1: Profile ───────────────────────────────────────
    def _step_profile(self, panel):
        ctk.CTkLabel(panel, text="Your Profile",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", pady=(5, 4))
        ctk.CTkLabel(panel, text="This info goes into your resume header and AI prompts.",
                     text_color="gray").pack(anchor="w", pady=(0, 15))

        profile = self.config.get("profile", default={})
        self._profile_fields = {}

        fields = [
            ("full_name",      "Full Name *",        "John Smith"),
            ("phone",          "Phone *",            "+1 782-000-0000"),
            ("email",          "Email *",            "john@email.com"),
            ("linkedin",       "LinkedIn",           "linkedin.com/in/johnsmith"),
            ("github",         "GitHub",             "github.com/johnsmith"),
            ("location",       "Default Location *", "Halifax, NS, Canada"),
            ("experience_yrs", "Years Experience",   "3"),
        ]
        for key, label, ph in fields:
            row = ctk.CTkFrame(panel, fg_color="transparent")
            row.pack(fill="x", pady=5)
            ctk.CTkLabel(row, text=label, width=160, anchor="w").pack(side="left")
            e = ctk.CTkEntry(row, placeholder_text=ph)
            e.insert(0, profile.get(key, ""))
            e.pack(side="left", fill="x", expand=True)
            self._profile_fields[key] = e

        ctk.CTkLabel(panel, text="Core Tech Stack *",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(12, 4))
        ctk.CTkLabel(panel, text="Technologies you know well (used in AI matching)",
                     text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w")
        self._profile_fields["core_stack"] = ctk.CTkTextbox(panel, height=60)
        self._profile_fields["core_stack"].insert("1.0",
            profile.get("core_stack", "Python, JavaScript, React, Node.js, AWS, Docker, Kubernetes, PostgreSQL"))
        self._profile_fields["core_stack"].pack(fill="x", pady=4)

        ctk.CTkLabel(panel, text="Job Target Titles",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        self._profile_fields["job_titles"] = ctk.CTkEntry(panel,
            placeholder_text="Software Developer, Full Stack Developer, Backend Developer")
        self._profile_fields["job_titles"].insert(0,
            profile.get("job_titles", "Software Developer, Full Stack Developer, Data Engineer"))
        self._profile_fields["job_titles"].pack(fill="x", pady=4)

        ctk.CTkLabel(panel, text="NOT a Good Fit For",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        self._profile_fields["not_fit_for"] = ctk.CTkEntry(panel,
            placeholder_text="Pure QA, Hardware Engineering, Sales, HR")
        self._profile_fields["not_fit_for"].insert(0,
            profile.get("not_fit_for", "Pure QA, Manual Testing, Hardware Engineering, Non-technical"))
        self._profile_fields["not_fit_for"].pack(fill="x", pady=4)

    def _save_profile_step(self):
        if not hasattr(self, "_profile_fields"):
            return
        profile = self.config.get("profile", default={})
        for key, widget in self._profile_fields.items():
            if isinstance(widget, ctk.CTkTextbox):
                profile[key] = widget.get("1.0", "end-1c").strip()
            else:
                profile[key] = widget.get().strip()
        self.config.set("profile", profile)

        # Update resume/cover letter filenames from name
        name     = profile.get("full_name", "")
        safe_name = name.replace(" ", "_")
        if safe_name:
            self.config.set("pipeline", "resume_filename",       f"{safe_name}_Resume")
            self.config.set("pipeline", "cover_letter_filename", f"{safe_name}_Cover_Letter")

    # ── Step 2: Education ─────────────────────────────────────
    def _step_education(self, panel):
        ctk.CTkLabel(panel, text="Education",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", pady=(5, 4))
        ctk.CTkLabel(panel, text="Add your degrees — shown in resume Education section.",
                     text_color="gray").pack(anchor="w", pady=(0, 12))

        self._edu_container = ctk.CTkFrame(panel, fg_color="transparent")
        self._edu_container.pack(fill="x")

        self._edu_rows = []
        profile  = self.config.get("profile", default={})
        edu_list = profile.get("education", [
            {"degree": "Your Degree", "dates": "Start Date -- End Date",
             "institution": "Your University", "location": "City, Country"},
        ])
        for edu in edu_list:
            self._add_edu_row(edu)

        ctk.CTkButton(panel, text="+ Add Education", height=32, fg_color="#333",
                      hover_color="#444",
                      command=self._add_edu_row).pack(anchor="w", pady=8)

    def _add_edu_row(self, data: dict = None):
        data = data or {}
        card = ctk.CTkFrame(self._edu_container, corner_radius=8)
        card.pack(fill="x", pady=5)

        fields = {}
        for row_data in [
            [("degree",      "Degree",      "Master of Computer Science"),
             ("dates",       "Dates",       "Sept 2023 -- Jun 2025")],
            [("institution", "Institution", "University Name"),
             ("location",    "Location",   "City, Province")],
        ]:
            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=4)
            r.grid_columnconfigure(1, weight=1)
            r.grid_columnconfigure(3, weight=1)
            for col, (key, label, ph) in enumerate(row_data):
                ctk.CTkLabel(r, text=label, width=80, anchor="w").grid(
                    row=0, column=col*2, sticky="w", padx=(0 if col==0 else 8, 4))
                e = ctk.CTkEntry(r, placeholder_text=ph)
                e.insert(0, data.get(key, ""))
                e.grid(row=0, column=col*2+1, sticky="ew")
                fields[key] = e

        def remove():
            self._edu_rows = [r for r in self._edu_rows if r is not fields]
            card.destroy()

        ctk.CTkButton(card, text="✕", width=28, height=24,
                      fg_color="#6e1a1a", hover_color="#8b2121",
                      command=remove).pack(anchor="e", padx=12, pady=(0, 8))
        self._edu_rows.append(fields)

    def _save_education_step(self):
        if not hasattr(self, "_edu_rows"):
            return
        edu_list = []
        for fields in self._edu_rows:
            edu_list.append({k: v.get().strip() for k, v in fields.items()})
        profile = self.config.get("profile", default={})
        profile["education"] = edu_list
        self.config.set("profile", profile)

    # ── Step 3: Work Experience ───────────────────────────────
    def _step_experience(self, panel):
        ctk.CTkLabel(panel, text="Work Experience",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", pady=(5, 4))
        ctk.CTkLabel(panel,
                     text="Define your roles. The pipeline uses these to generate experience bullets.\n"
                          "You can add/edit/reorder later in the Resume tab.",
                     text_color="gray", justify="left").pack(anchor="w", pady=(0, 12))

        self._exp_container = ctk.CTkFrame(panel, fg_color="transparent")
        self._exp_container.pack(fill="x")
        self._exp_rows_setup = []

        saved = self.config.get("experience_roles", default=None)
        roles = saved or [
            {"title": "Job Title",  "company": "Company Name",
             "dates": "Month Year – Month Year",  "domain": "Your Domain",
             "total_bullets": 4, "real_bullets": 2, "fabricated_bullets": 2},
        ]
        for role in roles:
            self._add_exp_row_setup(role)

        ctk.CTkButton(panel, text="+ Add Role", height=32, fg_color="#333",
                      hover_color="#444",
                      command=self._add_exp_row_setup).pack(anchor="w", pady=8)

    def _add_exp_row_setup(self, data: dict = None):
        data = data or {}
        card = ctk.CTkFrame(self._exp_container, corner_radius=8)
        card.pack(fill="x", pady=5)

        fields = {}
        for row_data in [
            [("title",   "Job Title",  "Software Developer"),
             ("company", "Company",    "Company Name")],
            [("dates",   "Dates",      "Jan 2024 – Dec 2024"),
             ("domain",  "Domain",     "full-stack, APIs, cloud")],
        ]:
            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=4)
            r.grid_columnconfigure(1, weight=1)
            r.grid_columnconfigure(3, weight=1)
            for col, (key, label, ph) in enumerate(row_data):
                ctk.CTkLabel(r, text=label, width=80, anchor="w").grid(
                    row=0, column=col*2, sticky="w", padx=(0 if col==0 else 8, 4))
                e = ctk.CTkEntry(r, placeholder_text=ph)
                e.insert(0, data.get(key, ""))
                e.grid(row=0, column=col*2+1, sticky="ew")
                fields[key] = e

        # Bullet counts
        row3 = ctk.CTkFrame(card, fg_color="transparent")
        row3.pack(fill="x", padx=12, pady=(0, 8))
        for col, (label, key, default) in enumerate([
            ("Total Bullets", "total_bullets", 4),
            ("Real Bullets",  "real_bullets",  2),
            ("Fabricated",    "fabricated_bullets", 2),
        ]):
            ctk.CTkLabel(row3, text=label, anchor="w").grid(
                row=0, column=col*2, padx=(0 if col==0 else 12, 4))
            e = ctk.CTkEntry(row3, width=45)
            e.insert(0, str(data.get(key, default)))
            e.grid(row=0, column=col*2+1)
            fields[key] = e

        def remove():
            self._exp_rows_setup = [r for r in self._exp_rows_setup if r is not fields]
            card.destroy()

        ctk.CTkButton(row3, text="✕ Remove", width=90, height=26,
                      fg_color="#6e1a1a", hover_color="#8b2121",
                      command=remove).grid(row=0, column=7, padx=(16, 0))

        self._exp_rows_setup.append(fields)

    def _save_experience_step(self):
        if not hasattr(self, "_exp_rows_setup"):
            return
        roles = []
        for fields in self._exp_rows_setup:
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

    # ── Step 4: AI Model ──────────────────────────────────────
    def _step_model(self, panel):
        ctk.CTkLabel(panel, text="AI Model Setup",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", pady=(5, 4))
        ctk.CTkLabel(panel,
                     text="Configure the AI model used for job screening and resume generation.",
                     text_color="gray").pack(anchor="w", pady=(0, 15))

        model_cfg = self.config.get("model", default={})
        self._model_fields = {}

        card = ctk.CTkFrame(panel, corner_radius=10)
        card.pack(fill="x", pady=5)

        for key, label, ph, default in [
            ("name", "Model Name", "gemma4:31b-cloud", "gemma4:31b-cloud"),
        ]:
            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=15, pady=8)
            ctk.CTkLabel(r, text=label, width=120, anchor="w").pack(side="left")
            e = ctk.CTkEntry(r, placeholder_text=ph)
            e.insert(0, model_cfg.get(key, default))
            e.pack(side="left", fill="x", expand=True)
            self._model_fields[key] = e

        ctk.CTkLabel(card, text="API Keys (one per line — for Ollama Cloud)",
                     font=ctk.CTkFont(weight="bold")).pack(padx=15, pady=(8, 4), anchor="w")
        ctk.CTkLabel(card,
                     text="Get keys from ollama.com → Profile → API Keys",
                     text_color="gray", font=ctk.CTkFont(size=11)).pack(padx=15, anchor="w")
        self._api_keys_box = ctk.CTkTextbox(card, height=90)
        keys = model_cfg.get("api_keys", [])
        self._api_keys_box.insert("1.0", "\n".join(keys))
        self._api_keys_box.pack(fill="x", padx=15, pady=(4, 12))

        ctk.CTkLabel(panel,
                     text="💡 For local Ollama, leave API keys empty and set model to e.g. 'gemma3:4b'\n"
                          "   For cloud, add API key(s) and use model ending in '-cloud'",
                     text_color="#58a6ff", font=ctk.CTkFont(size=11)).pack(anchor="w", pady=8)

    def _save_model_step(self):
        if not hasattr(self, "_model_fields"):
            return
        model_cfg = self.config.get("model", default={})
        model_cfg["name"] = self._model_fields["name"].get().strip()
        keys_raw = self._api_keys_box.get("1.0", "end").strip()
        model_cfg["api_keys"] = [k.strip() for k in keys_raw.splitlines() if k.strip()]
        self.config.set("model", model_cfg)

    # ── Step 5: Job Search ────────────────────────────────────
    def _step_search(self, panel):
        ctk.CTkLabel(panel, text="Job Search Settings",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", pady=(5, 4))
        ctk.CTkLabel(panel, text="Default settings for job scraping.",
                     text_color="gray").pack(anchor="w", pady=(0, 15))

        scraper = self.config.get("scraper", default={})
        self._search_fields = {}

        card = ctk.CTkFrame(panel, corner_radius=10)
        card.pack(fill="x", pady=5)

        for key, label, ph, default in [
            ("search_term",    "Job Title/Keywords", "Software Developer",  "Software Developer"),
            ("location",       "Location",           "Canada",              "Canada"),
            ("country_indeed", "Country Code",       "canada",              "canada"),
            ("hours_old",      "Post Age (hours)",   "72",                  "72"),
            ("results_wanted", "Jobs to Fetch",      "20",                  "20"),
        ]:
            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=15, pady=6)
            ctk.CTkLabel(r, text=label, width=150, anchor="w").pack(side="left")
            e = ctk.CTkEntry(r, placeholder_text=ph)
            e.insert(0, scraper.get(key, default))
            e.pack(side="left", fill="x", expand=True)
            self._search_fields[key] = e

        ctk.CTkLabel(card, text="Sites to Search",
                     font=ctk.CTkFont(weight="bold")).pack(padx=15, pady=(8, 4), anchor="w")

        sites_frame = ctk.CTkFrame(card, fg_color="transparent")
        sites_frame.pack(fill="x", padx=15, pady=(0, 12))
        self._site_vars = {}
        current_sites = scraper.get("sites", "indeed,glassdoor,jobright").split(",")
        for site in ["indeed", "glassdoor", "linkedin", "jobright"]:
            var = ctk.BooleanVar(value=site in current_sites)
            ctk.CTkCheckBox(sites_frame, text=site.title(), variable=var).pack(
                side="left", padx=8)
            self._site_vars[site] = var

        # Google Drive
        ctk.CTkLabel(panel, text="Google Drive & Sheets (Optional)",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", pady=(15, 4))
        google = self.config.get("google", default={})
        self._google_fields = {}

        g_card = ctk.CTkFrame(panel, corner_radius=10)
        g_card.pack(fill="x", pady=5)

        r = ctk.CTkFrame(g_card, fg_color="transparent")
        r.pack(fill="x", padx=15, pady=8)
        ctk.CTkLabel(r, text="Enable", width=150, anchor="w").pack(side="left")
        self._google_enabled = ctk.BooleanVar(value=google.get("enabled", False))
        ctk.CTkSwitch(r, variable=self._google_enabled, text="").pack(side="left")

        for key, label, ph in [
            ("spreadsheet_id", "Spreadsheet ID", "1ABC...xyz"),
            ("drive_folder",   "Drive Folder",   "Job Applications"),
            ("sheet_tab",      "Sheet Tab",       "Sheet1"),
        ]:
            r = ctk.CTkFrame(g_card, fg_color="transparent")
            r.pack(fill="x", padx=15, pady=5)
            ctk.CTkLabel(r, text=label, width=150, anchor="w").pack(side="left")
            e = ctk.CTkEntry(r, placeholder_text=ph)
            e.insert(0, google.get(key, ""))
            e.pack(side="left", fill="x", expand=True)
            self._google_fields[key] = e

        ctk.CTkFrame(g_card, height=8, fg_color="transparent").pack()

    def _save_search_step(self):
        if not hasattr(self, "_search_fields"):
            return
        scraper = self.config.get("scraper", default={})
        for key, entry in self._search_fields.items():
            scraper[key] = entry.get().strip()

        selected = [s for s, v in self._site_vars.items() if v.get()]
        scraper["sites"] = ",".join(selected) if selected else "indeed,glassdoor"
        self.config.set("scraper", scraper)

        google = self.config.get("google", default={})
        google["enabled"] = self._google_enabled.get()
        for key, entry in self._google_fields.items():
            google[key] = entry.get().strip()
        self.config.set("google", google)

    # ── Step 6: Done ──────────────────────────────────────────
    def _step_done(self, panel):
        profile = self.config.get("profile", default={})
        name    = profile.get("full_name", "there")

        ctk.CTkLabel(panel, text=f"🎉 All Set, {name.split()[0]}!",
                     font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", pady=(10, 8))
        ctk.CTkLabel(panel,
                     text="Your configuration has been saved.\nYou can update anything anytime from the app.",
                     text_color="gray", font=ctk.CTkFont(size=13), justify="left").pack(anchor="w", pady=(0, 20))

        for icon, title, desc in [
            ("📄", "Resume & Projects tab", "Paste your resume and projects text"),
            ("🔍", "Scraper tab",           "Run job scraping with AI filtering"),
            ("⚙",  "Pipeline tab",          "Generate tailored resumes for matched jobs"),
            ("✏",  "Prompts tab",           "Customize all AI prompts"),
            ("⚙",  "Settings tab",          "Change model, Google Drive, filenames"),
        ]:
            row = ctk.CTkFrame(panel, corner_radius=8)
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=icon, font=ctk.CTkFont(size=18), width=36).pack(
                side="left", padx=10, pady=8)
            ctk.CTkLabel(row, text=f"{title}  —  ", font=ctk.CTkFont(weight="bold")).pack(side="left")
            ctk.CTkLabel(row, text=desc, text_color="gray").pack(side="left")

        ctk.CTkLabel(panel,
                     text="\n💡 Tip: Delete app_config.json to reset and re-run this wizard.",
                     text_color="#58a6ff", font=ctk.CTkFont(size=11)).pack(anchor="w", pady=8)

    # ── Navigation ────────────────────────────────────────────
    def _save_current_step(self):
        savers = [
            None,
            self._save_profile_step,
            self._save_education_step,
            self._save_experience_step,
            self._save_model_step,
            self._save_search_step,
            None,
        ]
        saver = savers[self.step]
        if saver:
            saver()

    def _next(self):
        self._save_current_step()
        self.config.save()

        if self.step == len(self.STEPS) - 1:
            self._finish()
            return

        self.step += 1
        self._show_step(self.step)

    def _back(self):
        if self.step > 0:
            self.step -= 1
            self._show_step(self.step)

    def _skip(self):
        if messagebox.askyesno("Skip Setup",
                               "Skip setup? You can run it again by deleting app_config.json."):
            self.config.set("setup_complete", True)
            self.config.save()
            self.destroy()
            self.on_complete()

    def _finish(self):
        self.config.set("setup_complete", True)
        self.config.save()
        self.destroy()
        self.on_complete()


# ══════════════════════════════════════════════════════════════
#  PROFILE TAB (for ongoing editing in main app)
# ══════════════════════════════════════════════════════════════

class ProfileTab(ctk.CTkFrame):
    def __init__(self, master, config, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.config   = config
        self.edu_rows = []
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="My Profile",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                     pady=(20, 4), anchor="w", padx=30)
        ctk.CTkLabel(self,
                     text="Your profile drives AI matching, resume generation, and cover letters.",
                     text_color="gray", font=ctk.CTkFont(size=12)).pack(
                     anchor="w", padx=30, pady=(0, 12))

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=30, pady=(0, 20))

        self.tabview.add("👤 Personal Info")
        self.tabview.add("🎓 Education")
        self.tabview.add("💼 Work History")

        self._build_personal()
        self._build_education()
        self._build_work_history()

    # ── Personal info tab ─────────────────────────────────────
    def _build_personal(self):
        tab = self.tabview.tab("👤 Personal Info")
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        profile = self.config.get("profile", default={})
        self._personal_fields = {}

        ctk.CTkLabel(scroll, text="Contact Details",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))

        for key, label in [
            ("full_name",  "Full Name"),
            ("phone",      "Phone"),
            ("email",      "Email"),
            ("linkedin",   "LinkedIn URL"),
            ("github",     "GitHub URL"),
            ("location",   "City, Province"),
        ]:
            r = ctk.CTkFrame(scroll, fg_color="transparent")
            r.pack(fill="x", pady=4)
            ctk.CTkLabel(r, text=label, width=130, anchor="w").pack(side="left")
            e = ctk.CTkEntry(r)
            e.insert(0, profile.get(key, ""))
            e.pack(side="left", fill="x", expand=True)
            self._personal_fields[key] = e

        ctk.CTkLabel(scroll, text="Career Profile",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(12, 4))

        for key, label, height in [
            ("core_stack",  "Core Tech Stack",    60),
            ("job_titles",  "Target Job Titles",  None),
            ("not_fit_for", "NOT Fit For",        None),
            ("domains",     "Expertise Domains",  None),
        ]:
            ctk.CTkLabel(scroll, text=label, anchor="w").pack(anchor="w", pady=(6, 2))
            if height:
                w = ctk.CTkTextbox(scroll, height=height)
                w.insert("1.0", profile.get(key, ""))
                w.pack(fill="x", pady=(0, 4))
            else:
                w = ctk.CTkEntry(scroll)
                w.insert(0, profile.get(key, ""))
                w.pack(fill="x", pady=(0, 4))
            self._personal_fields[key] = w

        r = ctk.CTkFrame(scroll, fg_color="transparent")
        r.pack(fill="x", pady=4)
        ctk.CTkLabel(r, text="Years Experience", width=130, anchor="w").pack(side="left")
        e = ctk.CTkEntry(r, width=60)
        e.insert(0, profile.get("experience_yrs", "3"))
        e.pack(side="left")
        self._personal_fields["experience_yrs"] = e

        ctk.CTkButton(scroll, text="💾 Save Personal Info", height=36,
                      command=self._save_personal).pack(fill="x", pady=(15, 5))

    def _save_personal(self):
        profile = self.config.get("profile", default={})
        for key, widget in self._personal_fields.items():
            if isinstance(widget, ctk.CTkTextbox):
                profile[key] = widget.get("1.0", "end-1c").strip()
            else:
                profile[key] = widget.get().strip()
        self.config.set("profile", profile)

        # Update filenames
        name = profile.get("full_name", "")
        safe = name.replace(" ", "_")
        if safe:
            self.config.set("pipeline", "resume_filename",       f"{safe}_Resume")
            self.config.set("pipeline", "cover_letter_filename", f"{safe}_Cover_Letter")

        self.config.save()
        from tkinter import messagebox
        messagebox.showinfo("Saved", "Profile saved successfully.")

    # ── Education tab ─────────────────────────────────────────
    def _build_education(self):
        tab = self.tabview.tab("🎓 Education")

        header = ctk.CTkFrame(tab, fg_color="transparent")
        header.pack(fill="x", pady=(8, 4))
        ctk.CTkLabel(header, text="Your education history (shown in resume)",
                     text_color="gray").pack(side="left")
        ctk.CTkButton(header, text="+ Add", width=80, height=28,
                      command=self._add_edu).pack(side="right")

        self._edu_scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self._edu_scroll.pack(fill="both", expand=True)

        self._edu_rows = []
        profile = self.config.get("profile", default={})
        for edu in profile.get("education", []):
            self._add_edu(edu)

        ctk.CTkButton(tab, text="💾 Save Education", height=36,
                      command=self._save_education).pack(fill="x", pady=8)

    def _add_edu(self, data: dict = None):
        data = data or {}
        card = ctk.CTkFrame(self._edu_scroll, corner_radius=8)
        card.pack(fill="x", pady=5)
        fields = {}
        for row_items in [
            [("degree", "Degree"), ("dates", "Dates")],
            [("institution", "Institution"), ("location", "Location")],
        ]:
            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=4)
            r.grid_columnconfigure(1, weight=1)
            r.grid_columnconfigure(3, weight=1)
            for col, (key, label) in enumerate(row_items):
                ctk.CTkLabel(r, text=label, width=90, anchor="w").grid(
                    row=0, column=col*2, sticky="w", padx=(0 if col==0 else 8, 4))
                e = ctk.CTkEntry(r)
                e.insert(0, data.get(key, ""))
                e.grid(row=0, column=col*2+1, sticky="ew")
                fields[key] = e

        def rm():
            self._edu_rows = [x for x in self._edu_rows if x is not fields]
            card.destroy()

        ctk.CTkButton(card, text="Remove", width=80, height=24,
                      fg_color="#6e1a1a", hover_color="#8b2121",
                      command=rm).pack(anchor="e", padx=12, pady=(0, 6))
        self._edu_rows.append(fields)

    def _save_education(self):
        edu_list = [{k: v.get().strip() for k, v in f.items()} for f in self._edu_rows]
        profile = self.config.get("profile", default={})
        profile["education"] = edu_list
        self.config.set("profile", profile)
        self.config.save()
        from tkinter import messagebox
        messagebox.showinfo("Saved", f"Saved {len(edu_list)} education entries.")

    # ── Work History tab ──────────────────────────────────────
    def _build_work_history(self):
        tab = self.tabview.tab("💼 Work History")
        ctk.CTkLabel(tab,
                     text="These roles are used to generate experience bullets in your resume.",
                     text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w", pady=(8, 4))

        self._work_scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self._work_scroll.pack(fill="both", expand=True)

        self._work_rows = []
        for role in self.config.get("experience_roles", default=[]):
            self._add_work_row(role)

        btn_row = ctk.CTkFrame(tab, fg_color="transparent")
        btn_row.pack(fill="x", pady=6)
        ctk.CTkButton(btn_row, text="+ Add Role", height=32, fg_color="#333",
                      hover_color="#444",
                      command=self._add_work_row).pack(side="left")
        ctk.CTkButton(btn_row, text="💾 Save All Roles", height=32,
                      command=self._save_work).pack(side="right")

    def _add_work_row(self, data: dict = None):
        data = data or {}
        card = ctk.CTkFrame(self._work_scroll, corner_radius=8)
        card.pack(fill="x", pady=5)

        fields = {}
        ctk.CTkLabel(card, text=f"Role {len(self._work_rows)+1}",
                     font=ctk.CTkFont(weight="bold"),
                     text_color="#58a6ff").pack(anchor="w", padx=12, pady=(8, 2))

        for row_items in [
            [("title", "Job Title"), ("company", "Company")],
            [("dates", "Dates"),     ("domain", "Domain")],
        ]:
            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=3)
            r.grid_columnconfigure(1, weight=1)
            r.grid_columnconfigure(3, weight=1)
            for col, (key, label) in enumerate(row_items):
                ctk.CTkLabel(r, text=label, width=80, anchor="w").grid(
                    row=0, column=col*2, sticky="w", padx=(0 if col==0 else 8, 4))
                e = ctk.CTkEntry(r)
                e.insert(0, data.get(key, ""))
                e.grid(row=0, column=col*2+1, sticky="ew")
                fields[key] = e

        row3 = ctk.CTkFrame(card, fg_color="transparent")
        row3.pack(fill="x", padx=12, pady=(2, 8))
        for col, (label, key, default) in enumerate([
            ("Total", "total_bullets", 4),
            ("Real",  "real_bullets",  2),
            ("Fabricated", "fabricated_bullets", 2),
        ]):
            ctk.CTkLabel(row3, text=label+" Bullets", anchor="w").grid(
                row=0, column=col*2, padx=(0 if col==0 else 12, 4))
            e = ctk.CTkEntry(row3, width=45)
            e.insert(0, str(data.get(key, default)))
            e.grid(row=0, column=col*2+1)
            fields[key] = e

        def rm():
            self._work_rows = [x for x in self._work_rows if x is not fields]
            card.destroy()

        ctk.CTkButton(row3, text="✕ Remove", width=90, height=26,
                      fg_color="#6e1a1a", hover_color="#8b2121",
                      command=rm).grid(row=0, column=7, padx=(20, 0))
        self._work_rows.append(fields)

    def _save_work(self):
        roles = []
        for fields in self._work_rows:
            try:
                roles.append({
                    "title":              fields["title"].get().strip(),
                    "company":            fields["company"].get().strip(),
                    "dates":              fields["dates"].get().strip(),
                    "domain":             fields["domain"].get().strip(),
                    "total_bullets":      int(fields["total_bullets"].get() or 4),
                    "real_bullets":       int(fields["real_bullets"].get() or 2),
                    "fabricated_bullets": int(fields["fabricated_bullets"].get() or 2),
                })
            except Exception:
                pass
        self.config.set("experience_roles", roles)
        self.config.save()
        from tkinter import messagebox
        messagebox.showinfo("Saved", f"Saved {len(roles)} work experience roles.")


# ══════════════════════════════════════════════════════════════
#  FIRST-RUN CHECK
# ══════════════════════════════════════════════════════════════

def check_and_run_setup(app_window, config, on_complete=None):
    """
    Call this in JobHunterApp.__init__ BEFORE _build_ui().
    Shows wizard if first run, otherwise loads profile silently.
    """
    if config.get("setup_complete", default=False):
        # Already configured — just inject profile into resume builder
        _inject_profile(config)
        if on_complete:
            on_complete()
        return

    def _on_wizard_done():
        _inject_profile(config)
        if on_complete:
            on_complete()
        # Refresh dashboard if it exists
        try:
            app_window._build_ui()
        except Exception:
            pass

    # Show wizard after a short delay (let window render first)
    app_window.after(300, lambda: SetupWizard(app_window, config, _on_wizard_done))


def _inject_profile(config):
    """Inject profile into resume_builder constants."""
    try:
        import agents.resume_builder as rb
        profile = config.get("profile", default={})
        if not profile:
            return

        rb.FIXED_HEADER    = build_fixed_header(profile)
        rb.FIXED_EDUCATION = build_fixed_education(profile)

        # Update prompts with profile context
        profile_ctx = build_profile_prompt_context(profile)

        for prompt_key in ("job_screener", "experience_section", "skills_section",
                           "projects_section", "cover_letter"):
            current = config.get("prompts", prompt_key, default="")
            if current and "{candidate_profile}" in current:
                config.set("prompts", prompt_key,
                           current.replace("{candidate_profile}", profile_ctx))

    except Exception as e:
        print(f"Profile injection skipped: {e}")