"""Keep authorized collected Jira data usable without claiming historical coverage."""
import hashlib

from ..calculations import METRIC_CATEGORIES
from ..models import SprintMetricMembership
from ..repository import SnapshotNotFound, published_output


def add_collected_context(snapshot, view, data):
    diagnostics = []
    access = view.access_state or {}
    config = (snapshot.sprint_metadata or {}).get('analysis_config') or {}
    if access.get('history') != 'granted':
        diagnostics.append(f"Historical access: {access.get('history', 'pending')}. Collected values below are not sprint-close values.")
    elif not data.get('population_complete'):
        reasons = sorted({reason for row in data['rows'] for reason in row.get('reason_codes', [])})
        if not config.get('population_discovery_validated'):
            reasons.append('population_discovery_not_validated')
        diagnostics.append('Historical coverage: ' + ', '.join(reasons or ['incomplete']) + '.')
    data['diagnostics'] = diagnostics
    data['jira_summary'] = {}
    rows = {str(row['issue_id']): row for row in data['rows']}
    try:
        _, core = published_output(snapshot.id, 'core')
    except SnapshotNotFound:
        return data
    if view.verified_revisions.get('core') != core.id:
        raise PermissionError('Collected revision must be authorized again.')
    for group in (core.output or {}).get('groups', []):
        for issue in group.get('issues', []):
            identity = str(issue['issue_id'])
            row = rows.setdefault(identity, dict(issue_id=identity, issue_key=issue.get('issue_key'),
                summary=issue.get('summary'), issue_type=issue.get('issue_type'), is_subtask=issue.get('is_subtask'),
                coverage='unavailable', origin=None, outcome=None, baseline_points=None,
                reason_codes=['historical_enrichment_unavailable']))
            row['collected'] = dict(assignee=issue.get('assignee_name'), status=issue.get('status'),
                points=issue.get('story_points'), feature=issue.get('feature_key'), application=issue.get('app_name'))
    # These are the existing ScriptRunner cohorts, with their own explicit basis.
    # Do not replace historical metric definitions or use ungranted query results.
    categories = {}
    revisions = [str(core.id)]
    if access.get('metrics') == 'granted':
        for key in METRIC_CATEGORIES:
            try:
                _, revision = published_output(snapshot.id, key)
            except SnapshotNotFound:
                continue
            if view.verified_revisions.get(key) != revision.id:
                continue
            revisions.append(str(revision.id))
            members = SprintMetricMembership.query.filter_by(category_revision_id=revision.id).all()
            if len(members) != (revision.output or {}).get('count'):
                continue
            categories[key] = members
            for member in members:
                rows.setdefault(member.jira_issue_id, dict(issue_id=member.jira_issue_id, issue_key=member.issue_key,
                    summary='', issue_type=None, coverage='unavailable', origin=None, outcome=None,
                    baseline_points=None, reason_codes=['collected_details_unavailable']))
    if str(data['revision']).startswith('core-'):
        data['revision'] = 'core-' + '-'.join(revisions)
    if access.get('comments') == 'granted':
        try:
            _, comments = published_output(snapshot.id, 'comments')
            if view.verified_revisions.get('comments') == comments.id:
                for identity, row in rows.items():
                    comment = ((comments.output or {}).get('issues') or {}).get(identity)
                    if comment is not None:
                        row['relevant_comment_count'] = comment.get('relevant_comment_count')
                        row['comment_coverage'] = 'ready'
        except SnapshotNotFound:
            pass

    def metric(name, category, points=False, denominator=None):
        if category not in categories:
            return
        members = categories[category]
        ids = sorted(m.jira_issue_id for m in members)
        ref = hashlib.sha256(f"{data['revision']}:jira:{name}:{ids}".encode()).hexdigest()
        data['evidence'][ref] = ids
        known = [m for m in members if m.story_points is not None]
        value = sum(m.story_points for m in known) if points else len(ids)
        available = 'partial' if points and len(known) != len(members) else 'ready'
        reasons = ['collected_estimates_not_baseline'] if points else []
        if points and members and not known:
            value, available = None, 'unavailable'
        numerator = value
        if denominator is not None:
            if denominator not in categories:
                return
            total = categories[denominator]
            if points:
                # Do not compare different estimate coverage subsets in a ratio.
                if len(known) != len(members) or any(m.story_points is None for m in total):
                    return
                denominator = sum(m.story_points for m in total)
            else:
                denominator = len(total)
            value = value / denominator * 100 if denominator else None
        data['jira_summary'][name] = dict(value=value, availability=available if value is not None else 'unavailable',
            numerator=numerator, denominator=denominator, unit='percent' if denominator is not None else 'story_points' if points else 'issues',
            measured_count=len(known) if points else len(ids), eligible_count=len(ids),
            reason_codes=reasons, evidence_ref=ref, cohort_label=category.replace('_', ' '),
            time_basis='Jira ScriptRunner sprint query; estimates observed at collection, not historical baseline',
            calculation_version='jira-query-1', source='Jira sprint query')

    for name, category in [('planned','original_commitment'), ('completed','total_completed'), ('added','added_scope'), ('removed','removed_scope')]:
        metric(name, category)
    for name, category in [('planned_points','original_commitment'), ('delivered_points','total_completed'), ('added_points','added_scope'), ('removed_points','removed_scope')]:
        metric(name, category, points=True)
    metric('plan_completed', 'completed_original', denominator='original_commitment')
    metric('plan_completed_points', 'completed_original', points=True, denominator='original_commitment')
    if data['jira_summary'] and not data.get('population_complete'):
        diagnostics.append('Summary cards labelled Jira sprint query use the same saved cohorts as the original viewer. Historical flow metrics still require complete evidence.')
    data['rows'] = list(rows.values())
    return data
