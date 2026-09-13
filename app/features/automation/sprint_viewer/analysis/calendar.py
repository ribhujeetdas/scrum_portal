from datetime import date, timedelta
from .timezones import board_timezone
from .boundaries import instant


def late_addition_cutoff(close, config):
    """Last configured working dates before actual close, interpreted in board time."""
    if not config.get('calendar_version') or config['calendar_version'] == 'unconfigured':
        return None
    try:
        timezone = board_timezone(config.get('timezone', 'Asia/Kolkata'))
        end = instant(close)
        if end is None:
            return None
        holidays = {date.fromisoformat(d) for d in config.get('holidays', [])}
        weekdays = set(config.get('working_weekdays', [0, 1, 2, 3, 4]))
        if not weekdays or not weekdays <= set(range(7)):
            return None
        day, count = end.astimezone(timezone).date(), 0
        for _ in range(366):
            if day.weekday() in weekdays and day not in holidays:
                count += 1
                if count == 2:
                    return day, timezone
            day -= timedelta(days=1)
    except (ValueError, KeyError):
        return None
    return None
