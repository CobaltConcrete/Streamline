import sys
from pathlib import Path

# Allow `import codirector...` without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
