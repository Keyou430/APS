import json
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402


def rendered_openapi() -> str:
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export or verify the committed OpenAPI snapshot")
    parser.add_argument("--output", type=Path, default=Path("docs/openapi.json"))
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the generated document with --output without modifying the file",
    )
    args = parser.parse_args(argv)
    destination: Path = args.output
    rendered = rendered_openapi()

    if args.check:
        if not destination.exists() or destination.read_text(encoding="utf-8") != rendered:
            print(f"OpenAPI snapshot is out of date: {destination}", file=sys.stderr)
            return 1
        print(f"OpenAPI snapshot is current: {destination}")
        return 0

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    print(f"Exported {len(app.openapi()['paths'])} paths to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
