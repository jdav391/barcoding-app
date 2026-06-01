import os
from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["basename"] = lambda p: os.path.basename(p) if p else ""
