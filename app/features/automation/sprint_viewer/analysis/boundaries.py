from copy import deepcopy
from datetime import datetime, timezone


def instant(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (TypeError, AttributeError, ValueError):
        return None


def project_issue(issue, sprint_id, start, end, config):
    """Rewind a complete collected state; no current values in historical columns."""
    row = {k: deepcopy(issue.get(k)) for k in ('issue_id', 'issue_key', 'summary', 'issue_type', 'is_subtask')}
    row.update(coverage='unavailable', reason_codes=[], baseline_points=None, closing_points=None,
               origin=None, outcome=None, eligible=False, events=deepcopy(issue.get('events', [])),
               cycle_days=None, closing_age_days=None, reopened=False, membership_event_count=0)
    t0, t1 = instant(start), instant(end)
    events = issue.get('events', [])
    if not issue.get('history_complete') or t0 is None or t1 is None or t1 < t0 or any(instant(e.get('at')) is None for e in events):
        row['reason_codes'] = ['history_or_boundary_unavailable']
        return row
    events = sorted(events, key=lambda e: (instant(e['at']), e.get('sequence', 0)))
    # Multiple changes to one field at one instant need a verified source ordering.
    seen = set()
    for e in events:
        key = (e['at'], e['field'])
        if key in seen and 'sequence' not in e:
            row['reason_codes'] = ['ambiguous_event_order']
            return row
        seen.add(key)
    fields = ('membership', 'status', 'points', 'assignee', 'feature', 'application')
    current = {k: deepcopy(issue.get(k)) for k in fields}
    created = instant(issue.get('created'))

    def at(cutoff):
        state = deepcopy(current)
        for e in reversed(events):
            if instant(e['at']) > cutoff and e['field'] in state:
                state[e['field']] = deepcopy(e['old'])
        if created and cutoff < created:
            state['membership'] = []
        return state

    baseline, closing = at(t0), at(t1)
    created = instant(issue.get('created'))
    if created and created > t0:
        baseline['membership'] = []
    if not isinstance(baseline['membership'], list) or not isinstance(closing['membership'], list):
        row['reason_codes'] = ['membership_unavailable']
        return row
    member = lambda v: sprint_id in v if isinstance(v, list) else False
    moves = [e for e in events if e['field'] == 'membership' and t0 < instant(e['at']) <= t1 and member(e['old']) != member(e['new'])]
    if created and t0 < created <= t1 and member(at(created)['membership']) and not any(instant(e['at']) <= created and member(e['new']) for e in moves):
        moves.insert(0, {'at': created.isoformat(), 'field': 'membership', 'old': [], 'new': at(created)['membership'], 'source': 'creation_state'})
    original = member(baseline['membership'])
    entries = [e for e in moves if member(e['new'])]
    if not original and not entries:
        row['coverage'] = 'ready'
        row['reason_codes'] = ['outside_sprint_window']
        return row
    retained = member(closing['membership'])
    removals = [e for e in moves if not member(e['new'])]
    if not retained and not removals:
        row['reason_codes'] = ['removal_boundary_unknown']
        return row
    entry_time = t0 if original else instant(entries[0]['at'])
    entry = baseline if original else at(entry_time)
    boundary = closing if retained else at(instant(removals[-1]['at']))
    done = set(config.get('done_status_ids', []))
    known_statuses = set(config.get('known_status_ids', [])) or done | set(config.get('active_status_ids', [])) | set(config.get('review_status_ids', []))
    if not done or boundary['status'] not in known_statuses or entry['status'] not in known_statuses:
        row['reason_codes'] = ['workflow_mapping_unavailable']
        return row
    row.update(coverage='ready', origin='original' if original else 'added',
               outcome=('done' if closing['status'] in done else 'unfinished') if retained else 'removed',
               eligible=not issue.get('is_subtask') and entry['status'] not in done,
               baseline_points=entry['points'], closing_points=boundary['points'],
               status=boundary['status'], assignee=boundary['assignee'], feature=boundary['feature'],
               application=boundary['application'], membership_event_count=len(moves),
               first_entry=entry_time.isoformat(), time_basis='close' if retained else 'final_removal',
               estimate_basis='start' if original else 'first_entry',
               already_done=entry['status'] in done, stage_days={})
    statuses = [e for e in events if e['field'] == 'status' and instant(e['at']) <= t1]
    row['reopened'] = any(t0 < instant(e['at']) <= t1 and e['old'] in done and e['new'] not in done and member(at(instant(e['at']))['membership']) for e in statuses)
    active = set(config.get('active_status_ids', []))
    starts = [instant(e['at']) for e in statuses if e['new'] in active]
    # A recorded creation status can establish first active entry; absence cannot.
    first_status = statuses[0]['old'] if statuses else baseline['status']
    if first_status in active and created:
        starts.append(created)
    if starts:
        first = min(starts)
        if row['outcome'] == 'unfinished':
            row['closing_age_days'] = max(0, (t1 - first).total_seconds() / 86400)
        if row['outcome'] == 'done' and row['eligible']:
            finishes = [instant(e['at']) for e in statuses if e['new'] in done and e['old'] not in done]
            if finishes and max(finishes) >= first:
                row['cycle_days'] = (max(finishes) - first).total_seconds() / 86400
    boundaries = sorted({t0, t1, *(instant(e['at']) for e in events if e['field'] in {'status', 'membership'} and t0 < instant(e['at']) < t1)})
    if created and t0 < created < t1:
        boundaries = sorted(set(boundaries) | {created})
    for left, right in zip(boundaries, boundaries[1:]):
        state = at(left)
        if member(state['membership']):
            status = state['status']
            row['stage_days'][status] = row['stage_days'].get(status, 0) + (right - left).total_seconds() / 86400
    blocked = config.get('blocked_status_ids')
    row['blocked_days'] = sum(v for k, v in row['stage_days'].items() if k in blocked) if blocked is not None else None
    row['daily'] = None
    if config.get('daily_events_validated'):
        from datetime import timedelta, time
        from .timezones import board_timezone as resolve_timezone
        try:
            board_timezone = resolve_timezone(config.get('timezone', 'Asia/Kolkata'))
            day, last_day = t0.astimezone(board_timezone).date(), t1.astimezone(board_timezone).date()
            if (last_day - day).days <= 366:
                row['daily'] = []
                while day <= last_day:
                    cutoff = min(t1, datetime.combine(day + timedelta(days=1), time.min, board_timezone).astimezone(timezone.utc) - timedelta(microseconds=1))
                    state = at(cutoff)
                    in_scope = member(state['membership']) and row['eligible']
                    row['daily'].append({'date': day.isoformat(), 'scope': int(in_scope), 'done': int(in_scope and state['status'] in done),
                                         'wip': int(in_scope and state['status'] in config['wip_status_ids']) if config.get('wip_status_ids') else None})
                    day += timedelta(days=1)
        except (ValueError, KeyError):
            row['daily'] = None
    return row
