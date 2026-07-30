# chatbot-poc

ハーモニープラス向けチャットボットのPoC用リポジトリです。

Streamlitで作成した検証アプリから、Amazon Bedrock Knowledge Basesを使ったRAG回答、Q&A ExcelのBedrock投入用データ変換、フィードバックCSV出力、PDFメタデータ生成を実行できます。

## 構成

```text
chatbot-poc/
├── app.py                  # Streamlitアプリ本体
├── requirements.txt        # Python依存パッケージ
├── README.md               # このファイル
├── .gitignore              # venv、secretsなどを除外
└── .streamlit/
    └── secrets.toml        # AWS認証情報、アプリ用パスワード
```

## 主な機能

### チャット検証画面

Amazon Bedrock Knowledge Basesに対して質問し、検索結果に基づく回答を生成します。

- 対象者を「すべて」「学生」「教員」「職員」から選択
- Knowledge Baseを「新KB（Hierarchical）」「現行KB（No Chunking）」から選択
- 検索タイプを `HYBRID` / `SEMANTIC` から選択
- Top K、最大出力トークン数を画面から調整
- 回答に対するGood/BadフィードバックをDynamoDBへ保存

### Excel自動変換ツール

Q&A管理用Excelをアップロードし、Bedrock Knowledge Baseに投入しやすい形式へ変換します。

出力されるファイル:

- `qa_*.txt`
- `qa_*.txt.metadata.json`

想定するExcel列:

- `分類`
- `質問（回答用）`
- `回答1`
- `タグ`
- `学生`
- `教員`
- `職員`

### フィードバックCSV出力

DynamoDBに保存されたチャット回答フィードバックをCSVとしてダウンロードします。

参照先テーブル:

- `chatbot-feedback-table`

### PDFメタデータ生成

PDFを複数アップロードし、先頭ページのテキストをClaudeで解析して、Bedrock Knowledge Base用の `.metadata.json` を生成します。

出力される主なメタデータ:

- `document_type`
- `category`
- `business`
- `system`
- `school_type`
- `target_user`
- `keywords`
- `summary`
- `source_file_name`
- `generated_at`

### JASSO Q&A取得

認可されたJASSO担当者向けアカウントでログインし、「よくあるご質問」のカテゴリ、
ページ送り、Q&A詳細を順番に巡回します。詳細URL由来の固定IDでBedrock投入用TXTと
metadata.jsonを生成し、前回マニフェストとの新規・更新・変更なし・削除候補の比較も行います。
アクセスは並列化せず、標準では1リクエストごとに1秒空けます。

## セットアップ

### 1. 仮想環境を作成

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. 依存パッケージをインストール

```bash
pip install -r requirements.txt
```

### 3. secrets.tomlを設定

`.streamlit/secrets.toml` を作成し、以下のように設定します。

```toml
[aws]
aws_access_key_id = "YOUR_AWS_ACCESS_KEY_ID"
aws_secret_access_key = "YOUR_AWS_SECRET_ACCESS_KEY"

[app]
password = "YOUR_APP_PASSWORD"

[JASSO]
user_id = "YOUR_AUTHORIZED_JASSO_USER_ID"
password = "YOUR_JASSO_PASSWORD"
```

`.streamlit/secrets.toml` は `.gitignore` に含まれているため、Gitにはコミットされません。

## 起動方法

```bash
streamlit run app.py
```

起動後、ブラウザでStreamlitアプリを開き、`[app] password` に設定したパスワードでログインします。

### JASSOクロールの実行

1. `.streamlit/secrets.toml.example`を参考に、ローカルのSecretsへ`[JASSO]`を設定します。
2. `streamlit run app.py`で起動し、「🌐 JASSO Q&A取得」を開きます。
3. 初回は「全件出力」のまま接続テスト後、クローリングを開始します。
4. 2回目以降は、前回ダウンロードした`jasso_crawl_manifest.json`をアップロードします。
5. 必要に応じて「新規・更新分のみ」を選ぶと、ZIPには差分だけが入ります。

ダウンロードできるファイルは、Bedrock投入用ZIP、最新マニフェスト、全件レポート、
削除候補CSV、エラーログCSVです。ZIPにはTXTと対応するmetadata.jsonだけが入ります。

依存パッケージとテストは次のコマンドで準備・実行できます。

```bash
pip install -r requirements.txt
pytest
```

Streamlit Community Cloudでは、アプリ設定のSecretsへ`.streamlit/secrets.toml`と同じ
`[JASSO]`設定を登録してください。`secrets.toml`自体はコミットしません。

#### JASSO取得のトラブルシューティング

- ログイン失敗時はID・パスワードと、ログインフォームの入力名・送信先を確認します。
- FAQへ到達できない場合は、ログイン後の学校区分リンクと「よくあるご質問」の表示文字列・hrefを確認します。
- Q/A解析エラー時はデバッグHTML保存を有効にし、`jasso_crawler.py`の`JassoSelectors`、
  パンくず、Q/A見出し周辺の構造を確認します。保存HTMLにCookieや入力した認証情報は含めません。
- 429や一時的な5xxでは自動リトライします。繰り返す場合はアクセス間隔を長くしてください。
- 正規の権限を持つアカウントでのみ利用してください。CAPTCHAや多要素認証が導入された場合、
  自動回避は行わず運用またはログイン方式を見直してください。

## AWSで利用するサービス

このアプリでは以下のAWSサービスを利用します。

- Amazon Bedrock Knowledge Bases
- Amazon Bedrock Runtime
- Amazon DynamoDB

デフォルトのリージョンは `ap-northeast-1` です。

## 現在コード内で参照しているAWSリソース

### Knowledge Base

```python
{
    "新KB（Hierarchical）": "BXMG6V1XFR",
    "現行KB（No Chunking）": "TZKVQ8D3M6"
}
```

### DynamoDB

```text
chatbot-feedback-table
```

### モデルID

```text
jp.anthropic.claude-sonnet-4-6
```

## 注意点

- AWS認証情報とアプリ用パスワードは必ず `.streamlit/secrets.toml` で管理してください。
- 画像PDFはテキスト抽出できない場合があります。
- PDFメタデータ生成を大量ファイルで実行する場合は、Bedrockのレート制限や処理時間に注意してください。
- `chatbot-feedback-table` が存在しない場合、フィードバック保存とCSV出力は失敗します。
