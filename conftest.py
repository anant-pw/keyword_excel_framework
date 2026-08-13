"""
Ensures the project root is on sys.path for `from core... import ...` /
`from keywords... import ...` regardless of where pytest is invoked from.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
