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
- 本文ハッシュ変化
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
