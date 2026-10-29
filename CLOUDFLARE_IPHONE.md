# iPhoneからGitHub連携で朝起動を配備する（未接続）

## 2026-10-29の進捗

- iPhone SafariのCloudflareエディターではコードの削除はできたが貼り付けできなかった。空のコードはDeployしない。
- アカウントとHello World Worker `deploy` は利用者が作成済み。こちらのクラウドブラウザーではCloudflareログインに失敗しており、再試行していない。
- リポジトリの `wrangler.jsonc` は既存Worker名 `deploy` と、テスト済みの `external_morning_trigger.mjs` を指定する。公開HTTP URL・プレビューURLは無効。
- **GitHub連携、Cloudflareへの新コード配備、Secret登録、Cron有効化、実朝の公開確認は未完了。** ファイル追加だけで自動起動済みとはしない。
- 既存のアプリ画面・実績・予想履歴・GitHub cronには変更しない。

## 操作手順（長いコードの貼り付け不要）

1. エディター左上の `deploy` でWorker概要へ戻る。未配備の空コードを保存・Deployしない。破棄確認があれば、このHello World編集だけを破棄する。
2. `Settings` → `Builds` → `Connect`。GitHub連携の権限画面では止まり、表示された権限を確認する。GitHub Appの新規インストール・権限付与は利用者の確認後に行う。選択可能なら `Only select repositories` で `takeshisora314-tech/rakuen-juggler-ai` のみに絞る。
3. Worker名 `deploy`、リポジトリ上記、Production branch `main`、Root directory リポジトリ直下、Build command 空欄、Deploy command `npx wrangler deploy`。自動検出によるアプリ全体の移行やフレームワーク変換はしない。料金・生成されるCloudflare API tokenの権限も確認し、未承認の課金や権限追加はしない。
4. Build watch paths の Include は `external_morning_trigger.mjs, wrangler.jsonc` に限定し、実績のコミットごとにWorkerを再配備しない。設定画面の内容に応じて確認してから保存する。
5. 配備ログで成功を確認する。公開URLが無効なので、Visitが開けないことだけで配備失敗とは判断しない。まだCronは有効にしない。
6. **資格情報の作成・保管の前に確認する。** このrepo限定・短期有効期限のfine-grained GitHub tokenのActions writeは、単一workflow起動だけに限定できない。CloudflareがこのrepoのActionsを操作できるリスクを説明し、承認後に利用者が作成し、暗号化Secret `GITHUB_ACTIONS_TOKEN` に直接登録する。トークンをチャット・公開コード・スクリーンショットへ出さない。Build変数ではなくWorker runtime Secretに登録する。
7. 承認後にこちらで `wrangler.jsonc` に `"triggers":{"crons":["3,33 20,21 * * *"]}` を追加して配備する。UTC指定、JST 05:03/05:33/06:03/06:33。Wrangler配備後はCronを設定ファイルで管理し、dashboardだけの変更との競合を避ける。現在の設定ではtriggersを省略し、既存Cronを削除しない。
8. 翌朝のdispatch受理、GitHub Actions実行、当日の固定予想、7時前の公開先観測をそれぞれ確認する。朝以外の手動テストが時間外で見送られるのは仕様。未確認を成功に置き換えない。

## 次の手順と停止条件

次は利用者のiPhoneで `deploy` のSettingsを開き、Buildsの接続項目を確認する。新規GitHub権限付与の直前に確認が必要。接続画面が違う場合はスクリーンショットにある項目で案内し、存在しないボタンを推測しない。

7時公開はCloudflare・GitHub Actions・Pagesの遅延に影響され、保証しない。朝の時間制限・固定予想・公開監視は維持する。解除時はGit連携を切り、外部Cron停止・Secret/token失効を行う。実績・予想履歴は削除しない。

テスト: `node --test test_external_morning_trigger.mjs`（モックのみ、実dispatchなし）。

公式資料:
- https://developers.cloudflare.com/workers/ci-cd/builds/
- https://developers.cloudflare.com/workers/ci-cd/builds/build-watch-paths/
- https://developers.cloudflare.com/workers/configuration/cron-triggers/
- https://developers.cloudflare.com/workers/configuration/secrets/
