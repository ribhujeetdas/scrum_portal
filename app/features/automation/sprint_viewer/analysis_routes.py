"""Granted revision reads and private human writes; no Jira calls on read paths."""
from copy import deepcopy
import csv
from datetime import UTC, datetime
import io
import re

from flask import current_app, request, Response
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from ....core.api import json_ok, json_error
from ....extensions import db
from .models import ReportView, SprintSnapshotSeries, SprintReviewRecord
from .repository import owned_snapshot, owned_view, published_output, SnapshotNotFound
from .routes import _view_access_fresh
from .schemas import InputValidationError, require_json_object
from .review_service import validate_record
from .analysis.metrics import calculate
from ....models import UserBoardSprint

ROLES = {
    'team': {'title': 'What did we deliver and what remains?', 'metrics': ['added_completed', 'cycle_median', 'repeated_carryover', 'goal_linked_unfinished'], 'sections': ['Developer contribution · assignment context', 'Scope movement and recorded reasons', 'Work mix'], 'focus': 'all'},
    'developer': {'title': 'My historical assignments and follow-up', 'metrics': ['assigned_completed', 'assigned_unfinished', 'assigned_cycle', 'assigned_reopened'], 'sections': ['Selected developer assignments at close / removal', 'Handoffs and contribution evidence'], 'focus': 'developer'},
    'po': {'title': 'Delivered capabilities, acceptance and scope', 'metrics': ['plan_completed', 'accepted_stories', 'goal_linked_unfinished', 'unique_scope_change'], 'sections': ['Sprint-scoped feature delivery', 'Goal links and recorded acceptance', 'Scope changes and reasons'], 'focus': 'stories'},
    'scrum': {'title': 'Recorded constraints and retrospective follow-up', 'metrics': ['cycle_median', 'closing_age', 'reopened', 'blocked_duration'], 'sections': ['Flow and unfinished age', 'Recorded blockers and dependencies', 'Current action status'], 'focus': 'unfinished'},
    'manager': {'title': 'Delivery consistency and team context', 'metrics': ['plan_completed', 'throughput_baseline', 'cycle_p85', 'unique_scope_change'], 'sections': ['Comparable sprint history', 'Work mix and quality context', 'Capacity notes and dependencies'], 'focus': 'all'},
}


def context(view_id):
    if not current_app.config.get('SPRINT_VIEWER_V2_ENABLED'):
        raise SnapshotNotFound('Feature disabled')
    view = ReportView.query.filter_by(id=view_id, user_id=current_user.id, revoked_at=None).first()
    if view is None:
        raise SnapshotNotFound('View not found')
    scope, snapshot = owned_snapshot(current_user, view.snapshot_id)
    view = owned_view(current_user, snapshot.id, view.id)
    if not _view_access_fresh(view) or (view.access_state or {}).get('core') != 'granted':
        raise PermissionError('Jira access must be checked again.')
    series = db.session.get(SprintSnapshotSeries, snapshot.series_id)
    return scope, snapshot, view, series


def analysis_data(snapshot, view):
    try:
        if view.access_state.get('history') != 'granted' or view.access_state.get('metrics') != 'granted':
            raise SnapshotNotFound('Enrichment unavailable')
        _, history = published_output(snapshot.id, 'history')
        if view.verified_revisions.get('history') != history.id:
            raise PermissionError('Historical revision must be authorized again.')
        data = deepcopy((history.output or {}).get('analysis_v2'))
        if not data:
            raise SnapshotNotFound('Historical v2 import required')
        data['revision'] = str(history.id)
        comments = {}
        if view.access_state.get('comments') == 'granted':
            try:
                _, comment_revision = published_output(snapshot.id, 'comments')
                if view.verified_revisions.get('comments') == comment_revision.id:
                    comments = (comment_revision.output or {}).get('issues', {})
            except SnapshotNotFound:
                pass
        for row in data['rows']:
            item = comments.get(str(row['issue_id']))
            row['relevant_comment_count'] = item.get('relevant_comment_count') if item else None
            row['comment_coverage'] = 'ready' if item else 'unavailable'
        return data
    except SnapshotNotFound:
        _, core = published_output(snapshot.id, 'core')
        data = calculate([], population_complete=False, revision=f'core-{core.id}')
        data.update(rows=[], suggestions=[], revision=f'core-{core.id}', mapping_version='pending', calendar_version='unconfigured')
        from .analysis.rules import evaluate
        data['suggestions'] = evaluate([], data, {}, snapshot.series_id)
        for group in (core.output or {}).get('groups', []):
            for issue in group.get('issues', []):
                data['rows'].append({**{key: issue.get(key) for key in ('issue_id', 'issue_key', 'summary', 'issue_type', 'is_subtask')},
                                     'coverage': 'unavailable', 'reason_codes': ['historical_enrichment_unavailable'],
                                     'baseline_points': None, 'status': None, 'assignee': None, 'origin': None, 'outcome': None})
        return data


