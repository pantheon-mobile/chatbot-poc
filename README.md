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
```

`.streamlit/secrets.toml` は `.gitignore` に含まれているため、Gitにはコミットされません。

## 起動方法

```bash
streamlit run app.py
```

起動後、ブラウザでStreamlitアプリを開き、`[app] password` に設定したパスワードでログインします。

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
