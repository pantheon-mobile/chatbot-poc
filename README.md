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

### データ取り込み比較

同じPDFからPDF原本・TXT・Markdownを生成し、WebページからTXT・Markdownを生成します。
管理用正本とKB同期用コピーのS3二重配置、5つの検証専用Knowledge Baseの同期、評価質問CSVによる
Retrieve・回答生成比較、UTF-8 BOM付きCSV出力まで実行します。
Knowledge BaseとData Source自体は事前にAWS側で作成してください。

Secretsには次の設定を追加できます（画面からの入力も可能です）。

```toml
[ingestion_test]
s3_bucket = "YOUR_EXISTING_POC_BUCKET"
file_pdf_knowledge_base_id = "YOUR_FILE_PDF_KB_ID"
file_pdf_data_source_id = "YOUR_FILE_PDF_DATA_SOURCE_ID"
file_txt_knowledge_base_id = "YOUR_FILE_TXT_KB_ID"
file_txt_data_source_id = "YOUR_FILE_TXT_DATA_SOURCE_ID"
file_markdown_knowledge_base_id = "YOUR_FILE_MARKDOWN_KB_ID"
file_markdown_data_source_id = "YOUR_FILE_MARKDOWN_DATA_SOURCE_ID"
web_txt_knowledge_base_id = "YOUR_WEB_TXT_KB_ID"
web_txt_data_source_id = "YOUR_WEB_TXT_DATA_SOURCE_ID"
web_markdown_knowledge_base_id = "YOUR_WEB_MARKDOWN_KB_ID"
web_markdown_data_source_id = "YOUR_WEB_MARKDOWN_DATA_SOURCE_ID"
excel_xlsx_knowledge_base_id = "YOUR_EXCEL_XLSX_KB_ID"
excel_xlsx_data_source_id = "YOUR_EXCEL_XLSX_DATA_SOURCE_ID"
excel_csv_knowledge_base_id = "YOUR_EXCEL_CSV_KB_ID"
excel_csv_data_source_id = "YOUR_EXCEL_CSV_DATA_SOURCE_ID"
excel_markdown_knowledge_base_id = "YOUR_EXCEL_MARKDOWN_KB_ID"
excel_markdown_data_source_id = "YOUR_EXCEL_MARKDOWN_DATA_SOURCE_ID"
word_docx_knowledge_base_id = "YOUR_WORD_DOCX_KB_ID"
word_docx_data_source_id = "YOUR_WORD_DOCX_DATA_SOURCE_ID"
word_txt_knowledge_base_id = "YOUR_WORD_TXT_KB_ID"
word_txt_data_source_id = "YOUR_WORD_TXT_DATA_SOURCE_ID"
word_markdown_knowledge_base_id = "YOUR_WORD_MARKDOWN_KB_ID"
word_markdown_data_source_id = "YOUR_WORD_MARKDOWN_DATA_SOURCE_ID"
ppt_pptx_knowledge_base_id = "YOUR_PPT_PPTX_KB_ID"
ppt_pptx_data_source_id = "YOUR_PPT_PPTX_DATA_SOURCE_ID"
ppt_txt_knowledge_base_id = "YOUR_PPT_TXT_KB_ID"
ppt_txt_data_source_id = "YOUR_PPT_TXT_DATA_SOURCE_ID"
ppt_markdown_knowledge_base_id = "YOUR_PPT_MARKDOWN_KB_ID"
ppt_markdown_data_source_id = "YOUR_PPT_MARKDOWN_DATA_SOURCE_ID"
```

管理・追跡用正本は次の構成です。

```text
documents/ingestion-test/datasource/<datasource_id>/original/
documents/ingestion-test/datasource/<datasource_id>/processed/
```

各Data Sourceのinclusion prefixは次の1つだけに設定します。

