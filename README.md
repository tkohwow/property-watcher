# Property Watcher

気になる中古マンション等の物件URLを定期監視し、掲載終了・価格変更・タイトル変更・本文変化をSQLiteに保存し、Gmailへ通知する自分用Botです。

## 構成

- Python
- SQLite
- GitHub Actions
- Gmail SMTP

## 使い方

### 1. リポジトリを作る

GitHubで空のprivate repositoryを作り、このフォルダの中身をpushします。

```bash
git init
git add .
git commit -m "initial property watcher"
git branch -M main
git remote add origin git@github.com:YOUR_NAME/property-watcher.git
git push -u origin main
```

### 2. Gmail送信用のApp Passwordを用意する

通常のGoogleアカウントのパスワードではなく、Gmail送信用の **アプリパスワード** を使います。

前提として、Googleアカウントで2段階認証を有効にします。そのうえでGoogleアカウントの「アプリパスワード」から、メール送信用の16桁のパスワードを作成します。

GitHub repositoryの `Settings > Secrets and variables > Actions > Repository secrets` に以下を登録します。

- `GMAIL_USER` 送信元のGmailアドレス。例: `yourname@gmail.com`
- `GMAIL_APP_PASSWORD` Gmailのアプリパスワード。通常ログインパスワードではありません。
- `NOTIFY_TO` 通知先メールアドレス。自分宛てなら `GMAIL_USER` と同じでOKです。

### 3. 監視対象を登録する

`properties.example.csv` をコピーして `properties.csv` を作り、URLを登録します。

```csv
name,url,memo
中野坂上サンプル,https://example.com/property/123,気になる物件
```

`properties.csv` をGitHubにコミットします。

### 4. 手元で実行する

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m property_watcher.run --csv properties.csv --db property_watcher.db
```

Gmail通知も試す場合:

```bash
export GMAIL_USER='yourname@gmail.com'
export GMAIL_APP_PASSWORD='xxxx xxxx xxxx xxxx'
export NOTIFY_TO='yourname@gmail.com'
python -m property_watcher.run --csv properties.csv --db property_watcher.db
```

### 5. GitHub Actionsで定期実行

`.github/workflows/watch.yml` により、1日1回（日本時間 9:15 頃）実行されます。

GitHub Actionsの無料枠・対象サイトへの負荷を考え、最初はこの程度で十分です。

## 検知内容

- HTTPステータス変化
- 掲載終了っぽい文言
- タイトル変化
- 価格変化
- 本文ハッシュ（最新状態の確認用。通知対象外）
- 問い合わせボタン等の文言変化

## 通知メールの内容

変更があると、以下のような件名でGmail通知します。

```text
[物件ウォッチ] 価格が変わりました: 中野坂上サンプル
```

初回登録時はDBに保存するだけで、通知は飛ばしません。2回目以降に差分が出た場合だけ通知します。

## 注意

これは「成約」を直接検知するものではありません。実際には、掲載終了・ページ削除・問い合わせ停止・価格変更などの状態変化を早めに拾うためのツールです。

各サイトの利用規約、robots.txt、アクセス頻度に注意してください。大量アクセスや商用利用は避けてください。


## 通知条件について

`content_hash`（本文全体のハッシュ）は最新状態の保存・確認用に保持しますが、メール通知の条件からは外しています。
SUUMOなどのページは広告、レコメンド、トラッキング、表示順などの動的要素で本文が毎回少し変わることがあるためです。

メール通知されるのは、主に以下の明確な変化です。

- 価格変更
- HTTPステータス変更、404/410など
- 掲載終了・成約済み等の状態文言変更
- タイトル変更
- 問い合わせ導線の有無変更
- 取得可否の変化

ページ取得に失敗した場合、価格・タイトル・掲載状態・問い合わせ導線は比較せず、取得失敗として1件だけ通知します。連続する同一の取得失敗は再通知せず、取得が戻ったときも復旧として1件だけ通知します。

本文の最新内容は `latest_snapshots.raw_text` に上書き保存されます。

## 室内写真の保存

SUUMOの室内写真は掲載終了後に元URLが無効になる可能性があるため、縮小JPEGをprivate repository内の `property_images/` に保存できます。DBの `property_images` テーブルには元URL、キャプション、種別、ローカルパス、画像ハッシュを記録します。画像は私的な記録に限定し、再公開しないでください。

通常の日次実行は `--images initial` で、物件ごとに最初の1回だけ室内写真を保存します。保存実施済みかどうかは `image_archive_status` テーブルで管理するため、翌日以降は画像へアクセスしません。

GitHub Actionsを手動実行するときは `image_mode` を選べます。

- `initial`: 未保存の物件だけ保存（通常はこちら）
- `refresh`: 全物件の室内写真を任意に再取得
- `off`: 写真を取得しない

ローカルで任意に再取得する場合:

```bash
python -m property_watcher.run --csv properties.csv --db property_watcher.db --images refresh
```

## 簡易Web画面

ローカルで監視状況を見るだけの簡易ダッシュボードを起動できます。

```bash
python -m property_watcher.web --db property_watcher.db --image-dir property_images
```

起動後、ブラウザで `http://127.0.0.1:8000/` を開きます。

