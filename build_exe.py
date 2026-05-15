"""
build_exe.py
============
Run this to build the JobHunter Windows executable.

Usage:
    python build_exe.py

Output:
    dist/JobHunter/JobHunter.exe   ← the executable
    dist/JobHunter/               ← the full distributable folder

Prerequisites:
    pip install pyinstaller
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path


def check_prerequisites():
    """Check all required packages are installed."""
    print("Checking prerequisites...")

    required = [
        "customtkinter", "PIL", "pandas", "openpyxl",
        "ollama", "httpx", "reportlab", "bs4", "requests",
        "tqdm", "regex",
    ]
    missing = []
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"❌ Missing packages: {', '.join(missing)}")
        print(f"   Run: pip install {' '.join(missing)}")
        return False

    try:
        import PyInstaller
        print(f"✅ PyInstaller {PyInstaller.__version__} found")
    except ImportError:
        print("❌ PyInstaller not found. Run: pip install pyinstaller")
        return False

    print("✅ All prerequisites met")
    return True


def create_icon():
    """Create a simple icon if none exists."""
    if os.path.exists("icon.ico"):
        print("✅ icon.ico found")
        return

    print("⚠  icon.ico not found — building without custom icon")
    # Remove icon line from spec if no icon
    if os.path.exists("jobhunter.spec"):
        with open("jobhunter.spec", "r") as f:
            content = f.read()
        content = content.replace('icon="icon.ico",', "icon=None,")
        with open("jobhunter.spec", "w") as f:
            f.write(content)


def clean_build():
    """Remove previous build artifacts."""
    print("Cleaning previous build...")
    for folder in ["build", "dist/__pycache__"]:
        if os.path.exists(folder):
            shutil.rmtree(folder)
            print(f"  Removed {folder}/")


def build():
    """Run PyInstaller."""
    print("\nBuilding JobHunter executable...")
    print("This may take 3-5 minutes on first run.\n")

    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "jobhunter.spec", "--noconfirm"],
        capture_output=False,
    )

    if result.returncode != 0:
        print("\n❌ Build failed. Check errors above.")
        return False

    print("\n✅ Build succeeded!")
    return True


def post_build():
    """Copy required external files to dist folder."""
    dist_dir = Path("dist/JobHunter")

    if not dist_dir.exists():
        print("❌ dist/JobHunter not found — build may have failed")
        return

    print("\nCopying external files to dist/JobHunter/...")

    # Files that must exist alongside the exe (not bundled — user-specific)
    # We create placeholder/template versions
    external_files = {
        ".env.example":       "# Copy this to .env and fill in your values\n"
                              "OLLAMA_API_KEY_1=your_key_here\n"
                              "model=gemma4:31b-cloud\n",
        "README_SETUP.txt":   _readme_content(),
    }

    for filename, content in external_files.items():
        dest = dist_dir / filename
        if not dest.exists():
            dest.write_text(content, encoding="utf-8")
            print(f"  Created {filename}")

    # Copy credentials template
    creds_template = dist_dir / "credentials_TEMPLATE.json"
    if not creds_template.exists():
        creds_template.write_text(
            '{\n'
            '  "installed": {\n'
            '    "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",\n'
            '    "client_secret": "YOUR_CLIENT_SECRET",\n'
            '    "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],\n'
            '    "auth_uri": "https://accounts.google.com/o/oauth2/auth",\n'
            '    "token_uri": "https://oauth2.googleapis.com/token"\n'
            '  }\n'
            '}\n',
            encoding="utf-8"
        )
        print("  Created credentials_TEMPLATE.json")

    print(f"\n✅ Distribution folder ready: dist/JobHunter/")
    print(f"   Executable: dist/JobHunter/JobHunter.exe")
    print(f"   Size: {_folder_size(dist_dir):.0f} MB")


def _folder_size(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / (1024 * 1024)


def _readme_content() -> str:
    return """
╔══════════════════════════════════════════════════════════════╗
║                    JobHunter Setup Guide                     ║
╚══════════════════════════════════════════════════════════════╝

REQUIRED BEFORE FIRST RUN:
───────────────────────────────────────────────────────────────

1. INSTALL MiKTeX (for PDF resume generation)
   → https://miktex.org/download
   → Choose: Complete MiKTeX Network Installer
   → During install: set "Install missing packages on the fly" = YES
   → After install: open MiKTeX Console → Tasks → Update packages

2. INSTALL Playwright (for LinkedIn/Glassdoor scraping)
   Open a terminal in this folder and run:
   > pip install playwright
   > playwright install chromium

3. GET OLLAMA API KEY (for AI features)
   → Go to https://ollama.com → Sign up → Profile → API Keys
   → Copy your key
   → You'll enter it in the app Settings tab

4. (OPTIONAL) GOOGLE DRIVE INTEGRATION
   → Go to https://console.cloud.google.com
   → Create project → Enable Google Drive API + Google Sheets API
   → Create OAuth 2.0 credentials (Desktop app type)
   → Download JSON → rename to credentials.json
   → Place credentials.json in this folder

FIRST RUN:
───────────────────────────────────────────────────────────────
   Double-click JobHunter.exe
   → Setup wizard will guide you through configuration
   → Everything saves automatically

FOLDER STRUCTURE:
───────────────────────────────────────────────────────────────
   JobHunter.exe        ← Main application
   app_config.json      ← Your settings (auto-created on first run)
   jobs.xlsx            ← Scraped jobs (auto-created)
   outputs/             ← Generated resumes and cover letters
   resume.txt           ← Your resume text (paste via app)
   Projects.txt         ← Your projects (paste via app)
   credentials.json     ← Google OAuth (optional)

TROUBLESHOOTING:
───────────────────────────────────────────────────────────────
   • PDF not generating → Check MiKTeX is installed and updated
   • Scraping fails    → Run: playwright install chromium
   • AI errors        → Check API key in Settings tab
   • Reset app        → Delete app_config.json and reopen

SUPPORT:
   Delete app_config.json to re-run the setup wizard.

"""


def create_zip():
    """Create a distributable zip of the dist folder."""
    print("\nCreating distributable zip...")
    output = shutil.make_archive("JobHunter_Windows", "zip", "dist", "JobHunter")
    size = os.path.getsize(output) / (1024 * 1024)
    print(f"✅ Created JobHunter_Windows.zip ({size:.0f} MB)")
    print(f"   Share this zip — users just extract and run JobHunter.exe")


if __name__ == "__main__":
    print("=" * 60)
    print("  JobHunter — Windows Executable Builder")
    print("=" * 60)

    if not check_prerequisites():
        sys.exit(1)

    create_icon()
    clean_build()

    if build():
        post_build()

        answer = input("\nCreate distributable zip? (y/n): ").strip().lower()
        if answer == "y":
            create_zip()

        print("\n" + "=" * 60)
        print("  Build complete!")
        print("  Run:  dist\\JobHunter\\JobHunter.exe")
        print("=" * 60)