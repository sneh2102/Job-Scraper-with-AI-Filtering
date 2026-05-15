# runtime_hook.py
# PyInstaller runtime hook — fixes working directory and paths
# Placed in the same folder as the spec file

import os
import sys

def fix_working_directory():
    """
    When running as a PyInstaller exe, set the working directory
    to the folder containing the exe (not a temp folder).
    This ensures app_config.json, jobs.xlsx, outputs/ etc.
    are created next to the exe, not in a temp location.
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled exe
        exe_dir = os.path.dirname(sys.executable)
        os.chdir(exe_dir)
        # Also add exe dir to path so local imports work
        if exe_dir not in sys.path:
            sys.path.insert(0, exe_dir)

fix_working_directory()