```text
FILE_PDF:      documents/ingestion-test/kb-source/file-pdf/
FILE_TXT:      documents/ingestion-test/kb-source/file-txt/
FILE_MARKDOWN: documents/ingestion-test/kb-source/file-markdown/
WEB_TXT:       documents/ingestion-test/kb-source/web-txt/
WEB_MARKDOWN:  documents/ingestion-test/kb-source/web-markdown/
EXCEL_XLSX:    documents/ingestion-test/kb-source/excel-xlsx/
EXCEL_CSV:     documents/ingestion-test/kb-source/excel-csv/
EXCEL_MARKDOWN: documents/ingestion-test/kb-source/excel-markdown/
WORD_DOCX:      documents/ingestion-test/kb-source/word-docx/
WORD_TXT:       documents/ingestion-test/kb-source/word-txt/
WORD_MARKDOWN:  documents/ingestion-test/kb-source/word-markdown/
PPT_PPTX:       documents/ingestion-test/kb-source/ppt-pptx/
PPT_TXT:        documents/ingestion-test/kb-source/ppt-txt/
PPT_MARKDOWN:   documents/ingestion-test/kb-source/ppt-markdown/
```

各比較グループのData Sourceはすべて `Hierarchical Chunking`、Parent 1500 tokens、Child 300 tokens、
Overlap 60 tokensに手動設定してください。画面上の確認チェックを入れない限り比較は実行できません。

#### Web再帰クロール比較

「データ取り込み比較 PoC」→「Webページ取り込み」では、複数の起点URLから本文領域内のリンクを
再帰的に巡回し、取得した同一ページ集合を `WEB_TXT` と `WEB_MARKDOWN` に変換します。

- 1行に1件の起点URLを指定できます。
- 同一ホスト内のHTMLだけを追跡し、外部ホスト、PDF、Office、画像、動画、圧縮ファイルを除外します。
- ヘッダー、フッター、グローバルナビゲーション等のリンクは追跡対象にしません。
- URLのfragmentとトラッキング用queryを除去し、URL由来の固定`page_id`で重複を防止します。
- `robots.txt`遵守を既定で有効にし、アクセス間隔、最大深度、起点ごとの最大ページ数を設定できます。
- 1ページ取得に失敗しても残りを継続し、取得・エラー・除外をそれぞれCSVへ出力します。
- `web_crawl_manifest.json`を次回アップロードすると、新規・更新・変更なし・削除候補を判定できます。
- 削除候補は自動削除しません。`deleted_candidates.csv`を確認して運用判断してください。
- JASSO配下のmetadataは`source_authority=high`、その他は`medium`として保存します。

各ページのKB同期用KeyはURL由来の固定値です。

```text
documents/ingestion-test/kb-source/web-txt/<page_id>.txt
documents/ingestion-test/kb-source/web-markdown/<page_id>.md
```

再クロールで同じURLの本文が更新された場合は、同じKeyを更新します。管理用ログは次に保存します。

```text
documents/ingestion-test/datasource/<crawl_id>/crawl/
```

初回の再帰クロール評価前には、従来の単ページ取り込みで作成した`page.txt`、`page.md`と対応する
metadataをWeb用prefixから除外し、新しい成果物を配置してから2つのWeb Data Sourceを同期してください。

#### データ取り込み検証のIAM Action対応表

