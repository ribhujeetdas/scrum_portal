from datetime import timedelta, timezone
from zoneinfo import ZoneInfo


def board_timezone(name='Asia/Kolkata'):
    # Deployment defaults have fixed offsets for modern Jira history. Other zones
    # require the OS IANA database (or deployment-installed tzdata) for DST rules.
    if name == 'UTC':
        return timezone.utc
    if name in {'Asia/Kolkata', 'Asia/Calcutta'}:
        return timezone(timedelta(hours=5, minutes=30), 'Asia/Kolkata')
    return ZoneInfo(name)
