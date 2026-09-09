from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
import uuid

from app import create_app
from app.features.automation.sprint_viewer.jobs import (
    acquire_leadership,
    claim_job,
    heartbeat_leader,
    heartbeat_job,
    run_job,
)


log = logging.getLogger("app.sprint_worker")


def run_worker(*, once: bool = False) -> int:
    app = create_app()
    owner = str(uuid.uuid4())
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
    with app.app_context():
        epoch = acquire_leadership(owner, lease_seconds=int(app.config["SPRINT_JOB_LEASE_SECONDS"]))

    def run_with_heartbeat(job) -> None:
        completed = threading.Event()

        def renew() -> None:
            interval = int(app.config["SPRINT_JOB_HEARTBEAT_SECONDS"])
            lease = int(app.config["SPRINT_JOB_LEASE_SECONDS"])
            while not completed.wait(interval):
                with app.app_context():
                    if not heartbeat_leader(owner, epoch, lease_seconds=lease):
                        return
                    if not heartbeat_job(job.id, owner, job.fence, epoch, lease_seconds=lease):
                        return

        heartbeat = threading.Thread(target=renew, name=f"job-heartbeat-{job.id[:8]}", daemon=True)
        heartbeat.start()
        try:
            run_job(job, owner, epoch)
        finally:
            completed.set()
            heartbeat.join(timeout=2)
    if once:
        with app.app_context():
            heartbeat_leader(owner, epoch, lease_seconds=int(app.config["SPRINT_JOB_LEASE_SECONDS"]))
            job = claim_job(owner, epoch, "core") or claim_job(owner, epoch, "enrichment")
            if job:
                run_with_heartbeat(job)
        return 0

    def consume(lane: str) -> None:
        while not stop.is_set():
            job = None
            try:
                with app.app_context():
                    job = claim_job(owner, epoch, lane)
                    if job:
                        run_with_heartbeat(job)
            except Exception:
                log.exception("Worker lane iteration failed", extra={"lane": lane})
            if not job:
                stop.wait(float(app.config.get("SPRINT_JOB_POLL_SECONDS", 1)))

    consumers = [
        threading.Thread(target=consume, args=("core",), name="sprint-core", daemon=True),
        threading.Thread(target=consume, args=("enrichment",), name="sprint-enrichment-1", daemon=True),
        threading.Thread(target=consume, args=("enrichment",), name="sprint-enrichment-2", daemon=True),
    ]
    for consumer in consumers:
        consumer.start()
    last_heartbeat = 0.0
    while not stop.is_set():
        now = time.monotonic()
        with app.app_context():
            if now - last_heartbeat >= int(app.config["SPRINT_JOB_HEARTBEAT_SECONDS"]):
                if not heartbeat_leader(owner, epoch, lease_seconds=int(app.config["SPRINT_JOB_LEASE_SECONDS"])):
                    stop.set()
                    return 2
                last_heartbeat = now
        stop.wait(0.5)
    for consumer in consumers:
        consumer.join(timeout=5)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the SQLite-backed Sprint Viewer import worker")
    parser.add_argument("--once", action="store_true", help="Process at most one available job")
    args = parser.parse_args()
    return run_worker(once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
