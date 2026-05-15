# jobhunter.spec
# PyInstaller spec file for JobHunter Windows executable
# Build with: pyinstaller jobhunter.spec

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ── Collect customtkinter assets (themes, images) ────────────
import customtkinter
ctk_path = os.path.dirname(customtkinter.__file__)

# ── All data files to bundle ──────────────────────────────────
datas = [
    # CustomTkinter themes and assets
    (ctk_path, "customtkinter"),
    # Your source modules
    ("agents",         "agents"),
    ("utils",          "utils"),
    ("jobspy",         "jobspy"),
    ("setup_wizard.py","." ),
    ("google_integration.py", "."),
    ("jobs_scraper.py", "."),
    ("ai.py",          "."),
    ("pipeline.py",    "."),
    ("main_scraper.py","." ),
]

# ── Hidden imports that PyInstaller misses ────────────────────
hidden_imports = [
    # CustomTkinter
    "customtkinter",
    "PIL", "PIL.Image", "PIL.ImageTk",
    # Google APIs
    "google.oauth2.credentials",
    "google.auth.transport.requests",
    "google_auth_oauthlib.flow",
    "googleapiclient.discovery",
    "googleapiclient.http",
    # Ollama
    "ollama",
    "httpx",
    # Data
    "pandas",
    "openpyxl",
    "openpyxl.styles",
    "openpyxl.utils",
    "tqdm",
    # ReportLab (cover letter PDF)
    "reportlab",
    "reportlab.lib.pagesizes",
    "reportlab.lib.styles",
    "reportlab.platypus",
    # JobSpy internals
    "jobspy",
    "jobspy.indeed",
    "jobspy.glassdoor",
    "jobspy.linkedin",
    "jobspy.jobright",
    "bs4",
    "requests",
    "playwright.sync_api",
    # Other
    "regex",
    "markdownify",
    "dotenv",
    "certifi",
    "charset_normalizer",
    "aiohttp",
]

a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["runtime_hook.py"],
    excludes=[
        # Exclude heavy unused packages
        "matplotlib", "scipy", "numpy", "tensorflow",
        "torch", "cv2", "sklearn",
        "IPython", "jupyter", "notebook",
        "pytest", "unittest",
        "tkinter.test",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JobHunter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # No console window — GUI only
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,        # Optional: add your icon file
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="JobHunter",
)


# ── Update spec to include runtime hook ──────────────────────
# (Already included above — this comment is informational)
# The runtime hook fixes the working directory when running as exe
