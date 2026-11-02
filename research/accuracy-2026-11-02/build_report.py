"""Render the frozen offline audit into a Japanese review document."""
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from datetime import date

B=Path(__file__).parent
r=json.loads((B/'prediction-accuracy-review-2026-11-02.json').read_text())
p=json.loads((B/'provenance.json').read_text())
lines=[]
def add(s=''): lines.append(s)
def table(headers,rows):
    add();add('| '+' | '.join(headers)+' |');add('| '+' | '.join(['---']*len(headers))+' |')
    for row in rows:add('| '+' | '.join(str(x) for x in row)+' |')
    add()
def pct(v):return f'{v*100:.1f}%'
def coins(v):return f'{v:+,.0f}'
names={'myj5':'マイジャグ5','myj6':'マイジャグ6'}
methods={'current':'現行','bb_small':'BBを10%追加','dip_moderate':'凹み30%・BB15%','history_90':'BB/REGを過去90日集計','previous_day':'BB/REGを前日中心'}

add('# ジャグラーAI 予想精度検証 — 2026年11月2日')
add('\n結論：11月1日の上位6台は全39台平均を上回った。ただし、改善候補の安定した優位性は確認できず、本番の予想ルールは維持する。予想・保存・答え合わせ・自動運転のコードやデータは変更していない。今回の結果は研究用ブランチに保存する。')
add('\n## 1. 朝予想との照合と入力の時点')
add(f"\n11月1日05:03:43 JST作成の保存予想（コミット `{p['morning_commit']}`）を、そのコミットのデータ・設定・コードで再計算した。全8機種の保存モデル出力が完全一致し、対象6台の順位・点数も一致した。朝の入力の最新日は10月31日。11月1日の実績は選定理由の再計算に使用していない。保存ハッシュも検証した。公開サイトでユーザーが閲覧できた時刻までは、この照合だけでは証明しない。")
rows=[]
for m,v in r['case']['models'].items():
    for x in v['reasons']:
        a=x['actual'];rows.append([names[m],x['rank'],a['number'],f"{a['games']:,}",a['bb'],a['rb'],coins(a['difference']),x['saved_prediction']['score']])
table(['機種','朝順位','台番','G','BB','RB','保存実績の差枚','予想点'],rows)
add('G・BB・RBは提供された6台分とすべて一致した。表の差枚は保存済みのみんレポ由来データで、D-Deltaグラフからの概算とは区別する。差枚を実測の真値として新たに確認したものではない。保存済み朝予想3日分について、初回保存コミットのファイルと今回監査したファイルが同一であることも確認した。コミット時刻とSHAは provenance.json に記録。')
add('\n## 2. 6台が選ばれた理由')
add('\n現行順位は固定ルールの実験的な優先点。直近14暦日のうち最新7報告日を使い、台ごとに3,000G以上の日が3回以上・合計12,000G以上などを満たす台が対象。凹み45点・REG35点・回転数の裏付け20点で評価する。BBと曜日は現行点数に入っていない。90日分を保存していても、現行の順位に90日全体を直接使っているわけではない。')
add('\n凹み点は直近3回の有効日の差枚合計が−4,000枚で上限45点。連続3暦日とは限らない。REG点は機種全体のREG率へ5,000G分を加えて縮約し、平均との差を評価する。裏付け点は合計30,000Gで20点上限。6台とも裏付け点が満点で、今回の順位差には寄与していない。')
rows=[]
for m,v in r['case']['models'].items():
    for x in v['reasons']:
        f=x['features'];c=f['current_points']
        rows.append([names[m],x['actual']['number'],f['history_days'],f"{f['history_games']:,}",f"1/{f['history_games']/f['history_rb']:.1f}",coins(f['three_day_difference']),f"{c['dip']:.2f}",f"{c['rb']:.2f}",f"{c['support']:.2f}"])
table(['機種','台番','有効日数','過去G','過去REG','直近3回差枚','凹み点','REG点','裏付け点'],rows)
add('2223・2237は大きな凹み、2234は6台中で高いREG評価が支えた。2202は凹みとREGの両方、2206はREG評価が弱くても大きな凹みで上位になった。2219は凹み23.43点＋REG9.28点＋裏付け20点＝52.71点で3位になった。凹んだ台の翌日が有利になる因果関係は、この式だけでは証明されていない。')
add('\n2219の最終差枚−509枚と、本人の実戦収支−21,000円は別の指標。日次のG・BB・RB・最終差枚だけでは、着席時刻、途中の下振れ、投資額、交換、離席後の挙動を復元できない。選ばれた理由は特定できたが、実戦で負けた経路までは特定できない。予想点はプラス確率や設定4〜6確率ではない。')
add('\n## 3. 上位6台と全39台の比較')
rows=[]
for m,v in r['case']['models'].items():
    for label,key in [('上位3台','top3'),('全台','all_installed'),('上位3台を除く','unselected')]:
        x=v[key];rows.append([names[m],label,x['count'],f"{x['positive']}/{x['count']}",pct(x['positive_rate']),coins(x['mean_difference'])])
