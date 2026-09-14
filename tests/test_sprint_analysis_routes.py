from datetime import UTC, datetime, timedelta
import uuid

from cryptography.fernet import Fernet
import pytest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User, UserProject, UserBoard, UserBoardSprint
from app.features.automation.sprint_viewer.models import ReportView, SprintComponent, SprintComponentRevision
from app.features.automation.sprint_viewer.repository import get_or_create_snapshot
from app.features.automation.sprint_viewer.analysis.metrics import calculate


@pytest.fixture
def analysis_app(tmp_path):
    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = 'test-secret'
        WTF_CSRF_ENABLED = False
        SESSION_COOKIE_SECURE = False
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{(tmp_path / "v2.db").as_posix()}'
        FERNET_KEY = Fernet.generate_key().decode()
        JIRA_BASE_URL = 'https://jira.example'
        JIRA_SOURCE_ID = 'v2-test'
        SPRINT_VIEWER_MODE = 'snapshot'
        SPRINT_VIEWER_V2_ENABLED = True
        LOG_TO_CONSOLE = False
        LOG_DIR = str(tmp_path / 'logs')
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        user = User(eid='TEST1', email='test@example.com', display_name='Test', password_hash='x', jira_pat_enc=b'placeholder')
        user.set_password('Password12345')
        db.session.add(user); db.session.flush()
        user_id = user.id
        project = UserProject(user_id=user.id, project_key='TEST', admin_projects=True)
        db.session.add(project); db.session.flush()
        db.session.add(UserBoard(project_id=project.id, board_id=10, board_name='Test board', board_type='scrum'))
        db.session.add(UserBoardSprint(user_id=user.id, board_id=10, sprint_id=42, sprint_name='Closed sprint', sprint_state='closed', start_date='2026-01-05T00:00:00Z', complete_date='2026-01-15T00:00:00Z'))
        db.session.flush()
        scope, snapshot, _ = get_or_create_snapshot(user, 10, 42)
        history = SprintComponent.query.filter_by(snapshot_id=snapshot.id, component_key='history').one()
        revision = SprintComponentRevision(component_id=history.id, revision=1, state='ready')
        db.session.add(revision); db.session.flush()
        row = dict(issue_id='1', issue_key='TEST-1', summary='=Dangerous spreadsheet formula', issue_type='Story',
                   origin='original', outcome='unfinished', coverage='ready', eligible=True, baseline_points=3,
                   assignee={'id': 'key:a', 'label': 'Developer A'}, status='review', events=[])
        data = calculate([row], population_complete=True, revision=str(revision.id))
        data.update(rows=[row], suggestions=[], mapping_version='test', calendar_version='test')
        revision.output = {'analysis_v2': data}; history.state = 'ready'; history.published_revision_id = revision.id
        view = ReportView(user_id=user.id, scope_id=scope.id, snapshot_id=snapshot.id, client_action_nonce=str(uuid.uuid4()),
                          expires_at=datetime.now(UTC)+timedelta(minutes=5), access_state={'core': 'granted', 'history': 'granted', 'metrics': 'granted'}, verified_revisions={'history': revision.id})
        db.session.add(view); db.session.commit()
        view_id = view.id
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id); session['_fresh'] = True
    yield app, client, view_id
    with app.app_context():
        db.session.remove(); db.engine.dispose()


@pytest.mark.parametrize('mode,enabled,users,expected', [
    ('snapshot', True, '', True),
    ('snapshot', False, '', False),
    ('direct', True, '', False),
    ('snapshot', True, '999999', False),
    ('snapshot', True, 'current', True),
])
def test_viewer_activation_requires_mode_flag_and_allowlist(analysis_app, mode, enabled, users, expected):
    app, client, _ = analysis_app
    if users == 'current':
        with client.session_transaction() as session:
            users = session['_user_id']
    app.config.update(SPRINT_VIEWER_MODE=mode, SPRINT_VIEWER_V2_ENABLED=enabled,
                      SPRINT_VIEWER_SNAPSHOT_USER_IDS=users)
    response = client.get('/automation/sprint-viewer')
    assert response.status_code == 200
    assert ('id="sprintViewerV2"' in response.text) is expected


def test_analysis_evidence_export_and_revisions(analysis_app):
    _, client, view = analysis_app
    base = f'/automation/sprint-viewer/views/{view}'
    response = client.get(base+'/analysis')
    assert response.status_code == 200
    data = response.json
    assert len(data['role_sections']) == 5
    ref = data['metrics']['unfinished']['evidence_ref']
    issues = client.get(base+'/issues', query_string={'evidence': ref, 'revision': data['revision']}).json
    assert issues['total'] == 1
    assert client.get(base+'/issues?evidence=forged').status_code == 400
    assert client.get(base+'/issues?revision=forged').status_code == 409
    csv = client.get(base+'/export', query_string={'evidence': ref}).text
    assert "'=Dangerous" in csv and 'TEST-1' in csv


def test_expired_grant_blocks_analysis_and_export(analysis_app):
    app, client, view = analysis_app
    with app.app_context():
        db.session.get(ReportView, view).expires_at = datetime.now(UTC)-timedelta(seconds=1)
        db.session.commit()
    for operation in ('analysis', 'issues', 'export', 'trends'):
        assert client.get(f'/automation/sprint-viewer/views/{view}/{operation}').status_code == 403


