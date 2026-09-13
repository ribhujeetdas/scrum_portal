import hashlib
import json

CATALOG = {
    'SV-01': ('Review queue at sprint close', 'Review the queue together and record any shared constraint.', 'flow'),
    'SV-02': ('Late additions', 'Check recorded reasons for late changes.', 'scope'),
    'SV-03': ('Repeated carryover', 'Discuss slicing, clarification or dependency follow-up.', 'planning'),
    'SV-04': ('Explicit blockers', 'Review recorded blockers and agree an owner for follow-up.', 'flow'),
    'SV-05': ('Reopened work', 'Inspect transitions and record what additional work was needed.', 'quality'),
    'SV-06': ('Missing baseline estimates', 'Confirm whether estimation is expected for this work type.', 'planning'),
    'SV-07': ('Scope movement', 'Review changes and their recorded reasons.', 'scope'),
    'SV-08': ('Aging unfinished work', 'Review remaining work and next steps.', 'flow'),
    'SV-09': ('Overdue actions', 'Confirm ownership and update the next step or due date.', 'actions'),
    'SV-10': ('Delivery variation', 'Review capacity and scope context before changing forecasts.', 'planning'),
}


def evaluate(rows, analysis, config, sprint_key):
    rows = [row for row in rows if not row.get('is_subtask') and row.get('origin')]
    result = []
    for rule_id, (title, prompt, category) in CATALOG.items():
        selected, reason = [], None
        threshold = 1
        if not analysis['population_complete']:
            reason = 'historical_population_incomplete'
        elif rule_id == 'SV-01':
            review = config.get('review_status_ids', [])
            reason = None if review else 'review_mapping_unavailable'
            selected = [r for r in rows if r.get('outcome') == 'unfinished' and r.get('status') in review]
        elif rule_id == 'SV-05':
            selected = [r for r in rows if r.get('reopened')]
        elif rule_id == 'SV-02':
            from .calendar import late_addition_cutoff
            from .boundaries import instant
            cutoff = late_addition_cutoff(config.get('close_date'), config)
            reason = None if cutoff else 'working_calendar_required'
            if cutoff:
                selected = [r for r in rows if r.get('origin') == 'added' and instant(r.get('first_entry')) and instant(r['first_entry']).astimezone(cutoff[1]).date() >= cutoff[0]]
            threshold = 2
        elif rule_id == 'SV-04':
            threshold = config.get('blocked_elapsed_days', 2)
            if not config.get('blocked_status_ids') or any(r.get('blocked_days') is None for r in rows if r.get('origin')):
                reason = 'blocked_mapping_unavailable'
            else:
                selected = [r for r in rows if (r.get('blocked_days') or 0) >= threshold]
        elif rule_id == 'SV-06':
            selected = [r for r in rows if r.get('eligible') and r.get('baseline_points') is None]
        elif rule_id == 'SV-07':
            threshold = config.get('scope_change_percent', 30)
            if (analysis['metrics']['unique_scope_change']['value'] or 0) > threshold:
                selected = [r for r in rows if str(r['issue_id']) in analysis['cohorts']['changed']]
        elif rule_id == 'SV-08':
            threshold = config.get('age_days', 14)
            selected = [r for r in rows if r.get('closing_age_days') is not None and r['closing_age_days'] > threshold]
            if any(r.get('outcome') == 'unfinished' and r.get('closing_age_days') is None for r in rows):
                reason = 'active_history_unavailable'
        else:
            reason = {'SV-02': 'working_calendar_required', 'SV-03': 'consecutive_sprint_evidence_required', 'SV-04': 'blocked_mapping_unavailable', 'SV-09': 'current_action_status_separate', 'SV-10': 'comparable_history_required'}[rule_id]
        ids = sorted(str(r['issue_id']) for r in selected) if not reason else []
        identity = hashlib.sha256(json.dumps([sprint_key, rule_id, '1', ids, threshold], sort_keys=True).encode()).hexdigest()
        result.append(dict(id=identity, rule_id=rule_id, rule_version='1', category=category,
                           title=title, prompt=prompt, status='unavailable' if reason else 'matched' if ids else 'not_matched',
                           reason_codes=[reason] if reason else [], evidence_issue_ids=ids, count=len(ids), threshold=threshold,
                           time_basis='sprint close', coverage={'checked': len(rows) if not reason else 0, 'eligible': len(rows)}))
    return result
