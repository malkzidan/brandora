import json
from pathlib import Path
import jsonschema
SCHEMA=json.loads((Path(__file__).parent / "e03_schema.json").read_text(encoding="utf-8"))
VALIDATOR=jsonschema.Draft202012Validator(SCHEMA,format_checker=jsonschema.FormatChecker())
