# Property Watcher

気になる中古マンション等の物件URLを1日1回監視し、掲載終了・価格変更・タイトル変更・本文変化を検知してGmailへ通知する自分用Botです。

この版は **最新状態だけ保存** する設計です。日次スナップショットを毎回増やさず、物件ごとの最後の取得結果だけを `latest_snapshots` に上書き保存します。価格変更・掲載終了などの変化は `events` に履歴として残します。

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

## 保存されるデータ

### `targets`

監視対象の物件URLです。

- `url`
- `name`
- `memo`
- `created_at`
- `updated_at`

### `latest_snapshots`

物件URLごとの最後の取得状態だけを保存します。毎日増えず、上書きされます。

- `url`
- `fetched_at`
- `ok`
- `status_code`
- `final_url`
- `title`
- `price`
- `status_text`
- `contact_available`
- `content_hash`
- `raw_text`
- `error`

`raw_text` には、最後に取得できたページ本文の正規化済みテキストを保存します。HTML全文ではありませんが、あとから「最後にどういう内容だったか」を確認しやすくするための項目です。

### `events`

変化があった時だけ履歴として追加します。

- `url`
- `occurred_at`
- `severity`
- `event_type`
- `message`
- `old_value`
- `new_value`

## DBを後から見る例

SQLiteでDBを開きます。

```bash
sqlite3 property_watcher.db
```

最新状態を見る:

```sql
.headers on
.mode column
select url, fetched_at, status_code, title, price, status_text, contact_available
from latest_snapshots;
```

最後に取得した本文を一部見る:

```sql
select url, substr(raw_text, 1, 1000) as raw_text_preview
from latest_snapshots;
```

変化履歴を見る:

```sql
select occurred_at, severity, event_type, message, old_value, new_value
from events
order by id desc;
```

## 検知内容

- HTTPステータス変化
- 掲載終了っぽい文言
- タイトル変化
- 価格変化
- 本文ハッシュ変化
- 問い合わせボタン等の文言変化

## 通知メールの内容

変更があると、以下のような件名でGmail通知します。

```text
[物件ウォッチ] 価格が変わりました: 中野坂上サンプル
```

初回登録時はDBに保存するだけで、通知は飛ばしません。2回目以降に差分が出た場合だけ通知します。

## 旧版から更新する場合

既存の `property_watcher.db` がある場合でも、そのまま使えます。

旧版の `snapshots` に前回取得結果が残っている場合、新版は初回だけそこを参照して差分比較します。以後は `latest_snapshots` に最新状態だけを上書き保存します。

旧版で蓄積された `snapshots` を削除してDBを軽くしたい場合は、動作確認後に以下を実行できます。

```sql
delete from snapshots;
vacuum;
```

## 注意

これは「成約」を直接検知するものではありません。実際には、掲載終了・ページ削除・問い合わせ停止・価格変更などの状態変化を早めに拾うためのツールです。

各サイトの利用規約、robots.txt、アクセス頻度に注意してください。大量アクセスや商用利用は避けてください。
