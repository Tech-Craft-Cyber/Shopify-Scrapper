from datetime import datetime, timezone

import pytest

from app.scheduler import next_runs, validate

BASE = dict(enabled=1, mode="daily", interval_hours=6, time="06:00", timezone="America/New_York",
            days="mon,tue,wed,thu,fri", cron="0 6 * * *", service="store_building", location="US", concurrency=8)
# Wednesday 2026-11-25 12:00 UTC = 07:00 New York
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)


def test_daily_weekdays_in_local_time():
    runs = next_runs(validate(BASE), NOW, 3)
    # Thu 06:00 ET = 11:00 UTC, Fri, then skips the weekend to Monday.
    assert [r.isoformat() for r in runs] == ["2026-11-26T11:00:00+00:00", "2026-11-27T11:00:00+00:00",
                                            "2026-11-30T11:00:00+00:00"]


def test_interval_anchored_to_start_time():
    runs = next_runs(validate(dict(BASE, mode="interval", interval_hours=6)), NOW, 3)
    assert [r.isoformat() for r in runs] == [
        "2026-11-25T17:00:00+00:00", "2026-11-25T23:00:00+00:00", "2026-11-26T05:00:00+00:00"]  # 12:00, 18:00, 00:00 ET


def test_cron_uses_time_zone():
    runs = next_runs(validate(dict(BASE, mode="cron", cron="30 9 * * 1")), NOW, 1)
    assert runs[0].isoformat() == "2026-11-30T14:30:00+00:00"  # Monday 09:30 ET


@pytest.mark.parametrize("bad, msg", [
    (dict(mode="weekly"), "Repeat"), (dict(time="6am"), "Time"), (dict(timezone="Mars/Base"), "time zone"),
    (dict(days=""), "day"), (dict(mode="cron", cron="every day"), "cron"), (dict(concurrency=99), "Concurrency"),
])
def test_validation_messages(bad, msg):
    with pytest.raises(ValueError, match=msg):
        validate(dict(BASE, **bad))
