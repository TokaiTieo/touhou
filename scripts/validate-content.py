import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.content_validation_service import validate_world_content


result = validate_world_content(PROJECT_ROOT / "worlds" / "world_touhou")
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result["valid"] else 1)