def test_collected_summary_survives_unavailable_history_and_respects_grants(analysis_app):
    from app.features.automation.sprint_viewer.calculations import METRIC_CATEGORIES
    from app.features.automation.sprint_viewer.models import SprintMetricMembership
    app, client, view_id = analysis_app
    with app.app_context():
        view = db.session.get(ReportView, view_id)
        view.access_state = {'core':'granted', 'history':'unavailable', 'metrics':'granted'}
        core = SprintComponent.query.filter_by(snapshot_id=view.snapshot_id, component_key='core').one()
        revision = SprintComponentRevision(component_id=core.id, revision=1, state='ready', output={
            'groups':[{'issues':[{'issue_id':'1','issue_key':'TEST-1','summary':'Collected item','issue_type':'Story',
                                 'assignee_name':'Developer A','status':'Done','story_points':3,'feature_key':'F-1'}]}]})
        db.session.add(revision); db.session.flush(); core.published_revision_id = revision.id; core.state = 'ready'
        verified = {'core':revision.id}
        for category in METRIC_CATEGORIES:
            component = SprintComponent.query.filter_by(snapshot_id=view.snapshot_id, component_key=category).one()
            included = category in {'original_commitment','completed_original','total_completed'}
            rev = SprintComponentRevision(component_id=component.id, revision=1, state='ready', output={'count':int(included)})
            db.session.add(rev); db.session.flush(); component.state = 'ready'; component.published_revision_id = rev.id
            verified[category] = rev.id
            if included:
                db.session.add(SprintMetricMembership(category_revision_id=rev.id, jira_issue_id='1', issue_key='TEST-1', story_points=3))
        view.verified_revisions = verified
        db.session.commit()
    base = f'/automation/sprint-viewer/views/{view_id}'
    response = client.get(base+'/analysis')
    assert response.status_code == 200
    data = response.json
    assert data['jira_summary']['planned']['value'] == 1
    assert data['jira_summary']['plan_completed']['value'] == 100
    assert data['jira_summary']['delivered_points']['value'] == 3
    assert data['metrics']['planned']['value'] is None  # no fake historical coverage
    ref = data['jira_summary']['completed']['evidence_ref']
    row = client.get(base+'/issues', query_string={'evidence':ref}).json['issues'][0]
    assert row['collected']['assignee'] == 'Developer A'
    assert row['assignee'] is None and row['baseline_points'] is None
    with app.app_context():
        db.session.get(ReportView, view_id).access_state = {'core':'granted','history':'unavailable','metrics':'denied'}
        db.session.commit()
    assert client.get(base+'/analysis').json['jira_summary'] == {}
    assert client.get(base+'/issues', query_string={'evidence':ref}).status_code == 400


def test_failed_query_exposes_blocked_dependents_as_terminal(analysis_app, monkeypatch):
    from types import SimpleNamespace
    from app.features.automation.sprint_viewer import jobs
    from app.features.automation.sprint_viewer.models import SprintSnapshot
    from app.features.automation.sprint_viewer.repository import serialize_status
    app, _, view_id = analysis_app
    with app.app_context():
        view = db.session.get(ReportView, view_id)
        for key in ('history','comments','metrics'):
            component = SprintComponent.query.filter_by(snapshot_id=view.snapshot_id, component_key=key).one()
            component.state = 'missing'
        failed = SprintComponent.query.filter_by(snapshot_id=view.snapshot_id, component_key='original_commitment').one()
        failed.state = 'failed'; failed.error_code = 'JIRA_QUERY_FAILED'
        db.session.commit()
        status = serialize_status(db.session.get(SprintSnapshot, view.snapshot_id), view)
        for key in ('history','comments','metrics'):
            assert status['components'][key]['state'] == 'unavailable'
            assert status['components'][key]['error_code'] == 'DEPENDENCY_UNAVAILABLE'
        core = SprintComponent.query.filter_by(snapshot_id=view.snapshot_id, component_key='core').one()
        revision = SprintComponentRevision(component_id=core.id, revision=1, state='ready', output={'groups':[]})
        db.session.add(revision); db.session.flush()
        core.state = 'ready'; core.published_revision_id = revision.id
        view.access_state = {'base':'granted','core':'granted'}
        view.verified_revisions = {'core':revision.id}
        db.session.commit()
        snapshot = db.session.get(SprintSnapshot, view.snapshot_id)
        user = db.session.get(User, view.user_id)
        job = SimpleNamespace(id='test-grant', cursor={'view_id':view_id}, state='running', lease_until=None)
        monkeypatch.setattr(jobs, '_context', lambda _: (None, user, snapshot, 'synthetic'))
        monkeypatch.setattr(jobs, '_current_job', lambda *args: job)
        monkeypatch.setattr(jobs, 'sprint_viewer_service', lambda: object())
        jobs._run_authorize_view(job, 'owner', 1, 1)
        assert job.state == 'succeeded'
        assert view.access_state['metrics'] == 'unavailable'
        assert view.access_state['history'] == 'unavailable'


def test_reviews_idempotency_conflict_and_validation(analysis_app):
    _, client, view = analysis_app
    url = f'/automation/sprint-viewer/views/{view}/records'
    body = dict(kind='action', record_key='action-1', expected_revision=0, idempotency_key='request-1', payload={'title':'Follow up', 'owner':'Team', 'due_date':'2026-09-20', 'state':'Open'})
    assert client.post(url, json=body).json['record']['revision'] == 1
    assert client.post(url, json=body).json['record']['revision'] == 1
    assert client.post(url, json={**body, 'idempotency_key':'request-2'}).status_code == 409
    body['payload']['due_date'] = 'bad-date'
    assert client.post(url, json={**body, 'idempotency_key':'request-3'}).status_code == 400


