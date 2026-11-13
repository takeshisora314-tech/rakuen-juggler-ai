"""Compare My Juggler VI results by JST business-date category."""
import json
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

from collect_sources import layout_on
from forecast_engine import valid_record

BASE = Path(__file__).resolve().parent
CATEGORIES = ('通常日', '特日全体', '本ゾロ', 'ゾロ目', '5のつく日')


def special_days(day):
    return tuple(label for label, applies in (
        ('本ゾロ', day.month == day.day),
        ('ゾロ目', day.day in (11, 22)),
        ('5のつく日', day.day in (5, 15, 25)),
    ) if applies)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def metrics(samples):
    if not samples:
        return {'count': 0}
    return {'count': len(samples), 'positive_rate': mean(value > 0 for value, _ in samples),
            'mean_difference': mean(value for value, _ in samples),
            'lift_vs_all': mean(value - average for value, average in samples)}


def evaluate(base=BASE):
    history = base / 'history'
    periods = {'20台': {}, '39台': {}}
    excluded = []
    for path in sorted((history / 'machines').glob('*/myj6.json')):
        day = date.fromisoformat(path.parent.name)
        size = 39 if day >= date(2026, 11, 11) else 20
        rows = read(path)
        actual = {row['number']: row['difference'] for row in rows if valid_record(row)}
        if len(rows) != size or set(actual) != set(range(2201, 2201 + size)):
            excluded.append(str(day))
            continue
        average = mean(actual.values())
        evaluation_path = history / 'evaluations' / (str(day) + '.json')
        ranked = []
        if evaluation_path.exists():
            evaluation = read(evaluation_path)
            model = evaluation.get('models', {}).get('myj6', {})
            if evaluation.get('kind') == 'prospective' and model.get('status') == 'complete':
                ranked = [(row['rank'], actual[row['number']]) for row in model.get('prediction_results', [])
                          if 1 <= row['rank'] <= 10 and row['number'] in actual]
        periods[f'{size}台'][str(day)] = (special_days(day), average, ranked)
    summary = {}
    for period, days in periods.items():
        summary[period] = {}
        for category in CATEGORIES:
            selected = [(day, average, ranked) for day, (labels, average, ranked) in days.items()
                        if category in labels or (category == '特日全体' and labels)
                        or (category == '通常日' and not labels)]
            samples = [(rank, value, average) for _, average, ranked in selected for rank, value in ranked]
            summary[period][category] = {
                'dates': [day for day, _, _ in selected],
                'all_machine_mean': mean(average for _, average, _ in selected) if selected else None,
                'top3': metrics([(v, a) for r, v, a in samples if r <= 3]),
                'by_rank': {rank: metrics([(v, a) for r, v, a in samples if r == rank])
                            for rank in range(1, 11)},
            }
    return {'periods': summary, 'excluded_incomplete': excluded}


def evaluate_store_window(base, end):
    """Compare exact dated layouts over 90 calendar days, ending on end."""
    start = end - timedelta(days=89)
    config = read(base / 'machines.json')
    tables = {}
    groups = {}
    for offset in range(90):
        day = start + timedelta(days=offset)
        for model in layout_on(config, day):
            model_id = model['model_id']
            if model_id not in ('myj5', 'myj6'):
                continue
            key = f"{model_id} / {len(model['numbers'])}台"
            group = groups.setdefault(key, {'days': {}, 'excluded': []})
            path = base / 'history' / 'machines' / str(day) / (model_id + '.json')
            rows = read(path) if path.exists() else []
            actual = {row['number']: row for row in rows if valid_record(row)
                      and row['date'] == str(day) and row['model_id'] == model_id}
            if len(rows) != len(model['numbers']) or set(actual) != set(model['numbers']):
                group['excluded'].append(str(day))
                continue
            tables[day, model_id] = actual
            average = mean(row['difference'] for row in actual.values())
            previous = tables.get((day - timedelta(days=1), model_id), {})
            samples = {'low_play_loss': [], 'previous_plus_2000': []}
            for number, row in previous.items():
                if number not in actual:
                    continue
                result = (actual[number]['difference'], average)
                if 0 < row['games'] <= 1000 and row['difference'] < 0:
                    samples['low_play_loss'].append(result)
                if row['difference'] >= 2000:
                    samples['previous_plus_2000'].append(result)
            group['days'][day] = (average, samples)
    report = {}
    for key, group in groups.items():
        summary = {}
        for category in CATEGORIES:
            chosen = [(day, average, samples) for day, (average, samples) in group['days'].items()
                      if category in special_days(day)
                      or (category == '特日全体' and special_days(day))
                      or (category == '通常日' and not special_days(day))]
            summary[category] = {
                'days': [str(day) for day, _, _ in chosen],
                'all_machine_mean': mean(average for _, average, _ in chosen) if chosen else None,
                **{name: metrics([item for _, _, samples in chosen for item in samples[name]])
                   for name in ('low_play_loss', 'previous_plus_2000')},
            }
        report[key] = {'categories': summary, 'excluded': group['excluded']}
    return {'start': str(start), 'end': str(end), 'layouts': report}


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--end', type=date.fromisoformat,
                        help='Run the 90-day store analysis through this JST date')
    args = parser.parse_args()
    result = evaluate_store_window(BASE, args.end) if args.end else evaluate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
