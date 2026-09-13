"""Current human review facts, explicitly separate from frozen Jira calculations."""
from datetime import date
import hashlib
from .timezones import board_timezone


def add_review_context(data, records, config, now):
    try:
        today = now.astimezone(board_timezone(config.get('timezone', 'Asia/Kolkata'))).date()
    except (ValueError, KeyError):
        today = now.date()
    actions = [r for r in records if r['kind'] == 'action' and r['payload'].get('state') != 'Archived']
    due = [r for r in actions if date.fromisoformat(r['payload']['due_date']) <= today]
    overdue = [r for r in due if r['payload']['state'] != 'Done' and date.fromisoformat(r['payload']['due_date']) < today]
    data['action_context'] = {'time_basis': f'Current action status on {today.isoformat()}', 'due_count': len(due),
                              'completed_due_count': sum(r['payload']['state'] == 'Done' for r in due),
                              'follow_through_percent': sum(r['payload']['state'] == 'Done' for r in due) / len(due) * 100 if due else None,
                              'overdue_record_keys': [r['record_key'] for r in overdue]}
    rule = next((s for s in data['suggestions'] if s['rule_id'] == 'SV-09'), None)
    if rule:
        rule.update(status='matched' if overdue else 'not_matched', reason_codes=[], count=len(overdue),
                    evidence_record_keys=[r['record_key'] for r in overdue], evidence_issue_ids=[],
                    title='Overdue actions · Current action status', time_basis=data['action_context']['time_basis'],
                    coverage={'checked': len(actions), 'eligible': len(actions)},
                    id=hashlib.sha256(str([(r['record_key'],r['revision']) for r in overdue]).encode()).hexdigest())
    by_issue = {r['payload'].get('issue_id'): r for r in records if r['kind'] == 'issue_review'}
    selected = [r for r in data['rows'] if str(r['issue_id']) in by_issue]
    for name, predicate in [
        ('goal_linked_unfinished', lambda r, h: r.get('outcome') == 'unfinished' and h.get('goal_linked')),
        ('accepted_stories', lambda r, h: r.get('issue_type') == 'Story' and r.get('outcome') != 'removed' and h.get('acceptance') == 'Accepted'),
    ]:
        members = [str(r['issue_id']) for r in selected if predicate(r, by_issue[str(r['issue_id'])]['payload'])]
        ref = hashlib.sha256(f"{data['revision']}:{name}:{sorted(members)}:{[(r['record_key'],r['revision']) for r in by_issue.values()]}".encode()).hexdigest()
        data['evidence'][ref] = members
        metric = data['metrics'][name]
        metric.update(value=len(members) if by_issue and data['population_complete'] else None,
                      numerator=len(members), measured_count=len(selected), availability='partial' if by_issue and data['population_complete'] else 'unavailable',
                      cohort_label='Explicit human-reviewed subset', reason_codes=['manual_review_coverage'] if by_issue else ['no_human_issue_reviews'],
                      time_basis='Current human records entered after sprint close', evidence_ref=ref)
