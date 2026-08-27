import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.sandbox_attestation import (  # noqa: E402
    SandboxAdmissionError,
    validate_sandbox_attestation,
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        attestation = validate_sandbox_attestation(payload)
    except (json.JSONDecodeError, SandboxAdmissionError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "backend": attestation.backend,
                "running_as_uid": attestation.running_as_uid,
                "sandbox-admission": "passed",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