for label,key in [('上位6台','combined_selected'),('全39台','combined_all39')]:
    x=r['case'][key];rows.append(['両機種',label,x['count'],f"{x['positive']}/{x['count']}",pct(x['positive_rate']),coins(x['mean_difference'])])
table(['機種','対象','台数','プラス台数','プラス率','平均差枚'],rows)
add('全体平均との差は上位6台で＋1,013枚/台。マイジャグ5は平均差枚・プラス率の両方で全台を上回った。マイジャグ6は平均差枚で上回った一方、プラス率は全20台の70%を下回った。11月1日は店側全体も強く、5/6という成績だけでは選別の有効性を判断できない。')
add('\n参考として、同じ日の機種別全台から各3台を無作為に選ぶ1,104,660通りのうち、今回以上の合計差枚になる割合は約3.58%。これは当日結果を固定した比較であり、将来の勝率や継続的優位性を示す検定ではない。')
add('\n## 4. 保存済み朝予想の順位別成績')
add('\n完成済み実績と照合できた保存日はマイジャグ5が10/27・10/31・11/1の3日、マイジャグ6が10/31・11/1の2日。11/2は集計対象外。10/27の保存は04:48 JSTで、現在の朝5時枠より前だが開店前の予想として別記して含めた。未保存日の順位を後から作った結果は、ここには混ぜない。')
rows=[]
for m,v in r['saved_morning_predictions']['models'].items():
    for rank,x in v['by_rank'].items():
        ref=x['conditional_setting_reference'];eq=ref['equal'];lo=ref['low_heavy'];hi=ref['high_heavy']
        rows.append([names[m],rank,x['count'],pct(x['positive_rate']),coins(x['mean_difference']),pct(eq['share_mass_at_least_half']),f"{pct(lo['share_mass_at_least_half'])}〜{pct(hi['share_mass_at_least_half'])}"])
table(['機種','予想順位','標本数','プラス率','平均差枚','4〜6相当判定率・等事前','低/高寄り事前の感度'],rows)
add('10/27の保存ファイルには上位3台だけが残り、4位以降の保存順位はない。したがって4位以下は保存のある日だけを分母にした。台の適格条件によっても順位ごとの分母は変わる。')
add('\n「4〜6相当判定率」は、当日BB/RBの条件付きモデルで設定4〜6の質量が50%以上になる台の割合。通常G、BB/RBの排他性、終日同一設定などを仮定する参考計算で、実際の設定の正解率ではない。等事前は設定1〜6を同じ重みにし、低寄り=[60,20,10,5,3,2]%・高寄り=[5,5,10,20,30,30]%でも比較した。表の感度はこの2仮定の結果であり信頼区間ではない。生の平均質量もJSONに保存。通常Gという利用者確認はあるが、全期間の観測条件を独立検証したわけではない。')
add('\n標本は各順位2〜3台だけなので、順位間の優劣を断定できない。とくに2219を理由に3位全体を下げる根拠はない。ぶどう逆算、合成確率、差枚をBB/RBとは別の独立証拠として重ねて設定推定する処理はしていない。')
add('\n## 5. 過去データで現行と改善候補を比較')
add('\n保存済み予想とは別に、過去日を順に再計算した。対象日の前日以前の行のみで特徴量を作り、全設置台の実績が揃う日だけを採用。同じ日・同じ候補台で各方式の上位3台を比較した。データは8/4〜11/1の90日保存枠だが、評価可能日はマイジャグ5が8/7〜11/1の86日、マイジャグ6は10/30〜11/1の3日しかない。過去90日候補は取得範囲内で増える履歴を使うため、初期日には90日分の学習履歴がない。')
add('\nこれは現時点の保存実績と設置履歴からの再現で、当時の朝に公開済みだったことまで確認できない。修正済みデータや設置情報を後から知る影響も完全には除外できず、実際に保存された朝予想と同じ証拠の強さにはならない。')
add('\n候補は現行、BBを10%追加（凹み45/REG25/BB10/裏付け20）、凹みを30%へ下げBBを15%追加（30/35/15/20）、BB/REGを過去90日へ変更、BB/REGを前日中心へ変更の5方式。前日中心候補は直近報告日の率を機種プールへ縮約する。ぶどうは全候補で不使用。')
rows=[]
for m in names:
    a=r['historical_comparison']['summaries'][m]['all']
    for key,v in a['methods'].items():rows.append([names[m],methods[key],a['days'],coins(v['mean_difference']),pct(v['positive_rate']),coins(v['mean_lift_vs_installed'])])
