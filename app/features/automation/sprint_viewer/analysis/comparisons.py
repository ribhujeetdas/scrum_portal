import hashlib
import json


def apply_comparisons(data, comparison):
    previous = comparison['previous']
    if comparison['sample_size']:
        data['metrics']['throughput_baseline'].update(value=comparison['throughput_median'], availability='ready',
            numerator=None, denominator=None, measured_count=comparison['sample_size'], eligible_count=len(previous),
            time_basis='Preceding comparable closed sprints, excluding selected sprint', reason_codes=[], evidence_ref=None,
            input_revision_ids=[p['revision'] for p in previous])
    if not data['population_complete']:
        return
    if comparison.get('consecutive_prior_verified'):
        prior = previous[0]
        ids = sorted(set(data['cohorts']['unfinished']) & set(prior.get('unfinished_ids', [])))
        ref = hashlib.sha256(json.dumps([data['revision'], prior['revision'], 'carryover', ids]).encode()).hexdigest()
        data['evidence'][ref] = ids
        data['metrics']['repeated_carryover'].update(value=len(ids), availability='ready', numerator=len(ids),
            measured_count=len(data['cohorts']['unfinished']), reason_codes=[], evidence_ref=ref,
            input_revision_ids=[data['revision'], prior['revision']], time_basis='Unfinished at selected and immediately preceding comparable close')
        rule = next((s for s in data['suggestions'] if s['rule_id'] == 'SV-03'), None)
        if rule:
            rule.update(id=ref, status='matched' if ids else 'not_matched', reason_codes=[], evidence_issue_ids=ids, count=len(ids),
                        coverage={'checked':len(data['cohorts']['unfinished']),'eligible':len(data['cohorts']['unfinished'])}, threshold=2)
    rule = next((s for s in data['suggestions'] if s['rule_id'] == 'SV-10'), None)
    if rule and comparison['sample_size'] >= 5:
        value = data['metrics']['completed']['value']
        low, high = comparison['throughput_range']
        matched = value < low or value > high
        ids = data['cohorts']['completed'] if matched else []
        rule.update(status='matched' if matched else 'not_matched', reason_codes=[], evidence_issue_ids=ids, count=len(ids),
                    facts={'selected_completed':value,'preceding_range':[low,high],'sample_size':comparison['sample_size']},
                    id=hashlib.sha256(json.dumps([data['revision'],[p['revision'] for p in previous],value,low,high]).encode()).hexdigest(),
                    threshold=[low,high], coverage={'checked':comparison['sample_size'],'eligible':len(previous)},
                    time_basis='Selected close compared with preceding comparable sprint closes')
