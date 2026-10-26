# 楽園上新屋 ジャグラーAI

iPhone向けGitHub Pages用。機種別台割、公開実績と取得状況を表示します。
**設定推定、予想ランキング、答え合わせは未実装です。**

## 台別実績

`python collect_machines.py`は標準のPlaywright Chromiumでみんレポの楽園上新屋店を開き、最新の前日以前の営業日について回転数・BB・RB・差枚を取得します。公開表の列、台数、台番、日付、店舗を検査し、一致する機種だけ保存します。サイトの認証・アクセス制限は回避しません。

- `history/machines/YYYY-MM-DD/機種ID.json`：営業日別の実績。既存値を欠損で消しません。
- `data.json`の`machine_records`：直近90日分。古い履歴ファイルは削除しません。
- `machine_collection`：今回の試行日時、対象日、機種別の取得・未取得状況。失敗しても過去の取得値は残します。

画面は選択日以前の最新取得日を機種単位で表示します。日付と出典リンクを各台に明示し、未取得を0や予測値で補いません。みんレポの独自集計値は参考値であり、公式実績や勝利保証ではありません。取得の成否はActionsの緑色だけでなく`machine_collection`で確認してください。

## 2026年10月27日の台割変更

日本時間で切り替えます。`machines.json`を画面と収集処理で共用しています。

| 日付 | マイジャグラーV | マイジャグラーVI |
| --- | --- | --- |
| 2026/10/26まで | 2201〜2239（39台） | 未導入 |
| 2026/10/27から | 2221〜2239（19台） | 2201〜2220（20台） |

設置期間の`from`は当日を含み、`until`は当日を含みません。
履歴は日付・機種ID・台番で区別し、旧5の同じ台番を6の実績に付け替えません。
残る6機種の台番は変更していません。画面の日付を切り替えて台割を確認できます。
VIの設定別確率は[北電子公式](https://www.kitadenshi.co.jp/slot/myjuggler6/)を出典とする参考値です。予測計算にはまだ使用していません。

## 自動保存

実行対象は`.github/workflows/collect-test.yml`です。毎日20:00 UTC（翌日05:00 JST）と手動実行に対応します。GitHubの都合で実行が遅れる場合があります。

`python collect_sources.py`は次を保存します。

- `data.json`：最新の接続確認結果と、実行日の日本時間で有効な台割。既存の他のキーは維持します。
- `history/source-checks/YYYY-MM-DD/時刻.json`：実行ごとの接続確認結果。過去のスナップショットは上書きしません。

この履歴は**接続確認の履歴**であり、台別実績の履歴ではありません。
HTTP 200は台別の数値を取得できたことを意味しません。取得不可やタイムアウトを記録し、架空のデータで補いません。
収集ジョブだけに`contents: write`を付け、`data.json`と`history`のみをコミットします。

## テスト

`python -m pip install -r requirements.txt`と`python -m playwright install --with-deps chromium`のあと、`python -m unittest discover -s tests -v`および`python -m unittest test_machine_collector -v`。
日付境界、20台/19台への切替、履歴の機種区別、既存データ保持、取得失敗を確認します。テストでは外部サイトに接続しません。