def test_closed_only_and_rendered_shell(analysis_app):
    app, client, view = analysis_app
    text = client.get('/automation/sprint-viewer').text
    assert 'Past sprint analysis' in text and 'View as' in text
    assert 'Active sprint' not in text
    with app.app_context():
        UserBoardSprint.query.filter_by(sprint_id=42).one().sprint_state='active'
        db.session.commit()
    response = client.post('/automation/sprint-viewer/issues', json={'board_id':10, 'sprint_id':42})
    assert response.status_code == 400 and response.json['error']['code'] == 'sprint_not_closed'


def _previous_view_assignment_fixture():
    issue = {
        'id': '2',
        'key': 'TEST-2',
        'fields': {
            'summary': 'Assignment changes during sprint',
            'created': '2026-01-01T00:00:00Z',
            'customfield_10106': 5,
            'customfield_11700': {'value': 'Application'},
            'customfield_10100': 'F-1',
            'status': {'name': 'Done'},
            'issuetype': {'name': 'Story', 'subtask': False},
            'assignee': {'key': 'B', 'name': 'B', 'displayName': 'Developer B'},
        },
        'changelog': {
            'total': 1,
            'startAt': 0,
            'histories': [{
                'id': 'assignment-change',
                'created': '2026-01-10T00:00:00Z',
                'items': [{
                    'fieldId': 'assignee',
                    'from': 'A',
                    'fromString': 'A',
                    'to': 'B',
                    'toString': 'B',
                }],
            }],
        },
    }
    comments = [
        {'id': 'before-sprint', 'author': {'key': 'A', 'name': 'A'}, 'created': '2026-01-01T00:00:00Z'},
        {'id': 'inside-a', 'author': {'key': 'A', 'name': 'A'}, 'created': '2026-01-08T00:00:00Z'},
        {'id': 'wrong-before-change', 'author': {'key': 'B', 'name': 'B'}, 'created': '2026-01-08T01:00:00Z'},
        {'id': 'wrong-after-change', 'author': {'key': 'A', 'name': 'A'}, 'created': '2026-01-12T00:00:00Z'},
        {'id': 'inside-b', 'author': {'key': 'B', 'name': 'B'}, 'created': '2026-01-12T01:00:00Z'},
        {'id': 'after-sprint', 'author': {'key': 'B', 'name': 'B'}, 'created': '2026-01-20T00:00:00Z'},
    ]
    return issue, comments


def test_previous_view_direct_core_does_not_wait_for_relevant_comments(analysis_app, monkeypatch):
    from copy import deepcopy
    from app.features.automation.sprint_viewer import routes
    from app.services.sprint_viewer_service import SprintViewerService

    app, client, _ = analysis_app
    issue, comments = _previous_view_assignment_fixture()
    calls = []

    class Client:
        def get_json(self, path, **kwargs):
            calls.append(path)
            if path.endswith('/comment'):
                return {'comments': deepcopy(comments), 'total': len(comments), 'startAt': 0}
            return deepcopy(issue)

    service = SprintViewerService('https://jira.example', http_client=Client())
    monkeypatch.setattr(
        service,
        'fetch_all_issues_for_sprint',
        lambda *args, **kwargs: {'issues': [deepcopy(issue)], 'total': 1},
    )
    monkeypatch.setattr(routes, '_sprint_service', lambda: service)
    monkeypatch.setattr(routes, '_get_user_pat', lambda: 'synthetic-test-token')
    monkeypatch.setattr(routes, '_validate_pat_belongs_to_user', lambda _pat: None)
    app.config.update(SPRINT_VIEWER_MODE='direct', SPRINT_VIEWER_V2_ENABLED=False)

    core = client.post('/automation/sprint-viewer/issues', json={'board_id': 10, 'sprint_id': 42})
    assert core.status_code == 200
    assert core.json['work_type_mix']['overall']['Story']['count'] == 1
    assert core.json['groups'][0]['issues'][0]['relevant_comment_count'] is None
    assert calls == []

    result = client.post(
        '/automation/sprint-viewer/issues',
        json={'board_id': 10, 'sprint_id': 42, 'component': 'comments'},
    )
    assert result.status_code == 200
    assert result.json['issues'][0]['relevant_comment_count'] == 2
    assert result.json['issues'][0]['comment_coverage'] == 'complete'
    assert result.json['stats']['relevant_comment_count'] == 2
    assert calls == ['/rest/api/2/issue/TEST-2', '/rest/api/2/issue/TEST-2/comment']


