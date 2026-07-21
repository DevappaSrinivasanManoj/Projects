#!/usr/bin/env python3
"""
Launcher for the API Tool GUI.
Adds the src/ folder to the Python path and starts the application.
"""

import sys
from pathlib import Path

# Add the src folder so all internal imports resolve correctly
src_dir = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(src_dir))

from gui_app import ApiGuiApp

if __name__ == "__main__":
    app = ApiGuiApp()
    app.mainloop()
