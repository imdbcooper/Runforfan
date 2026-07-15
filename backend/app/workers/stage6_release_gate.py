import json

from app.core.settings import get_settings
from app.services.stage6_release import software_release_gate


def main() -> None:
    report = software_release_gate(get_settings())
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