def test_previous_view_browser_keeps_core_interactive_during_background_enrichment(page, analysis_app):
    import json
    import threading
    from werkzeug.serving import make_server

    app, _, _ = analysis_app
    app.config.update(SPRINT_VIEWER_MODE='direct', SPRINT_VIEWER_V2_ENABLED=False)
    core = {
        'ok': True,
        'total': 3,
        'standard_total': 2,
        'total_sp': 8,
        'sprint': {'name': 'Closed sprint', 'start_date': '2026-01-05T00:00:00Z', 'complete_date': '2026-01-15T00:00:00Z'},
        'stats': {
            'unestimated_count': 0,
            'unestimated_pct': 0,
            'bug_count': 1,
            'bug_sp': 3,
            'bug_pct': 50,
            'unassigned_count': 0,
            'unassigned_pct': 0,
            'relevant_comment_count': None,
            'zero_relevant_comment_count': None,
            'zero_relevant_comment_pct': None,
            'carryover_count': 0,
            'carryover_sp': 0,
        },
        'work_type_mix': {
            'totals': {'count': 3, 'pts': 10, 'estimated_count': 3, 'unestimated_count': 0},
            'overall': {
                'Story': {'count': 1, 'pts': 5, 'issue_pct': 33.3, 'points_pct': 50},
                'Defect': {'count': 1, 'pts': 3, 'issue_pct': 33.3, 'points_pct': 30},
                'Sub-task': {'count': 1, 'pts': 2, 'issue_pct': 33.3, 'points_pct': 20},
            },
            'by_assignee': [{
                'assignee_eid': 'B',
                'assignee_name': 'Developer B',
                'total_count': 3,
                'total_pts': 10,
                'estimated_count': 3,
                'unestimated_count': 0,
                'types': {
                    'Story': {'count': 1, 'pts': 5, 'points_pct': 50},
                    'Defect': {'count': 1, 'pts': 3, 'points_pct': 30},
                    'Sub-task': {'count': 1, 'pts': 2, 'points_pct': 20},
                },
            }],
        },
        'groups': [{
            'principal_id': 'key:B',
            'assignee_eid': 'B',
            'assignee_name': 'Developer B',
            'issue_count': 1,
            'sp_sum': 5,
            'relevant_comment_count': None,
            'issues': [{
                'issue_id': '2',
                'issue_key': 'TEST-2',
                'summary': 'Core renders first',
                'issue_type': 'Story',
                'status': 'Done',
                'story_points': 5,
                'relevant_comment_count': None,
            }],
        }],
    }
    comments = {
        'ok': True,
        'component': 'comments',
        'issues': [{'issue_id': '2', 'issue_key': 'TEST-2', 'comment_total': 6, 'relevant_comment_count': 2, 'comment_coverage': 'complete'}],
        'stats': {'relevant_comment_count': 2, 'zero_relevant_comment_count': 0, 'zero_relevant_comment_pct': 0},
    }
    metrics = {'ok': True}
    init_script = f"""
      (() => {{
        const originalFetch = window.fetch.bind(window);
        const response = (payload) => new Response(JSON.stringify(payload), {{
          status: 200,
          headers: {{'Content-Type': 'application/json'}}
        }});
        window.fetch = (input, options = {{}}) => {{
          const url = typeof input === 'string' ? input : input.url;
          if (url.endsWith('/api/automation/sprint-viewer/sprints')) {{
            return Promise.resolve(response({json.dumps({'ok': True, 'sprints': [{'id': 42, 'name': 'Closed sprint', 'state': 'closed'}]})}));
          }}
          if (url.endsWith('/api/automation/sprint-viewer/issues')) {{
            const body = JSON.parse(options.body || '{{}}');
            if (body.component === 'comments') {{
              window.__commentsRequested = true;
              return new Promise((resolve) => {{ window.__releaseComments = () => resolve(response({json.dumps(comments)})); }});
            }}
            return Promise.resolve(response({json.dumps(core)}));
          }}
          if (url.endsWith('/api/automation/sprint-viewer/metrics')) {{
            window.__metricsRequested = true;
            return new Promise((resolve) => {{ window.__releaseMetrics = () => resolve(response({json.dumps(metrics)})); }});
          }}
          return originalFetch(input, options);
        }};
      }})();
    """
    page.add_init_script(script=init_script)

    server = make_server('127.0.0.1', 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    page_errors = []
    console_errors = []
    page.on('pageerror', lambda error: page_errors.append(str(error)))
    page.on('console', lambda message: console_errors.append(message.text) if message.type == 'error' else None)
    try:
        page.goto(origin + '/auth/login')
        page.locator('input[name="identifier"]').fill('test@example.com')
        page.locator('input[name="password"]').fill('Password12345')
        page.locator('button[type="submit"], input[type="submit"]').first.click()
        page.goto(origin + '/automation/sprint-viewer')
        page.select_option('#projectKey', 'TEST')
        page.select_option('#boardId', '10')
        page.locator('#sprintId option[value="42"]').wait_for(state='attached')
        page.select_option('#sprintId', '42')
        page.locator('#fetchIssuesBtn').click()

        page.wait_for_function('window.__commentsRequested === true && window.__metricsRequested === true')
        assert page.locator('#workTypeMixBox').is_visible()
        assert page.locator('#workBreakdownTitle').inner_text() == 'Sprint Work Breakdown'
        assert page.locator('#workTypeTotalCount').inner_text() == '3'
        assert page.locator('#workTypeTotalPoints').inner_text() == '10'
        assert page.locator('#workTypePointBar .sv-point-segment').count() == 3
        assert 'Sub-task' in page.locator('#workTypeOverall').inner_text()
        assert '% of points' in page.locator('.sv-breakdown-table thead').inner_text()
        assert 'Developer B' in page.locator('#workTypeByDeveloper').inner_text()
        assert '50% of developer pts' in page.locator('#workTypeByDeveloper').inner_text()
        assert page.locator('#estimationCoverageValue').inner_text() == '100%'
        assert page.locator('#bugSp').inner_text() == '3'
        assert page.locator('#loadingOverlay').evaluate('(el) => getComputedStyle(el).display') == 'none'
        assert page.locator('#assigneeAccordion tbody tr td').nth(6).inner_text() == 'Unavailable'

        page.locator('#assigneeAccordion .accordion-button').click()
        page.locator('#assigneeAccordion .accordion-collapse.show').wait_for()
        page.evaluate('window.__releaseComments()')
        page.wait_for_function("document.getElementById('relevantCommentCount').textContent === '2'")
        assert page.locator('#assigneeAccordion tbody tr td').nth(6).inner_text() == '2'
        assert page.locator('#assigneeAccordion .accordion-collapse').get_attribute('class').endswith('show')

        page.evaluate('window.__releaseMetrics()')
        page.locator('#metricsUnavailableMessage').wait_for(state='visible')
        assert page.locator('#committedFmt').inner_text() == '—'
        assert not page_errors
        assert not console_errors
    finally:
        page.goto('about:blank')
        server.shutdown()
        thread.join(timeout=5)


def test_previous_view_rebuilds_cached_snapshot_with_old_comment_semantics(analysis_app):
    from app.features.automation.sprint_viewer.models import SprintSnapshot, SprintSnapshotSeries

    app, client, _ = analysis_app
    app.config.update(SPRINT_VIEWER_MODE='snapshot', SPRINT_VIEWER_V2_ENABLED=False)
    with app.app_context():
        user = User.query.first()
        _scope, old_snapshot, _created = get_or_create_snapshot(user, 10, 42)
        old_snapshot.status = 'ready'
        series = db.session.get(SprintSnapshotSeries, old_snapshot.series_id)
        series.active_snapshot_id = old_snapshot.id
        series.candidate_snapshot_id = None
        comments_component = SprintComponent.query.filter_by(
            snapshot_id=old_snapshot.id,
            component_key='comments',
        ).one()
        revision = SprintComponentRevision(
            component_id=comments_component.id,
            revision=1,
            state='ready',
            output={'time_basis': 'visible comments at collection, cutoff at sprint completion'},
        )
        db.session.add(revision)
        db.session.flush()
        comments_component.state = 'ready'
        comments_component.published_revision_id = revision.id
        db.session.commit()
        old_snapshot_id = old_snapshot.id

    response = client.post(
        '/automation/sprint-viewer/issues',
        json={'board_id': 10, 'sprint_id': 42, 'client_action_id': str(uuid.uuid4())},
    )
    assert response.status_code == 202
    assert response.json['snapshot_id'] != old_snapshot_id
    with app.app_context():
        replacement = db.session.get(SprintSnapshot, response.json['snapshot_id'])
        assert replacement.calculation_version == 1
        assert replacement.status in {'pending', 'processing'}


def test_v2_rendered_roles_drilldown_review_and_mobile(page, analysis_app, tmp_path):
    import json
    import threading
    from werkzeug.serving import make_server
    app, _, view = analysis_app
    with app.app_context():
        snapshot = db.session.get(ReportView, view).snapshot_id
    server = make_server('127.0.0.1', 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    requests = []
    page.on('request', lambda req: requests.append(req.url))
    page.route('**/automation/sprint-viewer/sprints', lambda route: route.fulfill(json={'ok':True, 'sprints':[{'id':42,'name':'Closed sprint','state':'closed'}, {'id':43,'name':'Other sprint','state':'closed'}]}))
    page.route('**/automation/sprint-viewer/issues', lambda route: route.fulfill(json={'ok':True,'view_id':view,'snapshot_id':snapshot}))
    page.route('**/snapshots/*/status?*', lambda route: route.fulfill(json={'ok':True,'access':{'core':'granted','history':'granted'},'components':{'core':{'state':'ready'},'history':{'state':'ready'}}}))
    try:
        page.goto(origin+'/auth/login')
        page.locator('input[name="identifier"]').fill('test@example.com')
        page.locator('input[name="password"]').fill('Password12345')
        page.locator('button[type="submit"], input[type="submit"]').first.click()
        page.goto(origin+'/automation/sprint-viewer')
        assert page.locator('#svProject').input_value() == ''
        assert page.locator('#svBoard').is_disabled()
        assert page.locator('#svAnalyze').is_disabled()
        assert not any('/sprint-viewer/sprints' in url or '/sprint-viewer/issues' in url for url in requests)
        page.select_option('#svProject', 'TEST')
        assert page.locator('#svBoard').input_value() == ''
        assert not any('/sprint-viewer/sprints' in url for url in requests)
        page.select_option('#svBoard', '10')
        page.locator('#svSprint option[value="42"]').wait_for(state='attached')
        assert page.locator('#svSprint').input_value() == ''
        page.select_option('#svSprint', '42')
        assert not any('/sprint-viewer/issues' in url for url in requests)
        page.locator('#svAnalyze').click()
        page.locator('#svIssues button').first.wait_for()
        assert 'Past sprint analysis' in page.title()
        assert 'Asia/Kolkata' in page.locator('#svDates').inner_text()
        shared = page.locator('#svSummary').inner_text()
        for role in ('developer','po','scrum','manager','team'):
            page.select_option('#svRole', role)
            assert page.locator('#svSummary').inner_text() == shared
        page.locator('#svSummary button').nth(3).click()
        page.locator('#svIssues button').first.click()
        page.locator('#svDrawer').wait_for(state='visible')
        assert page.locator('#svDrawer').is_visible()
        page.keyboard.press('Escape')
        assert not page.locator('#svDrawer').is_visible()
        page.locator('#svAssess').click()
        assert page.locator('#svEdit select').input_value() == 'Not assessed'
        page.select_option('#svEdit select', 'Partially achieved')
        page.locator('#svEditForm button[type="submit"]').click()
        page.wait_for_function("document.getElementById('svAssessment').textContent === 'Partially achieved'")
        page.locator('#svTab-retro').click()
        page.locator('#svNewAction').click()
        page.locator('#svEdit [name="title"]').fill('Follow up review')
        page.locator('#svEdit [name="owner"]').fill('Team')
        page.locator('#svEdit [name="due_date"]').fill('2026-09-20')
        page.locator('#svEditForm button[type="submit"]').click()
        page.get_by_role('heading', name='Follow up review').wait_for()
        page.locator('#svTab-overview').click()
        page.set_viewport_size({'width':1440,'height':1000})
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(tmp_path/'v2-desktop.png'), full_page=False)
        page.set_viewport_size({'width':390,'height':844})
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(tmp_path/'v2-mobile.png'), full_page=False)
        assert page.locator('#sprintViewerV2').evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
        assert page.locator('#svSprint').evaluate('(el) => getComputedStyle(el).fontSize') == '16px'
        assert page.locator('#sprintViewerV2').evaluate('(el) => getComputedStyle(el).fontSize') == '16px'
        before = len([u for u in requests if '/status?' in u or u.endswith('/analysis')])
        page.wait_for_timeout(2300)
        assert len([u for u in requests if '/status?' in u or u.endswith('/analysis')]) == before
        page.select_option('#svSprint', '43')
        assert not page.locator('#svReport').is_visible()
        assert len([u for u in requests if u.endswith('/sprint-viewer/issues')]) == 1
        page.select_option('#svProject', '')
        assert page.locator('#svBoard').input_value() == ''
        assert page.locator('#svSprint').input_value() == ''
        assert not errors
    finally:
        page.goto('about:blank'); server.shutdown(); thread.join(timeout=5)