| boto3 client | メソッド | IAM Action | Resource | 目的 |
|---|---|---|---|---|
| `boto3.client("s3")` | `head_object` | `s3:GetObject` | `arn:aws:s3:::<BUCKET>/documents/ingestion-test/*` | 上書き防止 |
| `boto3.client("s3")` | `put_object` | `s3:PutObject` | `arn:aws:s3:::<BUCKET>/documents/ingestion-test/*` | 成果物配置 |
| `boto3.client("s3")` | `put_object` | `s3:PutObject` | `arn:aws:s3:::<BUCKET>/evaluation-history/*` | 評価履歴・手動レビュー保存 |
| `boto3.client("s3")` | `get_object` | `s3:GetObject` | `arn:aws:s3:::<BUCKET>/evaluation-history/*` | 評価履歴詳細読込 |
| `boto3.client("s3")` | `list_objects_v2` | `s3:ListBucket` | `arn:aws:s3:::<BUCKET>` | `evaluation-history/`の履歴一覧取得 |
| `boto3.client("bedrock-agent")` | `start_ingestion_job` | `bedrock:StartIngestionJob` | 検証用Knowledge Base ARN | 同期開始 |
| `boto3.client("bedrock-agent")` | `get_ingestion_job` | `bedrock:GetIngestionJob` | 検証用Knowledge Base ARN | 同期状態取得 |
| `boto3.client("bedrock-agent")` | `list_ingestion_jobs` | `bedrock:ListIngestionJobs` | 検証用Knowledge Base ARN | AWS上の最新同期状態取得 |
| `boto3.client("bedrock-agent-runtime")` | `retrieve` | `bedrock:Retrieve` | 検証用Knowledge Base ARN | Retrieve評価 |
| `boto3.client("bedrock-runtime")` | `converse` | `bedrock:InvokeModel` | Inference Profile ARNと配下Foundation Model ARN | 変換・回答生成 |
| `boto3.client("bedrock-agent-runtime")` | `retrieve_and_generate` | `bedrock:RetrieveAndGenerate` | `*` | 既存チャット回答 |
| `boto3.resource("dynamodb")` | `Table.put_item` | `dynamodb:PutItem` | `arn:aws:dynamodb:ap-northeast-1:<ACCOUNT_ID>:table/chatbot-feedback-table` | フィードバック保存 |
| `boto3.resource("dynamodb")` | `Table.scan` | `dynamodb:Scan` | `arn:aws:dynamodb:ap-northeast-1:<ACCOUNT_ID>:table/chatbot-feedback-table` | フィードバックCSV出力 |

