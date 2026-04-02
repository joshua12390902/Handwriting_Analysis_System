from pathlib import Path
from flask import Flask

_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if _DIST_DIR.is_dir():
    app = Flask(__name__, static_folder=str(_DIST_DIR), static_url_path="")
else:
    app = Flask(__name__)
