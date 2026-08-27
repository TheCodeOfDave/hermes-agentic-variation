from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PIPE_LIMIT = 64 * 1024
TIMEOUT_SECONDS = 10


class ProtocolFailure(RuntimeError):
    pass


def _strict_line(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolFailure("malformed worker JSON") from exc
    if not isinstance(value, dict) or set(value) != {"id", "value"}:
        raise ProtocolFailure("worker response schema mismatch")
    return value


def validate_worker_transcript(
    lines: list[str],
    cases: list[dict[str, Any]],
    worker_stdout: bytes,
    worker_stderr: bytes,
    exit_code: int,
    overflow: bool = False,
) -> int:
    if overflow:
        raise ProtocolFailure("worker output overflow")
    if worker_stdout:
        raise ProtocolFailure("worker wrote unexpected stdout")
    if worker_stderr:
        raise ProtocolFailure("worker wrote stderr")
    if exit_code != 0:
        raise ProtocolFailure("worker exited nonzero or by signal")
    if len(lines) != len(cases):
        raise ProtocolFailure("missing, partial, duplicate, or extra worker response")
    seen: set[str] = set()
    for raw, case in zip(lines, cases, strict=True):
        response = _strict_line(raw)
        case_id = case.get("id")
        if (
            response["id"] != case_id
            or case_id in seen
            or response["value"] != case.get("expected")
        ):
            raise ProtocolFailure("worker response identity, order, or value mismatch")
        seen.add(case_id)
    return len(lines)


def _drain(proc: subprocess.Popen[bytes], response_fd: int) -> tuple[bytes, bytes, bytes, bool]:
    selector = selectors.DefaultSelector()
    streams = {
        response_fd: bytearray(),
        proc.stdout.fileno(): bytearray(),
        proc.stderr.fileno(): bytearray(),
    }
    for fd in streams:
        os.set_blocking(fd, False)
        selector.register(fd, selectors.EVENT_READ)
    deadline = time.monotonic() + TIMEOUT_SECONDS
    overflow = False
    while selector.get_map():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            proc.kill()
            raise ProtocolFailure("worker timeout")
        events = selector.select(min(remaining, 0.1))
        if not events and proc.poll() is not None:
            events = [(key, selectors.EVENT_READ) for key in list(selector.get_map().values())]
        for key, _ in events:
            try:
                chunk = os.read(key.fd, 8192)
            except BlockingIOError:
                continue
            if not chunk:
                selector.unregister(key.fd)
                continue
            streams[key.fd].extend(chunk)
            if len(streams[key.fd]) > PIPE_LIMIT:
                overflow = True
                proc.kill()
        if overflow:
            break
    if overflow:
        proc.wait(timeout=2)
    return (
        bytes(streams[response_fd]),
        bytes(streams[proc.stdout.fileno()]),
        bytes(streams[proc.stderr.fileno()]),
        overflow,
    )


def main() -> int:
    cases = json.loads(Path("/evaluator/phase5_cases.json").read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ProtocolFailure("case corpus invalid")
    request_r, request_w = os.pipe()
    response_r, response_w = os.pipe()
    env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": "/candidate",
        "PHASE5_REQUEST_FD": str(request_r),
        "PHASE5_RESPONSE_FD": str(response_w),
    }
    proc = subprocess.Popen(
        [sys.executable, "/evaluator/phase5_worker.py"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        close_fds=True,
        pass_fds=(request_r, response_w),
    )
    os.close(request_r)
    os.close(response_w)
    try:
        requests = b"".join(
            json.dumps(
                {"id": c["id"], "values": c["values"]}, sort_keys=True, separators=(",", ":")
            ).encode()
            + b"\n"
            for c in cases
        )
        os.write(request_w, requests)
    finally:
        os.close(request_w)
    response, worker_stdout, worker_stderr, overflow = _drain(proc, response_r)
    os.close(response_r)
    exit_code = proc.wait(timeout=2)
    if response and not response.endswith(b"\n"):
        raise ProtocolFailure("partial worker response")
    try:
        lines = [line.decode("utf-8") for line in response.splitlines()]
    except UnicodeDecodeError as exc:
        raise ProtocolFailure("non-UTF-8 worker response") from exc
    count = validate_worker_transcript(
        lines, cases, worker_stdout, worker_stderr, exit_code, overflow
    )
    sys.stdout.buffer.write(f"PHASE5_EVALUATOR_PASS cases={count}\n".encode("ascii"))
    return 0


if __name__ == "__main__":
    try:
        status = main()
    except BaseException:
        status = 1
    raise SystemExit(status)
