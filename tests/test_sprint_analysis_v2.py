from copy import deepcopy
import math
import pytest

from app.features.automation.sprint_viewer.analysis.field_registry import FieldRegistry, parse_value
from app.features.automation.sprint_viewer.analysis.boundaries import project_issue
from app.features.automation.sprint_viewer.analysis.metrics import calculate


def test_numbers_preserve_zero_and_reject_invalid_values():
    assert parse_value('number', 0)['value'] == 0
    for value in (True, math.nan, math.inf, -1, '3 days', '3'):
        assert parse_value('number', value)['reason'] == 'invalid_shape'
    assert parse_value('number', None)['reason'] == 'present_null'


def test_photo_fields_are_requested_without_optional_mapping_file():
    from app.features.automation.sprint_viewer.analysis.field_registry import load_registry
    registry = load_registry({})
    assert registry.requested_fields() == ['customfield_10100','customfield_10104','customfield_10106','customfield_11700']
    raw = {'fields':{'customfield_10106':0, 'customfield_10104':[{'id':42}],
                     'customfield_10100':'F-1', 'customfield_11700':{'id':'1','value':'App'}}}
    values = registry.extract(raw)
    assert values['points']['value'] == 0
    assert values['membership']['value'] == [42]
    assert values['feature']['value'] == 'F-1'
    assert values['application']['value']['value'] == 'App'
    overridden = load_registry({'JIRA_STORY_POINTS_FIELD':'customfield_900'})
    assert 'customfield_900' in overridden.requested_fields()
    assert 'customfield_10106' not in overridden.requested_fields()


def test_registry_does_not_mutate_source_and_uses_ids():
    registry = FieldRegistry({'mapping_version': 'test', 'fields': {
        'points': {'field_id': 'customfield_9', 'parser_kind': 'number', 'validation_status': 'validated'}}})
    raw = {'fields': {'customfield_9': 0}}
    before = deepcopy(raw)
    assert registry.extract(raw)['points']['value'] == 0
    assert raw == before
    assert registry.extract({'fields': {}})['points']['reason'] == 'missing_key'
    with pytest.raises(ValueError):
        FieldRegistry({'fields': {'x': {'field_id': 'x', 'parser_kind': 'eval'}}})


def issue(events=None, **changes):
    value = dict(issue_id='1', issue_key='T-1', summary='Example', issue_type='Story',
                 is_subtask=False, membership=[42], status='done', points=8,
                 assignee={'id': 'key:a', 'label': 'A'}, feature='F-1', application=None,
                 created='2026-01-01T00:00:00Z', history_complete=True, events=events or [])
    value.update(changes)
    return value


CONFIG = {'done_status_ids': ['done'], 'active_status_ids': ['doing'], 'review_status_ids': ['review']}
START = '2026-01-05T00:00:00Z'
END = '2026-01-15T00:00:00Z'


def test_post_close_edits_rewind_and_keep_baseline_weights():
    events = [dict(at='2026-01-06T00:00:00Z', field='points', old=3, new=5),
              dict(at='2026-01-10T00:00:00Z', field='status', old='doing', new='done'),
              dict(at='2026-01-20T00:00:00Z', field='points', old=5, new=8)]
    row = project_issue(issue(events), 42, START, END, CONFIG)
    assert row['baseline_points'] == 3
    assert row['closing_points'] == 5
    assert row['outcome'] == 'done'
    assert row['origin'] == 'original'


def test_added_then_removed_does_not_reduce_original_unfinished():
    rows = [dict(issue_id='1', origin='original', outcome='unfinished', eligible=True, baseline_points=3, coverage='ready'),
            dict(issue_id='2', origin='added', outcome='removed', eligible=True, baseline_points=2, coverage='ready')]
    result = calculate(rows, population_complete=True)
    assert result['metrics']['unfinished']['value'] == 1
    assert result['metrics']['added']['value'] == 1
    assert result['metrics']['removed']['value'] == 1
    assert result['metrics']['gross_scope_movement']['value'] == 200
    assert result['metrics']['unique_scope_change']['value'] == 100


def test_missing_population_and_zero_denominator_are_not_zero_ratios():
    assert calculate([], population_complete=False)['metrics']['planned']['value'] is None
    assert calculate([], population_complete=True)['metrics']['plan_completed']['value'] is None


def test_readded_original_is_not_removed_or_added():
    events = [dict(at='2026-01-07T00:00:00Z', field='membership', old=[42], new=[]),
              dict(at='2026-01-09T00:00:00Z', field='membership', old=[], new=[42])]
    row = project_issue(issue(events, status='doing'), 42, START, END, CONFIG)
    assert row['origin'] == 'original' and row['outcome'] == 'unfinished'
    assert row['membership_event_count'] == 2


def test_incomplete_history_never_claims_boundary_values():
    row = project_issue(issue(history_complete=False), 42, START, END, CONFIG)
    assert row['coverage'] == 'unavailable'
    assert row['baseline_points'] is None


def test_configured_legacy_points_history_and_raw_immutability():
    from app.services.sprint_viewer_service import SprintViewerService
    service = SprintViewerService('https://jira.example', story_points_field='customfield_999')
    raw = {'fields': {'customfield_999': 8}, 'changelog': {'total': 1, 'histories': [
        {'created': '2026-01-20T00:00:00Z', 'items': [{'field': 'Renamed estimate', 'fieldId': 'customfield_999', 'fromString': '3', 'toString': '8'}]}]}}
    before = deepcopy(raw)
    normalized = service.normalize_configured_fields(raw)
    values, fallback = service._reconstruct_at_sprint_end(normalized, {'story_points': 8}, END)
    assert values['story_points'] == 3 and not fallback
    assert raw == before


