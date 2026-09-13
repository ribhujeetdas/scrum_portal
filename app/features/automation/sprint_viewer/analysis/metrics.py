"""Pure v2 cohorts. Each number carries coverage and exact evidence membership."""
import hashlib
import json
import math
from statistics import median

VERSION = '2.0.0'


def calculate(rows, *, population_complete, revision='unpublished'):
    rows = [r for r in rows if not r.get('is_subtask')]
    complete = population_complete and all(r.get('coverage') == 'ready' for r in rows)
    scope = [r for r in rows if r.get('origin') in {'original', 'added'}]
    eligible = [r for r in scope if r.get('eligible')]
    cohorts = {
        'all': scope,
        'planned': [r for r in eligible if r['origin'] == 'original'],
        'added': [r for r in scope if r['origin'] == 'added'],
        'removed': [r for r in scope if r['outcome'] == 'removed'],
        'completed': [r for r in eligible if r['outcome'] == 'done'],
        'unfinished': [r for r in scope if r['outcome'] == 'unfinished'],
        'unestimated': [r for r in eligible if r.get('baseline_points') is None],
        'reopened': [r for r in scope if r.get('reopened')],
    }
    cohorts['plan_completed'] = [r for r in cohorts['completed'] if r['origin'] == 'original']
    cohorts['added_completed'] = [r for r in cohorts['completed'] if r['origin'] == 'added']
    cohorts['changed'] = [r for r in scope if r['origin'] == 'added' or r['outcome'] == 'removed']
    cohorts['original_unfinished'] = [r for r in eligible if r['origin'] == 'original' and r['outcome'] == 'unfinished']
    cohorts['original_removed'] = [r for r in eligible if r['origin'] == 'original' and r['outcome'] == 'removed']
    evidence, metrics = {}, {}

    def metric(name, selected, *, denominator=None, value=None, unit='issues', reasons=None, measured=None):
        ids = sorted({str(r['issue_id']) for r in selected})
        ref = hashlib.sha256(json.dumps([revision, VERSION, name, ids]).encode()).hexdigest()
        evidence[ref] = ids
        n = len(ids)
        reason = list(reasons or [])
        if not complete:
            reason.append('historical_population_incomplete')
        if denominator == 0:
            reason.append('zero_denominator')
        availability = 'ready' if complete and not reason else 'unavailable'
        result = n if value is None else value
        if denominator is not None:
            result = n / denominator * 100 if denominator else None
        metrics[name] = dict(metric_id=name, availability=availability, value=result if availability == 'ready' else None,
                             numerator=n if complete else None, denominator=denominator, unit=unit,
                             cohort_label=name.replace('_', ' '), eligible_count=len(scope),
                             measured_count=(len(scope) if complete else 0) if measured is None else measured,
                             exclusion_counts={'already_done': sum(bool(r.get('already_done')) for r in scope)},
                             reason_codes=reason, time_basis='start / first entry / close or final removal',
                             evidence_ref=ref, input_revision_ids=[revision], calculation_version=VERSION)

    for name in ('planned', 'added', 'removed', 'completed', 'unfinished', 'unestimated', 'reopened', 'original_unfinished', 'original_removed'):
        metric(name, cohorts[name])
    metric('plan_completed', cohorts['plan_completed'], denominator=len(cohorts['planned']), unit='percent')
    metric('added_completed', cohorts['added_completed'], denominator=sum(r['origin'] == 'added' for r in eligible), unit='percent')
    denominator = len(cohorts['planned'])
    metric('unique_scope_change', cohorts['changed'], denominator=denominator, unit='percent')
    metric('gross_scope_movement', cohorts['changed'], value=(len(cohorts['added']) + len(cohorts['removed'])) / denominator * 100 if denominator else 0,
           unit='percent', reasons=[] if denominator else ['zero_denominator'])
    metric('addition_rate', cohorts['added'], denominator=denominator, unit='percent')
    metric('removal_rate', cohorts['removed'], denominator=denominator, unit='percent')
    metric('net_scope_growth', cohorts['changed'], value=(len(cohorts['added']) - len(cohorts['removed'])) / denominator * 100 if denominator else 0,
           unit='percent', reasons=[] if denominator else ['zero_denominator'])
    churn = [r for r in scope if r.get('membership_event_count', 0)]
    event_count = sum(r.get('membership_event_count', 0) for r in churn)
    metric('membership_churn', churn, value=event_count / denominator * 100 if denominator else 0, unit='percent', reasons=[] if denominator else ['zero_denominator'])
    metrics['membership_churn'].update(numerator=event_count, denominator=denominator, cohort_label='Membership events per original planned issue; events can repeat')
    known_original = [r for r in cohorts['planned'] if r.get('baseline_points') is not None]
    point_denominator = sum(r['baseline_points'] for r in known_original)
    point_numerator = sum(r['baseline_points'] for r in known_original if r['outcome'] == 'done')
    metric('plan_completed_points', cohorts['plan_completed'], value=point_numerator / point_denominator * 100 if point_denominator else 0,
           unit='percent', reasons=[] if point_denominator else ['zero_denominator'])
    metrics['plan_completed_points'].update(numerator=point_numerator if complete else None, denominator=point_denominator,
                                            eligible_count=len(cohorts['planned']), measured_count=len(known_original))
    if complete and point_denominator and len(known_original) != len(cohorts['planned']):
        metrics['plan_completed_points'].update(availability='partial', reason_codes=['known_estimate_subset_only'])
    for name, selected in [('planned_points', cohorts['planned']), ('delivered_points', cohorts['completed']), ('unfinished_points', cohorts['unfinished']), ('added_points', cohorts['added']), ('removed_points', cohorts['removed'])]:
        known = [r for r in selected if r.get('baseline_points') is not None]
        metric(name, known, value=sum(r['baseline_points'] for r in known), unit='story_points', measured=len(known))
        if complete and len(known) < len(selected):
            metrics[name].update(availability='partial', reason_codes=['missing_baseline_estimates'], cohort_label='Known baseline estimates only')
            if not known:
                metrics[name].update(availability='unavailable', value=None)
        metrics[name]['eligible_count'] = len(selected)
    durations = [r for r in cohorts['completed'] if r.get('cycle_days') is not None]
    metric('cycle_median', durations, value=median([r['cycle_days'] for r in durations]) if durations else 0, unit='elapsed_days', reasons=[] if durations else ['active_history_unavailable'], measured=len(durations))
    metric('cycle_p85', durations, value=sorted(r['cycle_days'] for r in durations)[math.ceil(.85 * len(durations))-1] if durations else 0,
           unit='elapsed_days', reasons=[] if len(durations) >= 10 else ['sample_below_10'], measured=len(durations))
    metrics['cycle_median']['eligible_count'] = len(cohorts['completed'])
    metrics['cycle_p85']['eligible_count'] = len(cohorts['completed'])
    if complete and durations and len(durations) < len(cohorts['completed']):
        for name in ('cycle_median', 'cycle_p85'):
            if metrics[name]['availability'] == 'ready':
                metrics[name].update(availability='partial', reason_codes=['partial_cycle_coverage'])
    ages = [r for r in cohorts['unfinished'] if r.get('closing_age_days') is not None]
    metric('closing_age', ages, value=median([r['closing_age_days'] for r in ages]) if ages else 0, unit='elapsed_days', reasons=[] if ages else ['active_history_unavailable'], measured=len(ages))
    metrics['closing_age']['eligible_count'] = len(cohorts['unfinished'])
    if complete and ages and len(ages) < len(cohorts['unfinished']):
        metrics['closing_age'].update(availability='partial', reason_codes=['not_started_or_missing_active_history'])
    blocked = [r for r in scope if r.get('blocked_days') is not None]
    metric('blocked_duration', [r for r in blocked if r['blocked_days'] > 0], value=sum(r['blocked_days'] for r in blocked), unit='elapsed_days',
           reasons=[] if len(blocked) == len(scope) and blocked else ['blocked_mapping_unavailable'])
    for name, reason in [('repeated_carryover', 'consecutive_sprint_evidence_required'), ('goal_linked_unfinished', 'goal_links_not_recorded'), ('accepted_stories', 'acceptance_not_recorded'), ('throughput_baseline', 'comparable_history_required'), ('capacity', 'capacity_not_recorded')]:
        metric(name, [], reasons=[reason])
    daily = {}
    daily_ready = complete and all(r.get('daily') is not None for r in scope)
    if daily_ready:
        for row in scope:
            for sample in row['daily']:
                combined = daily.setdefault(sample['date'], {'date': sample['date'], 'scope': 0, 'done': 0, 'wip': 0})
                for key in ('scope', 'done', 'wip'):
                    combined[key] = None if sample[key] is None or combined[key] is None else combined[key] + sample[key]
    return {'calculation_version': VERSION, 'metrics': metrics, 'evidence': evidence,
            'daily': {'availability': 'ready' if daily_ready and daily else 'unavailable', 'samples': sorted(daily.values(), key=lambda s: s['date']),
                      'time_basis': 'Board-local day end, clipped to actual close; eligible scope only'},
            'population_complete': complete, 'cohorts': {name: [str(r['issue_id']) for r in values] for name, values in cohorts.items()}}
