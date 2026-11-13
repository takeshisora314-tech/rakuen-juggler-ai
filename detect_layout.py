"""Confirm dated changes using successfully parsed public machine tables."""
import json
from datetime import timedelta

from collect_sources import layout_on, write_json


def confirm_layout(base, config, day, report, observed):
    active = {model['model_id']: set(model['numbers']) for model in layout_on(config, day)}
    if set(observed) != set(active):
        return {}
    numbers = {model: {row['number'] for row in rows} for model, rows in observed.items()}
    if any(not group for group in numbers.values()):
        return {}
    all_numbers = [number for group in numbers.values() for number in group]
    if len(all_numbers) != len(set(all_numbers)):
        return {}

    day_key = day.isoformat()
    root = base / 'history' / 'layout-observations'
    path = root / (day_key + '.json')
    previous_day = (day - timedelta(days=1)).isoformat()
    previous_path = root / (previous_day + '.json')
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    evidence = {'date': day_key, 'report_url': report,
                'models': {model: sorted(group) for model, group in numbers.items()}}
    if not path.exists() or json.loads(path.read_text()) != evidence:
        write_json(path, evidence)

    changes = {model: evidence['models'][model] for model in active if active[model] != numbers[model]}
    if not changes:
        return {}
    old_owners = {n: m for m, group in active.items() for n in group}
    new_owners = {n: m for m, group in numbers.items() for n in group}
    changed_numbers = {n for n in old_owners.keys() | new_owners.keys()
                       if old_owners.get(n) != new_owners.get(n)}
    all_transfers = all(n in old_owners and n in new_owners for n in changed_numbers)
    repeated = all(previous.get('models', {}).get(m) == group for m, group in changes.items())
    if not (all_transfers or repeated):
        return {}

    # Only extend the latest open layout. Historical or future manual periods win.
    models = [model for model in config['models'] if model['id'] in changes]
    if any(model['installations'][-1]['until'] is not None
           or (model['installations'][-1]['from'] or '') >= day_key for model in models):
        return {}
    for model in models:
        periods = model['installations']
        periods[-1]['until'] = day_key
        periods.append({'from': day_key, 'until': None, 'numbers': changes[model['id']]})
    layout_on(config, day)
    write_json(base / 'machines.json', config)
    write_json(root / 'changes' / (day_key + '.json'),
               {**evidence, 'changed_models': sorted(changes),
                'confirmation': 'transfer' if all_transfers else 'consecutive_reports',
                'previous_report_date': previous_day if repeated else None})
    return changes
