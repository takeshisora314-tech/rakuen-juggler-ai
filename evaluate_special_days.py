"""Compare My Juggler VI results by JST business-date category."""
import json
from datetime import date
from pathlib import Path
from statistics import mean

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


if __name__ == '__main__':
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