一覧では監視中の物件、最新価格、掲載状態、HTTP状態、問い合わせ導線、保存写真数、最近のイベントを確認できます。物件名をクリックすると、詳細・イベント履歴・保存済み室内写真・最新テキストを確認できます。

### GitHub Pages で見る

GitHub Pages ではPythonサーバーやSQLiteを直接動かせないため、Actionsで `property_watcher.db` から静的HTMLを書き出して公開します。

```bash
python -m property_watcher.pages --db property_watcher.db --image-dir property_images --out site
```

`.github/workflows/pages.yml` を手動実行すると、静的HTMLをGitHub Pagesへデプロイします。GitHubの `Settings > Pages` で source が `GitHub Actions` になっている必要があります。

注意: GitHub Pagesの公開範囲はリポジトリ/アカウントの設定やプランに依存します。保存済み室内写真や物件メモも公開HTMLに含まれるため、公開範囲を確認してから使ってください。

このリポジトリがprivateのまま現在のGitHubプランでPagesを有効化できない場合があります。その場合は、リポジトリをpublicにする、Pages対応プランに変更する、または別の公開用リポジトリ/ホスティング先へ `site/` を配置してください。

## raw_text のクリーニング

`latest_snapshots.raw_text` はHTML全文ではなく、物件概要テーブル、`dt/dd`、JSON-LD、物件名、特徴・設備を優先して整形したテキストです。構造化情報が少ないページでは、物件情報らしいキーワードを含む行だけを補完します。
価格・掲載終了・問い合わせ導線の判定にはノイズ除去前の本文も使いますが、DBに保存して後から読む本文は `raw_text` として整形済みの内容を保存します。

次回の GitHub Actions 実行後に `latest_snapshots.raw_text` が新しい整形ルールで上書きされます。

## 追加候補物件のチェック

日次のGitHub Actionsでは、監視中物件の更新確認前に、追加候補物件もチェックします。条件に合った候補は `properties.csv` に自動追加され、その直後の監視処理でDB保存と画像保存の対象になります。

```bash
python -m property_watcher.discover --csv properties.csv --db property_watcher.db --auto-add --notify
```

中野坂上アムフラット702の売却参考として、対象は「55.61㎡・2LDK・1998年築・中野坂上駅徒歩3分」に近い比較候補へ寄せています。検索対象はSUUMOの「中野坂上」「中野新橋」「西新宿五丁目」「東中野」です。

デフォルト条件は `7000万円以上`、`1億1500万円以下`、`45㎡以上75㎡以下`、`1988年以降築`、`駅徒歩10分以内`、`2LDK/2SLDK/1LDK+S/納戸付き/75㎡以下の3LDK`、住所は中野区中央・本町・弥生町・東中野、新宿区北新宿・西新宿です。アムフラット702の売出履歴が8,780万円から8,998万円程度だったため、狭すぎる投資用や広すぎるファミリー物件を外しつつ、価格上限は相場上振れ候補も拾えるようにしています。

候補は `candidate_listings` テーブルに保存され、同じ候補は再通知しません。`--auto-add` が有効な場合は、DBに過去記録済みでもCSV未登録なら `properties.csv` へ追記します。
