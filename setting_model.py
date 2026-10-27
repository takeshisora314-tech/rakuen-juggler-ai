"""Offline conditional model only: not a next-day forecast or calibrated setting probability."""
import math
from datetime import date
from collect_sources import model_for_number

VERSION = 'conditional-counts-v1'
DENOMINATORS = ((273.1,409.6),(270.8,385.5),(266.4,336.1),
                (254.0,290.0),(240.1,268.6),(229.1,229.1))
SOURCES = {'myj5':'https://www.kitadenshi.co.jp/slot/myjuggler5/',
           'myj6':'https://www.kitadenshi.co.jp/slot/myjuggler6/',
           'neoim':'https://www.kitadenshi.co.jp/slot/neoimjugglerex/',
           'gogo3':'https://www.kitadenshi.co.jp/slot/gogojuggler3/',
           'funky2':'https://www.kitadenshi.co.jp/slot/funkyjuggler2/',
           'girls':'https://www.kitadenshi.co.jp/slot/jugglergirlsss/',
           'mr':'https://www.kitadenshi.co.jp/slot/mrjuggler/',
           'happy8':'https://www.kitadenshi.co.jp/slot/happyjugglerv3/'}
MODEL_NAMES={'myj5':'マイジャグラーV','myj6':'マイジャグラーVI',
             'neoim':'ネオアイムジャグラーEX','gogo3':'ゴーゴージャグラー3',
             'funky2':'ファンキージャグラー2','girls':'ジャグラーガールズSS',
             'mr':'ミスタージャグラー','happy8':'ハッピージャグラーV Ⅲ'}
SPECS = {
    'myj5':DENOMINATORS,'myj6':DENOMINATORS,
    'neoim':((273.1,439.8),(269.7,399.6),(269.7,331.0),(259.0,315.1),(259.0,255.0),(255.0,255.0)),
    'gogo3':((259.0,354.2),(258.0,332.7),(257.0,306.2),(254.0,268.6),(247.3,247.3),(234.9,234.9)),
    'funky2':((266.4,439.8),(259.0,407.1),(256.0,366.1),(249.2,322.8),(240.1,299.3),(219.9,262.1)),
    'girls':((273.1,381.0),(270.8,350.5),(260.1,316.6),(250.1,281.3),(243.6,270.8),(226.0,252.1)),
    'mr':((268.6,374.5),(267.5,354.2),(260.1,331.0),(249.2,291.3),(240.9,257.0),(237.4,237.4)),
    'happy8':((273.1,397.2),(270.8,362.1),(263.2,332.7),(254.0,300.6),(239.2,273.1),(226.0,256.0)),
}
REQUIRED_CONTRACT = ('normal_game_trials', 'exclusive_bb_rb',
                     'completed_business_day', 'constant_setting_assumed',
                     'model_identity_confirmed')


def infer_day(record, config, prior, observation_contract=None):
    """An explicit prior and observation assumptions are mandatory.

    Contract flags are caller assertions, NOT independent verification of a source.
    Never pool several business days; never treat these masses as verified labels.
    """
    out = {'version':VERSION,'status':'unverified_observation_semantics',
           'purpose':'retrospective_conditional_inference', 'calibrated':False}
    if not observation_contract or any(observation_contract.get(k) is not True for k in REQUIRED_CONTRACT):
        return out
    if not isinstance(record,dict):
        return {**out,'status':'invalid_record'}
    try:
        day=date.fromisoformat(record['date']).isoformat()
        model=record['model_id']
        if model not in SOURCES:
            return {**out,'status':'unsupported_model'}
        if type(record.get('number')) is not int or model_for_number(config,day,record['number']) != model:
            return {**out,'status':'installation_mismatch'}
        if any(type(record.get(k)) is not int for k in ('games','bb','rb')):
            return {**out,'status':'invalid_record'}
        games,bb,rb=(record[k] for k in ('games','bb','rb'))
        if min(games,bb,rb)<0 or bb+rb>games:
            return {**out,'status':'invalid_record'}
    except (ValueError,KeyError,TypeError):
        return {**out,'status':'invalid_record'}
    if len(prior)!=6 or any(type(p) not in (int,float) or not math.isfinite(p) or p<0 for p in prior) or sum(prior)<=0:
        raise ValueError('Six finite nonnegative prior weights with positive sum required')
    if games<3000:
        return {**out,'status':'insufficient_games'}
    total=sum(prior)
    if not math.isfinite(total):
        raise ValueError('Prior weight sum must be finite')
    logs=[]
    for (bd,rd),weight in zip(SPECS[model],prior):
        # Multinomial coefficient cancels between settings. Combined bonus rate
        # and difference are NOT additional independent observations.
        value=(bb*math.log(1/bd)+rb*math.log(1/rd)
               +(games-bb-rb)*math.log1p(-1/bd-1/rd))
        logs.append(value+math.log(weight)-math.log(total) if weight else -math.inf)
    peak=max(logs)
    weights=[math.exp(value-peak) for value in logs]
    distribution=[w/sum(weights) for w in weights]
    return {**out,'status':'conditional_result','date':day,'model_id':model,
            'number':record['number'],'games':games,'bb':bb,'rb':rb,
            'spec_model_name':MODEL_NAMES[model],
            'source':SOURCES[model],'spec_checked_on':'2026-10-27',
            'prior':[p/total for p in prior],
            'conditional_setting_distribution':distribution,
            'conditional_mass_4_6':sum(distribution[3:]),
            'warning':'Depends on asserted game semantics, constant setting, rounded factory rates and prior; not verified setting accuracy or next-day probability.'}
