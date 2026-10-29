# 外部朝起動の準備（未配備）

2026-10-29: 朝再試行 run 40791057084 / 40796825168 は08:59 / 09:52 JSTに開始し、時間外として生成を見送った。これは生成成功ではない。スケジュールの欠落・遅延の内部原因は未確定。GitHubはscheduleの遅延・欠落があり得ると説明している。

## 準備した内容

external_morning_trigger.mjs は Cloudflare Workers の scheduled ハンドラー。候補cronは UTC `3,33 20,21 * * *`（JST 05:03 / 05:33 / 06:03 / 06:33）。未配備であり、このファイルをGitHubへ保存しただけでは動かない。HTTPの公開入口は404、送信先・ワークフロー・mainブランチは固定。10分超遅延したイベントと時間外は送信しない。API受理204は生成・公開の成功ではない。

## 接続前の停止条件

Cloudflareアカウント、料金条件、GitHub資格情報の新設・保管への承認が必要。勝手な登録・課金・権限追加は禁止。資格情報はチャットや公開リポジトリへ貼らない。

配備する場合はこのリポジトリだけを対象にした短い有効期限のfine-grained token（Actions write、その他の任意権限なし）をCloudflareの暗号化Secret `GITHUB_ACTIONS_TOKEN` に登録する。Actions writeは特定workflowの起動だけに権限を限定できないため、そのリスクを説明して承認を受ける。トークン作成・Secret登録・配備前に個別確認する。workers.devとpreview URLは無効化しCronだけで起動する。

## 再開手順

1. 利用者がCloudflareを使用するか決定し、料金と権限を確認する。
2. 承認後にSecretを登録して配備し、cronを設定（反映に時間がかかる場合あり）。実トークンを使ったテスト送信は朝の時間帯で実施。
3. dispatch受理→Actionsのworkflow_dispatch実行→当日immutable予想→Pages公開JSONの7時前観測を別々に確認する。
4. 外部cronもActions runnerもPagesも遅延し得る。7時までの公開を保証しない。既存監視を残し、時間外生成・後付けの成功記録はしない。
5. 通常のGitHub cronは予備として維持。問題時は外部cronを無効化しSecret/tokenを失効する。既存実績と予想履歴は削除しない。

テスト: `node --test test_external_morning_trigger.mjs`。すべてモック通信で、実GitHubには起動要求を送らない。

公式仕様:
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event
- https://developers.cloudflare.com/workers/configuration/cron-triggers/
- https://developers.cloudflare.com/workers/configuration/secrets/
