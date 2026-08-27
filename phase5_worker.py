from __future__ import annotations

import json
import os


def main() -> int:
    request = os.fdopen(int(os.environ["PHASE5_REQUEST_FD"]), "r", encoding="utf-8", closefd=True)
    response = os.fdopen(int(os.environ["PHASE5_RESPONSE_FD"]), "w", encoding="utf-8", closefd=True)
    import calculator
    import filters
    import formatting

    with request, response:
        for raw in request:
            item = json.loads(raw)
            if not isinstance(item, dict) or set(item) != {"id", "values"}:
                raise ValueError("request schema mismatch")
            value = formatting.format_result(calculator.total(filters.select(item["values"])))
            response.write(
                json.dumps(
                    {"id": item["id"], "value": value}, sort_keys=True, separators=(",", ":")
                )
                + "\n"
            )
            response.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
