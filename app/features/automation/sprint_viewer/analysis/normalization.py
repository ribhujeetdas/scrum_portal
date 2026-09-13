"""A single normalized issue/event contract for historical analysis imports."""
from .field_registry import CONFIGURED, parse_value
from .boundaries import instant, project_issue


def normalize_issue(raw, registry, resolver):
    fields = raw.get('fields') or {}
    extracted = registry.extract(raw)
    extracted['summary'] = {'value':fields.get('summary'), 'reason':'known' if 'summary' in fields else 'missing_key', 'time_basis':'collection'}
    extracted['issue_type'] = {'value':fields.get('issuetype'), 'reason':'known' if 'issuetype' in fields else 'missing_key', 'time_basis':'collection; unchanged only when complete history proves it'}
    history = raw.get('changelog') or {}
    histories = history.get('histories')
    complete = isinstance(histories, list) and history.get('total') == len(histories) and history.get('startAt', 0) == 0
    if instant(fields.get('created')) is None:
        complete = False
    values = {name: item['value'] for name, item in extracted.items()}
    # Stable system IDs, with no display-name matching.
    status = fields.get('status') or {}
    assignee = fields.get('assignee')
    values.update(status=str(status.get('id')) if status.get('id') is not None else None,
                  assignee={'id': resolver.resolve(assignee), 'label': (assignee or {}).get('displayName') or 'Unassigned'})
    aliases = {'status': 'status', 'assignee': 'assignee'}
    aliases.update({spec['field_id']: name for name, spec in registry.fields.items() if spec.get('field_id') and spec.get('validation_status') in CONFIGURED})
    for name, spec in registry.fields.items():
        if spec.get('validation_status') in CONFIGURED:
            for alias in spec.get('history_identifiers', []):
                if alias in aliases and aliases[alias] != name:
                    raise ValueError('Ambiguous history identifier')
                aliases[alias] = name
    events, seen = [], set()
    for h in histories or []:
        if instant(h.get('created')) is None:
            complete = False
        for ordinal, item in enumerate(h.get('items') or []):
            token = item.get('fieldId') or item.get('field')
            if token == 'issuetype':
                # Old type IDs alone cannot establish historical subtask inclusion.
                complete = False
                extracted['issue_type']['reason'] = 'issue_type_history_requires_mapping'
            name = aliases.get(token)
            if not name:
                continue
            identity = (h.get('id'), ordinal)
            if not h.get('id') or identity in seen:
                complete = False
            seen.add(identity)
            before, after = item.get('from'), item.get('to')
            if name == 'assignee':
                before = {'id': resolver.observe_changelog(before, item.get('fromString')) if before is not None else f"unknown:{raw.get('id')}:{h.get('id')}:before" if item.get('fromString') else 'unassigned', 'label': item.get('fromString') or 'Unassigned'}
                after = {'id': resolver.observe_changelog(after, item.get('toString')) if after is not None else f"unknown:{raw.get('id')}:{h.get('id')}:after" if item.get('toString') else 'unassigned', 'label': item.get('toString') or 'Unassigned'}
            elif name == 'points':
                # Jira changelog numerical IDs are strings; this explicit adapter accepts them.
                def number(v):
                    if v is None:
                        return None
                    if isinstance(v, bool):
                        return None
                    try:
                        return parse_value('number', float(v))['value']
                    except (TypeError, ValueError):
                        return None
                old, new = number(before), number(after)
                if (before is not None and old is None) or (after is not None and new is None):
                    values[name] = None
                    old, new = None, None
                    extracted[name] = {**extracted.get(name, {}), 'value': None, 'reason': 'invalid_history_number'}
                before, after = old, new
            elif name == 'membership':
                # Enable only for validated comma-separated numeric raw IDs. Never parse labels.
                def ids(v):
                    if v is None or v == '':
                        return []
                    parts = str(v).split(',')
                    return [int(p.strip()) for p in parts] if all(p.strip().isdigit() for p in parts) else None
                before, after = ids(before), ids(after)
                if before is None or after is None:
                    complete = False
            elif name not in {'status', 'feature'}:
                # Optional structured fields do not invalidate membership/status coverage.
                values[name] = None
                before, after = None, None
                if name in extracted:
                    extracted[name] = {**extracted[name], 'value': None, 'reason': 'unsupported_history'}
            events.append({'source_history_id': h.get('id'), 'ordinal': ordinal, 'at': h.get('created'),
                           'field': name, 'field_id': token, 'old': before, 'new': after})
    required = ('membership',)
    if any(extracted.get(name, {}).get('reason') != 'known' for name in required):
        complete = False
    values.update(issue_id=str(raw.get('id')), issue_key=raw.get('key'), summary=fields.get('summary') or '',
                  issue_type=(fields.get('issuetype') or {}).get('name'), is_subtask=(fields.get('issuetype') or {}).get('subtask', False),
                  created=fields.get('created'), events=events, history_complete=complete,
                  field_coverage=extracted, mapping_version=registry.version)
    return values


def normalize_and_project(raw, registry, resolver, sprint, config):
    normalized = normalize_issue(raw, registry, resolver)
    projected = project_issue(normalized, int(sprint['id']), sprint.get('activated_date') or sprint.get('start_date'), sprint.get('complete_date'), config)
    projected['field_coverage'] = normalized['field_coverage']
    projected['mapping_version'] = registry.version
    projected['start_basis'] = 'actual_activation' if sprint.get('activated_date') else 'scheduled_start_fallback'
    return projected