PoC実行ロールの最小ポリシー例です。`<...>`は実リソースへ置き換え、KB ARNは検証用だけを列挙します。

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "IngestionTestObjects",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::<BUCKET>/documents/ingestion-test/*"
    },
    {
      "Sid": "ListEvaluationHistory",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::<BUCKET>",
      "Condition": {
        "StringLike": {
          "s3:prefix": ["evaluation-history", "evaluation-history/*"]
        }
      }
    },
    {
      "Sid": "ReadWriteEvaluationHistory",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::<BUCKET>/evaluation-history/*"
    },
    {
      "Sid": "TestKnowledgeBases",
      "Effect": "Allow",
      "Action": ["bedrock:StartIngestionJob", "bedrock:GetIngestionJob", "bedrock:ListIngestionJobs", "bedrock:Retrieve"],
      "Resource": ["arn:aws:bedrock:ap-northeast-1:<ACCOUNT_ID>:knowledge-base/<TEST_KB_ID>"]
    },
    {
      "Sid": "ComparisonModel",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": [
        "arn:aws:bedrock:ap-northeast-1:<ACCOUNT_ID>:inference-profile/<PROFILE_ID>",
        "arn:aws:bedrock:*::foundation-model/<FOUNDATION_MODEL_ID>"
      ]
    },
    {
      "Sid": "ExistingChatRetrieveAndGenerate",
      "Effect": "Allow",
      "Action": "bedrock:RetrieveAndGenerate",
      "Resource": "*"
    },
    {
      "Sid": "FeedbackTable",
      "Effect": "Allow",
      "Action": ["dynamodb:PutItem", "dynamodb:Scan"],
      "Resource": "arn:aws:dynamodb:ap-northeast-1:<ACCOUNT_ID>:table/chatbot-feedback-table"
    }
  ]
}
```

`evaluation-history/`は評価履歴専用です。Knowledge Base Data Sourceのinclusion prefixには
`documents/ingestion-test/kb-source/`だけを指定し、`evaluation-history/`を取り込み対象へ含めないでください。

評価実行中は、質問×方式が1件完了するたびに
`evaluation-history/_checkpoints/<評価グループ>.json`へ途中結果を上書き保存します。
Streamlitの再起動や通信切断後も、同じ評価CSV・KB/Data Source ID・検索設定・モデル設定で
再実行すると未完了の質問×方式だけを続行します。完了済みチェックポイントがある場合は、
Bedrockを再実行せず結果を復元します。最初からやり直す場合だけ、画面の
「保存済みの途中結果を使わず、新規評価として開始する」を選択してください。
履歴削除機能は実装していないため、PoC実行ロールに`s3:DeleteObject`は不要です。

Knowledge Baseサービスロールの最小ポリシー例です。OpenSearch Serverless利用時の例であり、
別のベクトルストアでは最後のStatementをそのサービス用権限へ置き換えます。

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListSourcePrefix",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::<BUCKET>",
      "Condition": {"StringLike": {"s3:prefix": ["documents/ingestion-test/kb-source/*"]}}
    },
    {
      "Sid": "ReadSourceObjects",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::<BUCKET>/documents/ingestion-test/kb-source/*"
    },
    {
      "Sid": "EmbeddingModel",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:ap-northeast-1::foundation-model/<EMBEDDING_MODEL_ID>"
    },
    {
      "Sid": "OpenSearchServerless",
      "Effect": "Allow",
      "Action": "aoss:APIAccessAll",
      "Resource": "arn:aws:aoss:ap-northeast-1:<ACCOUNT_ID>:collection/<COLLECTION_ID>"
    },
    {
      "Sid": "DecryptSourceObjectsIfKmsEncrypted",
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:ap-northeast-1:<ACCOUNT_ID>:key/<KEY_ID>"
    }
  ]
}
```

Knowledge Baseサービスロールの信頼ポリシーでは、Bedrockによる引き受けを次のように許可します。

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "bedrock.amazonaws.com"},
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {"aws:SourceAccount": "<ACCOUNT_ID>"},
        "ArnLike": {
          "aws:SourceArn": "arn:aws:bedrock:ap-northeast-1:<ACCOUNT_ID>:knowledge-base/*"
        }
      }
    }
  ]
}
```

OpenSearch Serverless側のデータアクセスポリシーにもKBサービスロールをPrincipalとして登録し、対象indexへ
`aoss:CreateIndex`、`aoss:DescribeIndex`、`aoss:ReadDocument`、`aoss:WriteDocument`を付与します。
SSE-KMSを使用しない場合は、上記JSONの`kms:Decrypt` Statementを削除します。

この機能には`s3:DeleteObject`、`bedrock:DeleteKnowledgeBase`、`bedrock:DeleteDataSource`、
`aoss:DeleteCollection`、`iam:*`は不要です。

#### Excel取り込み比較

`.xlsx`からXLSX原本、表示・非空シートごとのUTF-8 BOM付きCSV、Markdown表を生成します。
非表示・空シートは除外し、Excel Table定義があればその範囲、なければ使用セル範囲を使います。
数式は再計算せず、ファイルに保存された表示値を優先します。旧`.xls`、グラフ、画像、OCRは対象外です。

管理用正本とKB同期用コピーは同じ`datasource_id`で紐付け、CSVとMarkdownにはシート単位の
`document_part_id`を付けます。Excel専用3KBもHierarchical ChunkingのParent 1500、Child 300、
Overlap 60 tokensへ手動設定し、画面で確認してから比較を実行してください。

#### Word取り込み比較

`.docx`からDOCX原本、構造付きTXT、Markdownを生成します。見出し、段落順、リスト、表、
ハイパーリンク、改ページ、ヘッダー、フッターを可能な範囲で保持します。脚注、コメント、
複雑なテキストボックス、埋め込み画像、旧`.doc`は対象外です。Word専用3KBも同じChunking条件へ
手動設定し、画面で確認してから比較を実行してください。

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
