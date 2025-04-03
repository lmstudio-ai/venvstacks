import os
from pathlib import Path

# Allow DLL import on Windows
if hasattr(os, "add_dll_directory"):
    assert os.name == "nt"
    os.add_dll_directory(Path(__file__).parent)