table(['機種','方式','日数','上位3台平均差枚','プラス率','全台平均との差'],rows)
add('全期間では凹み30%候補の平均差枚が少し高いが、マイジャグ5のプラス率は現行より低い。マイジャグ6では凹みを下げると平均差枚が悪化した。機種横断で改善したとは言えない。')
add('\n比較用の時系列区分として10/3より前を開発区分、10/3〜10/31を後半区分とし、11/1は別枠にした。以前の探索で見た可能性のあるデータなので、完全な未使用ホールドアウトとは呼ばない。')
rows=[]
v=r['historical_comparison']['summaries']['myj5']['validation']
for key,x in v['methods'].items():
    ci=x['paired_day_bootstrap_95'];rows.append([methods[key],v['days'],coins(x['mean_difference']),pct(x['positive_rate']),coins(x['mean_daily_gain_vs_current']),f"{coins(ci[0])}〜{coins(ci[1])}"])
table(['マイジャグ5・後半区分','日数','平均差枚','プラス率','現行との差','差の参考95%区間'],rows)
add('後半区分では凹み30%候補が現行比＋120枚/台だが、参考区間は−176〜＋442枚で悪化も否定できない。BB10%追加も＋23枚程度で区間が0をまたぐ。90日集計と前日中心は後半で改善していない。区間は対応する日を3,000回再標本化したもの。日を跨ぐ依存・複数比較・候補探索の偏りを解決しないため、採用根拠には不足する。')
add('\nマイジャグ6の後半区分は2日だけ。11/1単日なら凹み30%候補は2219を外して平均＋478枚良くなるが、11/1を除く2日では現行比−880枚。今回の2219だけに合わせた変更が危うい具体例になっている。')
add('\n### 曜日の確認')
rows=[]
for m in names:
    daily=[x for x in r['historical_comparison']['daily'] if x['model_id']==m]
    for wd,label in enumerate(['月','火','水','木','金','土','日']):
        v=[x for x in daily if date.fromisoformat(x['date']).weekday()==wd]
        if v:rows.append([names[m],label,len(v),coins(mean(x['methods']['current']['mean_difference'] for x in v)),pct(mean(x['methods']['current']['positive_rate'] for x in v)),coins(mean(x['methods']['current']['lift'] for x in v))])
table(['機種','曜日','日数','現行上位3台平均差枚','プラス率','全台平均との差'],rows)
add('曜日の数字は事後の記述集計。特定日・祝日・入替・店全体の強弱と交絡する。マイジャグ6は各曜日0〜1日で検証不可。曜日別の重みをこの表から後付けで最適化していない。今後試すなら、過去だけで店全体の曜日基準値を作り、サンプルの少ない曜日を全体へ縮約し、未来日に固定して比較する必要がある。')
add('\n## 6. 保存したものと次の判断')
add(f"\n現行コードは `{p['baseline_commit']}` に固定し、研究フォルダにもコピーした。11/1朝コードと保存予想、入力ハッシュ、候補定義、日別比較、順位別の全結果、検証スクリプトを保存した。元データは2つの固定コミットから再取得でき、取得後にSHA256を確認する。")
add('\n本番変更は見送る。期待改善の観測値は上表のとおりで、客観的に確立した効果はまだない。候補の配点を固定したまま今後の朝予想と並行比較し、少なくとも30日程度の未使用日を蓄積してから、平均差枚・プラス率・全台平均との差・機種別の悪化を再確認するのが次の段階。30日は運用上の最低目安で、統計的に十分な日数を保証しない。現時点では比較の自動実行や本番昇格処理は追加していない。')
add('\nデータ不足、設定の正解ラベル不在、朝の公開状況不明という限界が残るため、「設定を当てる精度」「実戦収支」「未来のプラス率」を今回の数字から確定扱いしない。')
add('\n## 付録：11月1日の全39台')
for m,v in r['case']['models'].items():
    add(f'\n### {names[m]}')
    table(['朝予想順位','台番','G','BB','RB','保存実績差枚'],[[x['rank'],x['number'],x['actual']['games'],x['actual']['bb'],x['actual']['rb'],coins(x['actual']['difference'])] for x in v['all39_detail']])
add('\n## 再現方法')
add('\n研究フォルダで `forecast_engine.py`・`morning_forecast_engine.py`・`collect_sources.py`・`setting_model.py`・`machines.json` と履歴JSONを固定コピーとして保持。`requests` が利用可能なPythonで実行する。')
add('\n```sh\npython prepare_inputs.py\npython -m unittest test_accuracy_audit -v\npython analyze_prediction_accuracy.py\npython build_report.py\n```')
add('\nテスト3件は、全8機種の朝モデル再現・6台の提供値一致・全39台の母数確認、当日以降の値を改変しても全候補の特徴量と順位が不変、未完成日の除外を確認した。研究ファイルのみなので、本番のフロントエンドや収集処理は変更・再実行していない。')
(B/'REPORT.md').write_text('\n'.join(lines)+'\n')