def test_v2_access_error_is_visible_with_code_and_request_id(page, analysis_app):
    import threading
    from werkzeug.serving import make_server

    app, _, _view = analysis_app
    server = make_server('127.0.0.1', 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    page.route(
        '**/automation/sprint-viewer/sprints',
        lambda route: route.fulfill(json={
            'ok': True,
            'sprints': [{'id': 42, 'name': 'Closed sprint', 'state': 'closed'}],
        }),
    )
    page.route(
        '**/automation/sprint-viewer/issues',
        lambda route: route.fulfill(
            status=403,
            json={
                'ok': False,
                'error': {
                    'code': 'JIRA_PAT_REQUIRED',
                    'message': 'Add a Jira PAT in Settings > Integrations, then try again.',
                },
                'request_id': 'server-denied-123',
            },
        ),
    )
    try:
        page.goto(origin + '/auth/login')
        page.locator('input[name="identifier"]').fill('test@example.com')
        page.locator('input[name="password"]').fill('Password12345')
        page.locator('button[type="submit"], input[type="submit"]').first.click()
        page.goto(origin + '/automation/sprint-viewer')
        page.select_option('#svProject', 'TEST')
        page.select_option('#svBoard', '10')
        page.locator('#svSprint option[value="42"]').wait_for(state='attached')
        page.select_option('#svSprint', '42')
        page.locator('#svAnalyze').click()

        message = page.locator('#svMessage')
        page.wait_for_function(
            "document.getElementById('svMessage').textContent.includes('Settings > Integrations')"
        )
        assert 'Settings > Integrations' in message.inner_text()
        assert 'JIRA_PAT_REQUIRED' in message.inner_text()
        assert 'server-denied-123' in message.inner_text()
        assert 'sv2-message-danger' in (message.get_attribute('class') or '')
        assert message.get_attribute('role') == 'alert'
    finally:
        page.goto('about:blank')
        server.shutdown()
        thread.join(timeout=5)


def test_v2_header_typography_matches_existing_automation_card(page, analysis_app):
    import threading
    from werkzeug.serving import make_server

    app, _, _view = analysis_app
    server = make_server('127.0.0.1', 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        page.goto(origin + '/auth/login')
        page.locator('input[name="identifier"]').fill('test@example.com')
        page.locator('input[name="password"]').fill('Password12345')
        page.locator('button[type="submit"], input[type="submit"]').first.click()

        page.goto(origin + '/automation/rule-copier')
        rule_font = page.locator('#ruleCopierPage').evaluate(
            '(el) => getComputedStyle(el).fontFamily'
        )
        rule_heading_size = page.locator('#ruleCopierPage h3').evaluate(
            '(el) => getComputedStyle(el).fontSize'
        )

        page.goto(origin + '/automation/sprint-viewer')
        viewer_font = page.locator('#sprintViewerV2').evaluate(
            '(el) => getComputedStyle(el).fontFamily'
        )
        viewer_heading_size = page.locator('#sprintViewerV2 h1').evaluate(
            '(el) => getComputedStyle(el).fontSize'
        )
        control_card = page.locator('.sv2-control-card')

        assert viewer_font == rule_font
        assert viewer_heading_size == rule_heading_size == '28px'
        assert control_card.evaluate('(el) => getComputedStyle(el).backgroundColor') == 'rgb(255, 255, 255)'
        assert control_card.evaluate('(el) => getComputedStyle(el).boxShadow') != 'none'
    finally:
        page.goto('about:blank')
        server.shutdown()
        thread.join(timeout=5)


def test_v2_unchanged_poll_does_not_render_and_stops_after_timeout(page, analysis_app):
    import threading
    from werkzeug.serving import make_server
    app, _, view = analysis_app
    with app.app_context():
        snapshot = db.session.get(ReportView, view).snapshot_id
    server = make_server('127.0.0.1', 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    requests = []
    page.on('request', lambda req: requests.append(req.url))
    page.route('**/automation/sprint-viewer/sprints', lambda route: route.fulfill(json={'sprints':[{'id':42,'name':'Closed','state':'closed'}]}))
    page.route('**/automation/sprint-viewer/issues', lambda route: route.fulfill(json={'view_id':view,'snapshot_id':snapshot}))
    page.route('**/snapshots/*/status?*', lambda route: route.fulfill(json={
        'access':{'core':'granted','history':'granted','comments':'pending'},
        'components':{'core':{'state':'ready'},'history':{'state':'ready'},'comments':{'state':'running'}}}))
    try:
        page.clock.install()
        page.goto(origin+'/auth/login')
        page.locator('input[name="identifier"]').fill('test@example.com')
        page.locator('input[name="password"]').fill('Password12345')
        page.locator('button[type="submit"], input[type="submit"]').first.click()
        page.goto(origin+'/automation/sprint-viewer')
        page.select_option('#svProject', 'TEST'); page.select_option('#svBoard', '10')
        page.locator('#svSprint option[value="42"]').wait_for(state='attached')
        page.select_option('#svSprint', '42'); page.locator('#svAnalyze').click()
        page.locator('#svIssues button').first.wait_for()
        page.wait_for_function("document.getElementById('svMessage').textContent.includes('Import in progress')")
        page.evaluate("window.dropdownChanges = 0; new MutationObserver(() => window.dropdownChanges++).observe(document.getElementById('svDeveloper'), {childList:true})")
        page.locator('#svSprint').focus()
        with page.expect_response('**/snapshots/*/status?*'):
            page.clock.run_for(2500)
        assert len([url for url in requests if url.endswith('/analysis')]) == 1
        assert page.evaluate('window.dropdownChanges') == 0
        with page.expect_response('**/snapshots/*/status?*'):
            page.clock.fast_forward(120000)
        page.wait_for_function("document.getElementById('svMessage').textContent.includes('checks paused')")
        count = len([url for url in requests if '/status?' in url])
        page.clock.run_for(15000)
        assert len([url for url in requests if '/status?' in url]) == count
    finally:
        page.goto('about:blank'); server.shutdown(); thread.join(timeout=5)


def test_v2_worker_publishes_normalized_history_and_windowed_comments(analysis_app, monkeypatch):
    from app.core.dependencies import crypto_service
    from app.features.automation.sprint_viewer import jobs
    from app.features.automation.sprint_viewer.models import BackgroundJob
    from app.features.automation.sprint_viewer.repository import published_output
    from app.services.sprint_viewer_service import SprintViewerService
    from copy import deepcopy
    app, _, _ = analysis_app
    raw = {'id':'2','key':'TEST-2','fields':{'summary':'Worker fixture','created':'2026-01-01T00:00:00Z',
           'customfield_10106':5,'customfield_10104':[{'id':43}], 'customfield_11700':{'id':'app','value':'Application'},
           'customfield_10100':'F-1','status':{'id':'done','name':'Done'},'issuetype':{'name':'Story','subtask':False},
           'assignee':{'key':'A','name':'A','displayName':'Developer A'}},
           'changelog':{'total':2,'histories':[
               {'id':'h1','created':'2026-01-10T00:00:00Z','items':[{'fieldId':'status','from':'doing','to':'done','fromString':'Doing','toString':'Done'}]},
               {'id':'h2','created':'2026-01-20T00:00:00Z','items':[{'fieldId':'customfield_10106','from':'3','to':'5','fromString':'3','toString':'5'}]}]}}
    class Client:
        def get_json(self, path, **kwargs):
            if '/board/' in path:
                return {'values':[{'id':43,'state':'closed'}],'total':1,'startAt':0,'isLast':True}
            if path.endswith('/comment'):
                return {'comments':[],'total':0,'startAt':0}
            return deepcopy(raw)
    service = SprintViewerService('https://jira.example', http_client=Client())
    monkeypatch.setattr(jobs, 'sprint_viewer_service', lambda: service)
    monkeypatch.setattr(service, 'fetch_all_issues_for_sprint', lambda *args: {'issues':[deepcopy(raw)],'total':1})
    monkeypatch.setattr(service, '_aggregate_by_jql_with_client', lambda *args: {'count':1,'sp':5,'memberships':[{'issue_id':'2','issue_key':'TEST-2','story_points':5}]})
    monkeypatch.setattr(service, '_fetch_all_comments_for_issue', lambda *args: [
        {'id':str(i),'author':{'key':'A'},'created':date} for i,date in enumerate(['2026-01-01T00:00:00Z','2026-01-08T00:00:00Z','2026-01-20T00:00:00Z'])])
    with app.app_context():
        user = User.query.first(); user.jira_pat_enc = crypto_service().encrypt('synthetic-test-token')
        BackgroundJob.query.update({'state':'succeeded'})
        db.session.add(UserBoardSprint(user_id=user.id, board_id=10, sprint_id=43, sprint_name='Worker sprint', sprint_state='closed',start_date='2026-01-05T00:00:00Z',complete_date='2026-01-15T00:00:00Z'))
        db.session.flush()
        _, snapshot, _ = get_or_create_snapshot(user,10,43)
        snapshot.sprint_metadata = {**snapshot.sprint_metadata, 'analysis_mapping':{'mapping_version':'test','fields':{
            'points':{'field_id':'customfield_10106','parser_kind':'number','validation_status':'validated'},
            'membership':{'field_id':'customfield_10104','parser_kind':'sprints','validation_status':'validated'}}},
            'analysis_config':{'population_discovery_validated':True,'known_status_ids':['doing','done'],'done_status_ids':['done'],'active_status_ids':['doing']}}
        db.session.commit()
        owner = str(uuid.uuid4()); epoch = jobs.acquire_leadership(owner)
        for _ in range(20):
            job = jobs.claim_job(owner,epoch,'core') or jobs.claim_job(owner,epoch,'enrichment')
            if job is None:
                BackgroundJob.query.filter_by(state='retry_wait').update({'available_at':datetime.now(UTC)-timedelta(seconds=1)})
                db.session.commit()
                job = jobs.claim_job(owner,epoch,'core') or jobs.claim_job(owner,epoch,'enrichment')
            if job is None: break
            jobs.run_job(job,owner,epoch)
        history = published_output(snapshot.id,'history')[1].output
        assert history['analysis_v2']['metrics']['planned_points']['value'] == 3
        assert history['analysis_v2']['rows'][0]['outcome'] == 'done'
        assert published_output(snapshot.id,'comments')[1].output['issues']['2']['relevant_comment_count'] == 1


def test_previous_view_worker_uses_assignee_at_comment_time(analysis_app, monkeypatch):
    from app.core.dependencies import crypto_service
    from app.features.automation.sprint_viewer import jobs
    from app.features.automation.sprint_viewer.models import BackgroundJob
    from app.features.automation.sprint_viewer.repository import published_output
    from app.services.sprint_viewer_service import SprintViewerService
    from copy import deepcopy

    app, _, _ = analysis_app
    raw, comments = _previous_view_assignment_fixture()

    class Client:
        def get_json(self, path, **kwargs):
            if '/board/' in path:
                return {'values': [{'id': 44, 'state': 'closed'}], 'total': 1, 'startAt': 0, 'isLast': True}
            return deepcopy(raw)

    service = SprintViewerService('https://jira.example', http_client=Client())
    monkeypatch.setattr(jobs, 'sprint_viewer_service', lambda: service)
    monkeypatch.setattr(service, 'fetch_all_issues_for_sprint', lambda *args: {'issues': [deepcopy(raw)], 'total': 1})
    monkeypatch.setattr(service, '_aggregate_by_jql_with_client', lambda *args: {'count': 1, 'sp': 5, 'memberships': [{'issue_id': '2', 'issue_key': 'TEST-2', 'story_points': 5}]})
    monkeypatch.setattr(service, '_fetch_all_comments_for_issue', lambda *args: deepcopy(comments))

    with app.app_context():
        user = User.query.first()
        user.jira_pat_enc = crypto_service().encrypt('synthetic-test-token')
        BackgroundJob.query.update({'state': 'succeeded'})
        db.session.add(UserBoardSprint(
            user_id=user.id,
            board_id=10,
            sprint_id=44,
            sprint_name='Previous-view sprint',
            sprint_state='closed',
            start_date='2026-01-05T00:00:00Z',
            complete_date='2026-01-15T00:00:00Z',
        ))
        db.session.flush()
        _, snapshot, _ = get_or_create_snapshot(user, 10, 44)
        snapshot.calculation_version = 1
        db.session.commit()

        owner = str(uuid.uuid4())
        epoch = jobs.acquire_leadership(owner)
        for _ in range(20):
            job = jobs.claim_job(owner, epoch, 'core') or jobs.claim_job(owner, epoch, 'enrichment')
            if job is None:
                BackgroundJob.query.filter_by(state='retry_wait').update(
                    {'available_at': datetime.now(UTC) - timedelta(seconds=1)}
                )
                db.session.commit()
                job = jobs.claim_job(owner, epoch, 'core') or jobs.claim_job(owner, epoch, 'enrichment')
            if job is None:
                break
            jobs.run_job(job, owner, epoch)

        output = published_output(snapshot.id, 'comments')[1].output
        assert output['issues']['2']['relevant_comment_count'] == 2
        assert output['issues']['2']['visible_ids'] == ['inside-a', 'inside-b']
        assert output['time_basis'] == 'visible comments by the assignee at comment time within activation/start through actual close'


def test_additive_migration_from_prior_schema_preserves_snapshot(analysis_app):
    from sqlalchemy import text, inspect
    app, _, view_id = analysis_app
    # Only this disposable fixture database is changed to the exact prior table set.
    with app.app_context():
        snapshot_id = db.session.get(ReportView, view_id).snapshot_id
        db.session.remove()
        with db.engine.begin() as connection:
            connection.execute(text('DROP TABLE sprint_review_records'))
            connection.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)'))
            connection.execute(text("INSERT INTO alembic_version VALUES ('b27d5f8a9c02')"))
    runner = app.test_cli_runner()
    upgrade = runner.invoke(args=['setup-db','--apply'])
    assert upgrade.exit_code == 0, upgrade.output
    with app.app_context():
        assert 'sprint_review_records' in inspect(db.engine).get_table_names()
        assert db.session.get(ReportView, view_id).snapshot_id == snapshot_id
