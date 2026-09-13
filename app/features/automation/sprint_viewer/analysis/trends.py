from statistics import median


def comparable_summary(selected, previous):
    """Input list contains only authorized, comparable, preceding sprint revisions."""
    previous = previous[:7]
    throughputs = [p['completed'] for p in previous if p.get('completed') is not None]
    ratios = [p['plan_completed'] for p in previous if p.get('plan_completed') is not None]
    return {'availability': 'ready' if throughputs else 'unavailable', 'sample_size': len(throughputs),
            'throughput_median': median(throughputs) if throughputs else None,
            'throughput_range': [min(throughputs), max(throughputs)] if throughputs else None,
            'throughput_mad': median(abs(v - median(throughputs)) for v in throughputs) if throughputs else None,
            'plan_completion_median': median(ratios) if ratios else None,
            'selected': selected, 'previous': previous,
            'note': 'Baseline excludes the selected sprint. Current/prior-year catalogue range may shorten the baseline.'}
