"""Hourly rolling-horizon generator for task instances."""

from datetime import datetime, timedelta, timezone
import logging
import time

from .scheduler import generate_future


LOG = logging.getLogger(__name__)


def seconds_until_next_hour(now: datetime) -> float:
    now = now.astimezone(timezone.utc)
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return (next_hour - now).total_seconds()


def run_forever() -> None:
    while True:
        try:
            generate_future()
            LOG.info("Queue generation completed")
        except Exception:
            LOG.exception("Queue generation failed; retrying in one minute")
            time.sleep(60)
            continue
        time.sleep(seconds_until_next_hour(datetime.now(timezone.utc)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_forever()