def records_query(scope, series):
    return SprintReviewRecord.query.filter_by(user_id=current_user.id, source_id=scope.source_id, board_id=series.board_id, sprint_id=series.sprint_id)


def serialize_record(row):
    return dict(record_key=row.record_key, kind=row.kind, revision=row.revision, payload=row.payload,
                author_id=row.user_id, recorded_at=row.created_at.isoformat() + ('+00:00' if row.created_at.tzinfo is None else ''))


def latest_records(query):
    found = {}
    for row in query.order_by(SprintReviewRecord.revision.desc()).all():
        found.setdefault(row.record_key, serialize_record(row))
    return list(found.values())


def query_rows(data):
    rows = list(data['rows'])
    evidence = request.args.get('evidence')
    if evidence:
        ids = data['evidence'].get(evidence)
        if ids is None:
            observation = next((s for s in data['suggestions'] if s['id'] == evidence and s['status'] == 'matched'), None)
            ids = observation['evidence_issue_ids'] if observation else None
        if ids is None:
            raise InputValidationError('Evidence reference does not belong to this revision.')
        rows = [r for r in rows if str(r['issue_id']) in ids]
    focus = request.args.get('focus', 'all')
    if focus not in {'all', 'stories', 'developer', 'unfinished', 'original', 'added', 'removed', 'unestimated', 'reopened'}:
        raise InputValidationError('Invalid issue focus.')
    if focus in {'original', 'added'}:
        rows = [r for r in rows if r.get('origin') == focus]
    elif focus in {'removed', 'unfinished'}:
        rows = [r for r in rows if r.get('outcome') == focus]
    elif focus == 'stories':
        rows = [r for r in rows if r.get('issue_type') == 'Story']
    elif focus == 'developer':
        rows = [r for r in rows if (r.get('assignee') or {}).get('id') == request.args.get('developer')]
    elif focus == 'unestimated':
        rows = [r for r in rows if r.get('eligible') and r.get('baseline_points') is None]
    elif focus == 'reopened':
        rows = [r for r in rows if r.get('reopened')]
    search = request.args.get('search', '').strip().casefold()
    if len(search) > 200:
        raise InputValidationError('Search is too long.')
    if search:
        rows = [r for r in rows if search in f"{r.get('issue_key', '')} {r.get('summary', '')}".casefold()]
    for key in ('feature', 'application', 'issue_type', 'status'):
        if request.args.get(key):
            rows = [r for r in rows if (str((r.get(key) or {}).get('id')) if isinstance(r.get(key), dict) else str(r.get(key))) == request.args[key]]
    sort = request.args.get('sort', 'issue_key')
    if sort not in {'issue_key', 'summary', 'status', 'issue_type'}:
        raise InputValidationError('Invalid sort field.')
    return sorted(rows, key=lambda r: (str(r.get(sort) or '').casefold(), str(r['issue_id'])))


