import hashlib
from statistics import median


def add_sections(data):
    sections = {}
    for name, field in [('contribution', 'assignee'), ('features', 'feature'), ('work_mix', 'issue_type')]:
        groups = {}
        for row in data['rows']:
            if row.get('coverage') != 'ready' or not row.get('origin') or row.get('is_subtask'):
                continue
            value = row.get(field)
            identity = value.get('id', 'unknown') if isinstance(value, dict) else str(value or 'Unknown')
            label = value.get('label', value.get('value', identity)) if isinstance(value, dict) else str(value or 'Unknown')
            group = groups.setdefault(identity, dict(identity=identity, label=label, done=0, unfinished=0, removed=0, evidence={}, _rows=[]))
            group['_rows'].append(row)
            if row['outcome'] != 'done' or row.get('eligible'):
                group[row['outcome']] += 1
        for group in groups.values():
            rows = group.pop('_rows')
            for outcome in ('done', 'unfinished', 'removed'):
                ids = sorted(str(r['issue_id']) for r in rows if r['outcome'] == outcome and (outcome != 'done' or r.get('eligible')))
                ref = hashlib.sha256(f"{data['revision']}:{name}:{group['identity']}:{outcome}".encode()).hexdigest()
                data['evidence'][ref] = ids
                group['evidence'][outcome] = ref
            completed = [r for r in rows if r['outcome'] == 'done' and r.get('eligible')]
            group['closing_scope'] = sum(r['outcome'] != 'removed' for r in rows)
            group['type_split'] = {kind: sum(r['outcome'] != 'removed' and r.get('issue_type') == kind for r in rows) for kind in ('Story','Bug','Task')}
            group['completed_baseline_points'] = sum(r['baseline_points'] for r in completed if r.get('baseline_points') is not None)
            group['estimated_completed_count'] = sum(r.get('baseline_points') is not None for r in completed)
            if completed and not group['estimated_completed_count']:
                group['completed_baseline_points'] = None
            total = data['metrics']['completed']['value']
            group['team_completed_share'] = len(completed) / total * 100 if total else None
            cycles = [r['cycle_days'] for r in completed if r.get('cycle_days') is not None]
            group['cycle_median'] = median(cycles) if cycles else None
            group['cycle_sample'] = len(cycles)
            group['reopened'] = sum(bool(r.get('reopened')) for r in rows)
        sections[name] = sorted(groups.values(), key=lambda g: (g['label'].casefold(), g['identity']))
    data['sections'] = sections
    return data
