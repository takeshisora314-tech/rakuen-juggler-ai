# 設定推定の根拠確認（2026-10-31）

## 確認できたこと

setting_model.py の8機種×6設定×BB/RB（96項目）は、北電子公式確率表と照合して一致。
確率表は工場データから算出した予測値であり、設定ラベルや店舗配分の根拠ではない。

| 内部ID | 公式製品ページ |
| --- | --- |
| myj5 | https://www.kitadenshi.co.jp/slot/myjuggler5/ |
| myj6 | https://www.kitadenshi.co.jp/slot/myjuggler6/ |
| neoim | https://www.kitadenshi.co.jp/slot/neoimjugglerex/ |
| gogo3 | https://www.kitadenshi.co.jp/slot/gogojuggler3/ |
| funky2 | https://www.kitadenshi.co.jp/slot/funkyjuggler2/ |
| girls | https://www.kitadenshi.co.jp/slot/jugglergirlsss/ |
| mr | https://www.kitadenshi.co.jp/slot/mrjuggler/ |
| happy8 | https://www.kitadenshi.co.jp/slot/happyjugglerv3/ |

マイジャグラーV/VIは同じ確率表。実績の機種履歴は引き続き分離する。
内部ID happy8 に対応している公式名は「ハッピージャグラーV Ⅲ」。
内部IDの綴りだけを実機型式の証明に用いない。

## 未確認の観測条件

みんレポ https://min-repo.com/about/ は平均G数の条件や引用元へのリンク掲載を説明しているが、
閲覧した説明では、G数がボーナス中ゲームを含むか、通常ゲームの試行数かは確認できなかった。
公式サイト内検索でも該当説明は見つからなかった。説明が存在しないと断定はしない。

公式問い合わせ先は https://min-repo.com/contact/ 。
ホール調査・特定日・旧イベント日変更を案内する窓口で、
質問への個別返信ができない場合があると記載されている。
送信はしていない。

確認すべき事項:
- 楽園上新屋店のジャグラー台別G数は通常ゲームのみか、ボーナス中を含むか。
- BB/RB回数とG数が同じ営業日・同じ集計範囲を指すか。
- G数の定義が店舗・取得元・日付により変わるか。
- 終日確定値と途中更新値を区別する方法。

他サイトとのG数一致や G÷BB の一致だけでは、通常ゲーム数であることの証明にならない。
ボーナス中G数を固定値で推測して差し引かない。

## 公開判断

未確認の observation_contract を true にせず、設定確率の公開は保留。
機種同定・観測条件を確認できても、実設定の正解データや店舗配分の検証は別に必要。
単日実績からの条件付き推定と、翌日設定4〜6予想は異なる。
既存ランキング点数を設定確率へ読み替えない。
今回の調査で本番データ・推定コード・予想方式は変更していない。

## 別途完了した候補台数の修正

コミット 971273c7a5c961bbd480a316824f877233d09cd2 で、
稼働条件を満たす台が1〜2台でも候補を生成するよう修正。
関連56テストと画面46項目、1〜2台表示を確認。
保存済み実績による隔離模擬実行では8機種生成を確認。
模擬実績で夜の待機→翌朝の8機種照合完了を確認し、本番ファイル不変を検証。
模擬検証は実運転の成功や設定精度を示さない。