def dispatch(view_id, operation, issue_id=None):
    try:
        scope, snapshot, view, series = context(view_id)
        from .analysis.sections import add_sections
        from .analysis.collected import add_collected_context
        data = add_sections(add_collected_context(snapshot, view, analysis_data(snapshot, view)))
        records = latest_records(records_query(scope, series))
        from .analysis.review_context import add_review_context
        add_review_context(data, records, (snapshot.sprint_metadata or {}).get('analysis_config', {}), datetime.now(UTC))
        from .analysis.comparisons import apply_comparisons
        comparison = read_trends(scope, snapshot, series, data, include_rows=True)
        apply_comparisons(data, comparison)
        if request.args.get('revision') and request.args['revision'] != data['revision']:
            return json_error('Report revision changed. Reload the analysis.', status_code=409, code='REVISION_MISMATCH')
        if operation == 'analysis':
            return json_ok(view_id=view.id, snapshot_id=snapshot.id, sprint_id=series.sprint_id, generation=snapshot.generation,
                           sprint={k: v for k, v in (snapshot.sprint_metadata or {}).items() if k not in {'analysis_mapping', 'analysis_config'}}, role_sections=ROLES,
                           timezone=(snapshot.sprint_metadata or {}).get('analysis_config', {}).get('timezone', 'Asia/Kolkata'),
                           access_expires_at=view.expires_at.isoformat() + ('+00:00' if view.expires_at.tzinfo is None else ''),
                           **{key: value for key, value in data.items() if key not in {'rows', 'evidence', 'suggestions', 'cohorts'}},
                           developers=sorted({(r.get('assignee') or {}).get('id', 'unknown'): (r.get('assignee') or {}) for r in data['rows'] if r.get('assignee')}.values(), key=lambda d: d.get('label', '')),
                           review_records=records, previous_actions=previous_actions(scope, series, snapshot))
        if operation == 'suggestions':
            return json_ok(revision=data['revision'], suggestions=data['suggestions'], availability='ready' if data['population_complete'] else 'unavailable')
        if operation == 'timeline':
            row = next((r for r in data['rows'] if str(r['issue_id']) == issue_id), None)
            if row is None:
                raise SnapshotNotFound('Issue not in revision')
            page = int(request.args.get('event_page', '1'))
            if page < 1:
                raise InputValidationError('Invalid event page.')
            events = row.get('events', [])
            return json_ok(revision=data['revision'], issue={**row, 'events':events[(page-1)*100:page*100]},
                           event_total=len(events), next_event_page=page+1 if len(events) > page*100 else None)
        if operation in {'issues', 'export'}:
            rows = query_rows(data)
            if operation == 'export':
                stream = io.StringIO(newline='')
                writer = csv.writer(stream)
                safe = lambda v: ("'" + str(v)) if str(v).lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else str(v if v is not None else '')
                writer.writerow(['Sprint', series.sprint_id, 'Snapshot', snapshot.id, 'Revision', data['revision'], 'Role', safe(request.args.get('view', 'team')), 'Basis', 'start / first entry / close or final removal'])
                writer.writerow(['Filters', safe(str({key:request.args.get(key) for key in ('focus','developer','search','evidence','feature','application','issue_type','status','sort') if request.args.get(key)}))])
                writer.writerow(['Key', 'Summary', 'Type', 'Assignee at boundary', 'Origin', 'Outcome', 'Status at boundary', 'Baseline points', 'Coverage', 'Assignee at collection', 'Status at collection', 'Points at collection', 'Feature at collection', 'Application at collection'])
                for r in rows:
                    writer.writerow([safe(v) for v in [r.get('issue_key'), r.get('summary'), r.get('issue_type'), (r.get('assignee') or {}).get('label'), r.get('origin'), r.get('outcome'), r.get('status'), r.get('baseline_points'), r.get('coverage'), *[(r.get('collected') or {}).get(k) for k in ('assignee','status','points','feature','application')]]])
                return Response(stream.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename="sprint-analysis.csv"'})
            page = int(request.args.get('page', '1'))
            if page < 1:
                raise InputValidationError('Page must be positive.')
            return json_ok(revision=data['revision'], issues=[{k: v for k, v in r.items() if k != 'events'} for r in rows[(page-1)*25:page*25]], total=len(rows), page=page, page_size=25)
        if operation == 'trends':
            return json_ok(**read_trends(scope, snapshot, series, data))
        if operation == 'record-history':
            key = request.args.get('record_key', '')
            page = max(1, int(request.args.get('page', '1')))
            query = records_query(scope, series).filter_by(record_key=key).order_by(SprintReviewRecord.revision.desc())
            return json_ok(records=[serialize_record(row) for row in query.offset((page-1)*25).limit(25).all()], page=page, total=query.count())
        if operation == 'records':
            return write_record(scope, series, data)
        raise SnapshotNotFound('Unknown operation')
    except PermissionError as exc:
        return json_error(str(exc), status_code=403, code='ACCESS_CHECK_EXPIRED')
    except SnapshotNotFound:
        return json_error('Report or evidence not found.', status_code=404, code='REPORT_NOT_FOUND')
    except (InputValidationError, ValueError, TypeError):
        return json_error('Invalid analysis or review request.', status_code=400, code='INVALID_INPUT')


def write_record(scope, series, data):
    body = require_json_object(request.get_json(silent=True))
    key, idem, kind = body.get('record_key', ''), body.get('idempotency_key', ''), body.get('kind')
    if not re.fullmatch(r'[A-Za-z0-9:_-]{1,80}', key) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', idem):
        raise InputValidationError('Invalid record identity.')
    expected = body.get('expected_revision')
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
        raise InputValidationError('Expected revision is required.')
    payload = validate_record(kind, require_json_object(body.get('payload')))
    query = records_query(scope, series)
    prior = SprintReviewRecord.query.filter_by(user_id=current_user.id, idempotency_key=idem).first()
    if prior:
        if prior.source_id != scope.source_id or prior.board_id != series.board_id or prior.sprint_id != series.sprint_id or prior.record_key != key or prior.kind != kind:
            return json_error('Idempotency key already used.', status_code=409, code='RECORD_CONFLICT')
        if any(prior.payload.get(k) != v for k, v in payload.items() if k != 'completed_at'):
            return json_error('Idempotency key was used with different content.', status_code=409, code='RECORD_CONFLICT')
        return json_ok(record=serialize_record(prior))
    last = query.filter_by(record_key=key).order_by(SprintReviewRecord.revision.desc()).first()
    if (last.revision if last else 0) != expected or (last and last.kind != kind):
        return json_error('Record changed. Your draft has not been saved.', status_code=409, code='RECORD_CONFLICT')
    source = payload.get('source_evidence')
    if source and source not in data['evidence'] and not any(o['id'] == source for o in data['suggestions']) and not (last and last.payload.get('source_evidence') == source):
        raise InputValidationError('Source evidence is not in this report.')
    observation = next((o for o in data['suggestions'] if o['id'] == source), None)
    if observation:
        payload['source_rule_id'] = observation['rule_id']
        payload['source_rule_version'] = observation['rule_version']
    elif last and source == last.payload.get('source_evidence'):
        for field in ('source_rule_id', 'source_rule_version'):
            if field in last.payload:
                payload[field] = last.payload[field]
    if kind == 'issue_review' and not any(str(r['issue_id']) == payload.get('issue_id') for r in data['rows']):
        raise InputValidationError('Issue is not in this report.')
    if kind == 'action':
        payload['completed_at'] = (last.payload.get('completed_at') if last and last.payload.get('state') == 'Done' else datetime.now(UTC).isoformat()) if payload['state'] == 'Done' else ''
    record = SprintReviewRecord(user_id=current_user.id, source_id=scope.source_id, board_id=series.board_id,
                                sprint_id=series.sprint_id, record_key=key, kind=kind, revision=expected+1,
                                idempotency_key=idem, payload=payload)
    db.session.add(record)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return json_error('Concurrent edit. Your draft has not been saved.', status_code=409, code='RECORD_CONFLICT')
    return json_ok(record=serialize_record(record))


def read_trends(scope, snapshot, series, selected, include_rows=False):
    from .analysis.boundaries import instant
    from .analysis.trends import comparable_summary
    def summary(meta, data):
        return {'sprint_id': meta.get('id'), 'name': meta.get('name'), 'close': meta.get('complete_date'), 'revision': data['revision'],
                **({'unfinished_ids': data['cohorts']['unfinished']} if include_rows else {}),
                **{key: data['metrics'][key]['value'] for key in ('completed', 'plan_completed', 'added', 'removed', 'cycle_median')}}
    current_meta = snapshot.sprint_metadata or {}
    t0 = instant(current_meta.get('activated_date') or current_meta.get('start_date'))
    t1 = instant(current_meta.get('complete_date'))
    candidates = (ReportView.query.join(SprintSnapshotSeries, ReportView.snapshot_id == SprintSnapshotSeries.active_snapshot_id)
                  .filter(ReportView.user_id == current_user.id, ReportView.revoked_at.is_(None),
                          SprintSnapshotSeries.scope_id == scope.id, SprintSnapshotSeries.board_id == series.board_id,
                          SprintSnapshotSeries.sprint_id != series.sprint_id)
                  .order_by(ReportView.created_at.desc()).limit(32).all())
    previous, seen = [], set()
    for candidate in candidates:
        try:
            _, prior, granted, prior_series = context(candidate.id)
            meta = prior.sprint_metadata or {}
            start = instant(meta.get('activated_date') or meta.get('start_date'))
            end = instant(meta.get('complete_date'))
            if prior_series.sprint_id in seen or not all((t0, t1, start, end)) or end > t0:
                continue
            if meta.get('analysis_config') != current_meta.get('analysis_config') or meta.get('analysis_mapping') != current_meta.get('analysis_mapping'):
                continue
            if abs(((end-start) - (t1-t0)).total_seconds()) > 86400:
                continue
            prior_data = analysis_data(prior, granted)
            if not prior_data['population_complete']:
                continue
            seen.add(prior_series.sprint_id)
            previous.append(summary(meta, prior_data))
        except (SnapshotNotFound, PermissionError):
            continue
    previous.sort(key=lambda p: instant(p['close']), reverse=True)
    result = comparable_summary(summary(current_meta, selected), previous[:7])
    catalogue = UserBoardSprint.query.filter_by(user_id=current_user.id, board_id=series.board_id, sprint_state='closed').all()
    preceding = [r for r in catalogue if r.sprint_id != series.sprint_id and instant(r.complete_date) and t0 and instant(r.complete_date) <= t0]
    preceding.sort(key=lambda r: instant(r.complete_date), reverse=True)
    result['consecutive_prior_verified'] = bool(previous and preceding and previous[0]['sprint_id'] == preceding[0].sprint_id)
    return result


def previous_actions(scope, series, snapshot):
    from .analysis.boundaries import instant
    selected_close = instant((snapshot.sprint_metadata or {}).get('complete_date'))
    result, seen = [], set()
    views = (ReportView.query.join(SprintSnapshotSeries, ReportView.snapshot_id == SprintSnapshotSeries.active_snapshot_id)
             .filter(ReportView.user_id == current_user.id, ReportView.revoked_at.is_(None),
                     SprintSnapshotSeries.scope_id == scope.id, SprintSnapshotSeries.board_id == series.board_id,
                     SprintSnapshotSeries.sprint_id != series.sprint_id)
             .order_by(ReportView.created_at.desc()).limit(32).all())
    for candidate in views:
        try:
            prior_scope, prior_snapshot, prior_view, prior_series = context(candidate.id)
            prior_close = instant((prior_snapshot.sprint_metadata or {}).get('complete_date'))
            if not prior_close or not selected_close or prior_close >= selected_close:
                continue
            if prior_series.sprint_id in seen:
                continue
            seen.add(prior_series.sprint_id)
            for record in latest_records(records_query(prior_scope, prior_series)):
                if record['kind'] == 'action':
                    result.append({**record, 'view_id':prior_view.id, 'sprint_id':prior_series.sprint_id,
                                   'sprint_name':(prior_snapshot.sprint_metadata or {}).get('name')})
        except (SnapshotNotFound, PermissionError):
            continue
    return result