def test_trend_baseline_excludes_selected_and_uses_median_of_ratios():
    from app.features.automation.sprint_viewer.analysis.trends import comparable_summary
    result = comparable_summary({'completed': 99}, [{'completed': 2, 'plan_completed': 50}, {'completed': 4, 'plan_completed': 100}])
    assert result['throughput_median'] == 3
    assert result['plan_completion_median'] == 75


def test_created_in_sprint_is_added_and_stage_time_excludes_removed_intervals():
    row = project_issue(issue(status='doing', created='2026-01-08T00:00:00Z'), 42, START, END, CONFIG)
    assert row['origin'] == 'added'
    events = [dict(at='2026-01-07T00:00:00Z', field='membership', old=[42], new=[]),
              dict(at='2026-01-10T00:00:00Z', field='membership', old=[], new=[42])]
    row = project_issue(issue(events, status='doing'), 42, START, END, CONFIG)
    assert row['stage_days']['doing'] == 7


def test_normalizer_matches_changed_configured_ids_and_rejects_legacy_sprint_strings():
    from app.features.automation.sprint_viewer.analysis.normalization import normalize_issue
    from app.integrations.jira.identity import build_identity_resolver
    registry = FieldRegistry({'fields': {'points': {'field_id':'customfield_9','parser_kind':'number','validation_status':'validated'},
                                         'membership': {'field_id':'customfield_8','parser_kind':'sprints','validation_status':'validated'}}})
    raw = {'id':'1','key':'T-1','fields':{'created':START,'customfield_9':5,'customfield_8':[{'id':42}], 'status':{'id':'doing'},'issuetype':{'name':'Story'}},
           'changelog':{'total':1,'histories':[{'id':'h1','created':'2026-01-09T00:00:00Z','items':[{'fieldId':'customfield_9','field':'Renamed estimate','from':'3','to':'5'}]}]}}
    result = normalize_issue(raw, registry, build_identity_resolver([]))
    assert result['history_complete'] and result['events'][0]['old'] == 3
    raw['fields']['customfield_8'] = ['com.atlassian.Sprint[id=42]']
    assert not normalize_issue(raw, registry, build_identity_resolver([]))['history_complete']


def test_daily_samples_require_explicit_coverage_and_stop_at_close():
    config = {**CONFIG, 'daily_events_validated': True, 'timezone': 'UTC', 'wip_status_ids': ['doing']}
    row = project_issue(issue(status='doing'), 42, START, END, config)
    data = calculate([row], population_complete=True)
    assert data['daily']['availability'] == 'ready'
    assert data['daily']['samples'][-1]['date'] == '2026-01-15'
    assert data['daily']['samples'][-1]['wip'] == 1


def test_scoped_registry_and_ambiguous_overrides():
    spec = {'field_id':'customfield_1','parser_kind':'number','validation_status':'validated'}
    override = {'board_ids':[42], 'fields':{'points':{**spec,'field_id':'customfield_2'}}}
    registry = FieldRegistry({'fields':{'points':spec},'overrides':[override]})
    assert registry.for_scope(42).fields['points']['field_id'] == 'customfield_2'
    assert registry.for_scope(43).fields['points']['field_id'] == 'customfield_1'
    with pytest.raises(ValueError, match='Ambiguous'):
        FieldRegistry({'fields':{'points':spec},'overrides':[override,override]}).for_scope(42)


def test_closed_source_verification_checks_returned_state():
    from types import SimpleNamespace
    from app.features.automation.sprint_viewer.jobs import _verify_board_sprint
    client = SimpleNamespace(get_json=lambda *a, **k: {'values':[{'id':42,'state':'active'}],'total':1,'isLast':True,'startAt':0})
    service = SimpleNamespace(_client=client, _headers=lambda pat: {})
    assert not _verify_board_sprint(service, 10, 42, 'synthetic')


def test_comparison_rules_use_consecutive_history_and_minimum_samples():
    from app.features.automation.sprint_viewer.analysis.rules import evaluate
    from app.features.automation.sprint_viewer.analysis.comparisons import apply_comparisons
    from app.features.automation.sprint_viewer.analysis.trends import comparable_summary
    row = dict(issue_id='1',origin='original',outcome='unfinished',eligible=True,coverage='ready',baseline_points=3)
    data = calculate([row],population_complete=True,revision='1')
    data.update(revision='1',rows=[row],suggestions=evaluate([row],data,{},'sprint'))
    prior = [{'revision':str(i+2),'completed':4,'plan_completed':80,'unfinished_ids':['1']} for i in range(5)]
    comparison = comparable_summary({},prior)
    comparison['consecutive_prior_verified'] = True
    apply_comparisons(data,comparison)
    metric = data['metrics']['repeated_carryover']
    assert metric['value'] == 1 and data['evidence'][metric['evidence_ref']] == ['1']
    assert next(r for r in data['suggestions'] if r['rule_id'] == 'SV-10')['status'] == 'matched'


def test_overdue_context_excludes_future_and_completed_actions():
    from datetime import datetime, UTC
    from app.features.automation.sprint_viewer.analysis.review_context import add_review_context
    from app.features.automation.sprint_viewer.analysis.rules import evaluate
    data = calculate([],population_complete=True,revision='1')
    data.update(revision='1',rows=[],suggestions=evaluate([],data,{},'sprint'))
    records = [{'kind':'action','record_key':key,'revision':1,'payload':{'state':state,'due_date':due}}
               for key,state,due in [('a','Open','2026-09-12'),('b','Done','2026-09-12'),('c','Open','2026-09-20')]]
    add_review_context(data,records,{'timezone':'UTC'},datetime(2026,9,13,tzinfo=UTC))
    assert data['action_context']['overdue_record_keys'] == ['a']
    assert data['action_context']['follow_through_percent'] == 50
