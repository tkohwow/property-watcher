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

## raw_text のクリーニング

`latest_snapshots.raw_text` はHTML全文ではなく、物件概要テーブル、`dt/dd`、JSON-LD、物件名、特徴・設備を優先して整形したテキストです。構造化情報が少ないページでは、物件情報らしいキーワードを含む行だけを補完します。
価格・掲載終了・問い合わせ導線の判定にはノイズ除去前の本文も使いますが、DBに保存して後から読む本文は `raw_text` として整形済みの内容を保存します。

次回の GitHub Actions 実行後に `latest_snapshots.raw_text` が新しい整形ルールで上書きされます。
