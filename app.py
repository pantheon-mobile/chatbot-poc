import streamlit as st
import boto3
import pandas as pd
import json
import io
import zipfile
import traceback from datetime 
import datetime
import streamlit as st

@st.dialog("フィードバックを送る")
def show_feedback_dialog(score, message_index, query, response_text, user_type):
    # バッド（改善）ボタンが押された場合（score == 0）
    if score == 0:
        st.markdown("### 改善フィードバックを送る")
        
        # 📄 画像2枚目のセレクトボックスを完全再現
        problem_type = st.selectbox(
            "報告したい問題の種類を選択してください（任意）",
            ["選択してください", "要求を完全に満たしていない", "回答に誤りがある", "情報が古い", "その他"]
        )
        
        st.write("詳細を入力してください（任意）：")
        user_comment = st.text_area(
            "詳細", 
            placeholder="この回答のどこに不満がありましたか？", 
            label_visibility="collapsed",
            key=f"dlg_cmt_{message_index}"
        )
        
    # グッド（ポジティブ）ボタンが押された場合（score == 1）
    else:
        st.markdown("### ポジティブなフィードバックを送る")
        problem_type = "ポジティブ（良好）"
        
        st.write("詳細を入力してください（任意）：")
        user_comment = st.text_area(
            "詳細", 
            placeholder="この回答の満足できた点は何ですか？", 
            label_visibility="collapsed",
            key=f"dlg_cmt_{message_index}"
        )

    # ボタンを横並びに配置（キャンセル / 送信）
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("キャンセル", key=f"dlg_can_{message_index}", use_container_width=True):
            st.rerun()
            
    with col2:
        if st.button("送信", type="primary", key=f"dlg_sub_{message_index}", use_container_width=True):
            try:
                # 🗄️ AWS DynamoDBへ「質問・回答・評価・コメント・属性」を一括自動格納
                dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
                table = dynamodb.Table('chatbot-feedback-table')
                
                table.put_item(
                    Item={
                        'feedback_id': f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{message_index}", # 一意のキー
                        'timestamp': str(datetime.now()),
                        'query': query,
                        'response': response_text,
                        'score': int(score), # 1=Good, 0=Bad
                        'problem_type': problem_type,
                        'comment': user_comment if user_comment else "なし",
                        'user_type': user_type
                    }
                )
                st.toast("フィードバックを送信しました！")
                st.rerun()
            except Exception as e:
                st.error(f"データベース保存エラー: {e}")

# --- 🔒 セキュリティ設定（パスワード） ---
VALID_PASSWORD = "hp_chatbot_2026"

st.set_page_config(page_title="ハーモニープラス チャットボットPoC", page_icon="🎓", layout="wide")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 パスワード認証")
    user_password = st.text_input("検証用パスワードを入力してください", type="password")
    if st.button("ログイン"):
        if user_password == VALID_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("パスワードが違います。")
    st.stop()

# --- 🗂️ 画面のタブ切り替え（機能を同居させる） ---
tab1, tab2 = st.tabs(["💬 チャット検証画面", "📊 【管理者専用】Excel自動変換ツール"])

# ==========================================
#  タブ1：チャット検証画面（お客様・テスター用）
# ==========================================
with tab1:
    st.markdown(
        """
        <style>
        /* チャット内の大見出し（#、H1相当）のサイズを調整 */
        .stChatMessage h1 {
            font-size: 20px !important;
            font-weight: 600 !important;
            margin-bottom: 8px !important;
        }
        /* チャット内の中見出し（##、H2相当）のサイズを調整 */
        .stChatMessage h2 {
            font-size: 18px !important;
            font-weight: 600 !important;
            margin-bottom: 6px !important;
        }
        /* チャット内の小見出し（###、H3相当）のサイズを調整 */
        .stChatMessage h3 {
            font-size: 17px !important;
            font-weight: 600 !important;
            margin-bottom: 6px !important;
        }
        /* チャット内の本文のサイズを調整 */
        .stChatMessage p, .stChatMessage li {
            font-size: 15px !important;
            line-height: 1.6 !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    st.title("チャットボット検証")
    st.caption("AWS S3に格納したQ&Aドキュメントベースでお答えします。")

    target_user = st.radio(
        "対象者を選択してください：",
        ["すべて", "学生", "教員", "職員"],
        horizontal=True
    )

    # Secretsから子アカウントの鍵を引き抜いて接続
    bedrock_agent_runtime = boto3.client(
        service_name="bedrock-agent-runtime", 
        region_name="ap-northeast-1",
        aws_access_key_id=st.secrets["aws"]["aws_access_key_id"],
        aws_secret_access_key=st.secrets["aws"]["aws_secret_access_key"]
    )
    
    # 公式コード通りの正しい10桁のナレッジベースID
    KNOWLEDGE_BASE_ID = "TZKVQ8D3M6"

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            
        if message["role"] == "assistant":
            # 画面上にGood/Badボタンを設置
            feedback = st.feedback("thumbs", key=f"fb_{idx}")
            
            # ボタンが押されたら、上記で定義したポップアップ関数をフワッと起動
            if feedback is not None:
                # 1つ前のユーザーの質問（query）を取得
                user_query_text = st.session_state.messages[idx-1]["content"] if idx > 0 else "不明な質問"
                
                # ポップアップを画面中央に起動させる
                show_feedback_dialog(
                    score=feedback, 
                    message_index=idx, 
                    query=user_query_text, 
                    response_text=message["content"], 
                    user_type=target_user
                )

    # ユーザーからの質問入力
user_query = st.chat_input("例：学生寮に入っている場合の申請書類を教えてください")
if user_query:
        with st.chat_message("user"):
            st.markdown(user_query)
        st.session_state.messages.append({"role": "user", "content": user_query})

        with st.chat_message("assistant"):
            response_placeholder = st.empty()
            try:
                aws_filter = None
                if target_user == "学生":
                    aws_filter = {"orAll": [
                        {"equals": {"key": "user_type", "value": "学生"}},
                        {"equals": {"key": "user_type", "value": "all"}}
                    ]}
                elif target_user == "教員":
                    aws_filter = {"orAll": [
                        {"equals": {"key": "user_type", "value": "教員"}},
                        {"equals": {"key": "user_type", "value": "all"}}
                    ]}
                elif target_user == "職員":
                    aws_filter = {"orAll": [
                        {"equals": {"key": "user_type", "value": "職員"}},
                        {"equals": {"key": "user_type", "value": "all"}}
                    ]}

                # ナレッジベースのベース設定
                kb_config = {
                    'knowledgeBaseId': KNOWLEDGE_BASE_ID,
                    'modelArn': 'jp.anthropic.claude-sonnet-4-6'
                }

                kb_config['retrievalConfiguration'] = {
                    'vectorSearchConfiguration': {
                        'numberOfResults': 5
                    }
                }

                if aws_filter:
                    kb_config['retrievalConfiguration']['vectorSearchConfiguration']['filter'] = aws_filter


                kb_config['generationConfiguration'] = {
                    'inferenceConfig': {
                        'textInferenceConfig': {
                            'maxTokens': 4000
                        }
                    },
                    'promptTemplate': {
                        'textPromptTemplate': (
                            "あなたは大学の奨学金業務のベテラン職員です。提供された検索結果（マニュアルや規程の資料）のみに基づいて、ユーザーの質問に正確に答えてください。\n\n"
                            "【重要な指示】\n"
                            "1. 検索結果の資料内に、必要書類の名前（例：確認書兼個人信用情報の取扱いに関する同意書、住民票の写しなど）や、対象者の条件が断片的にでも記載されている場合は、「一覧表の形式ではないから」という理由で拒否したり隠したりせず、見つかった書類名や条件をすべて漏れなく抜き出して箇条書き（リスト形式）で出力してください。\n"
                            "2. 資料に記載されている具体的な書類名は絶対に省略せず、正式名称のまま詳しく出力してください。\n"
                            "3. 資料に書かれていない嘘（ハルシネーション）は一切混ぜないでください。\n\n"
                            "検索結果:\n$search_results$\n\n"
                            "ユーザーの質問: $query$"
                        )
                    }
                }

                # Amazon Bedrock ナレッジベースを呼び出し
                response = bedrock_agent_runtime.retrieve_and_generate(
                    input={'text': user_query},
                    retrieveAndGenerateConfiguration={
                        'type': 'KNOWLEDGE_BASE',
                        'knowledgeBaseConfiguration': kb_config
                    }
                )
                ai_answer = response['output']['text']
                
                # 正常に回答が取れたときだけ画面に表示して履歴に保存
                response_placeholder.markdown(ai_answer)
                st.session_state.messages.append({"role": "assistant", "content": ai_answer})

            except Exception as e:
                # まだ完全に動き出すまでは、原因究明用の詳細デバッグログを残しておきます
                st.error(f"エラーが発生しました: {str(e)}")
                st.warning("詳細なエラーログ（ここが原因究明のヒントになります）:")
                st.code(traceback.format_exc())



# ==========================================
#  タブ2：管理者専用 Excel自動変換ツール
# ==========================================
with tab2:
    st.title("📊 Excel ➡ Bedrockデータ一括自動変換")
    st.write("Q&A管理用のExcelファイルをアップロードすると、Bedrock用のテキストとJSON(メタデータ)に自動変換し、ZIPでまとめてダウンロードできます。")

    uploaded_file = st.file_uploader("Excelファイルをアップロードしてください", type=["xlsx", "xls"])

    if uploaded_file is not None:
        try:
            df = pd.read_excel(uploaded_file)
            st.success("Excelファイルを正常に読み込みました。")
            st.dataframe(df.head(3)) # 先頭3行をプレビュー

            if st.button("🚀 変換を実行してZIPを作成"):
                # ⭕ 変換ボタンが押された瞬間の現在日時を「yyyyMMddHHmmss」の14桁の文字列として取得します
                from datetime import datetime
                current_timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

                # メモリ上にZIPファイルを展開する準備
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    
                    # ⭕ ループ処理の中で行番号(i)をカウントし、3桁の連番（000, 001, 002...）を作ります
                    for i, (index, row) in enumerate(df.iterrows()):
                        
                        # ⭕ 日時14桁 + 3桁の連番を組み合わせて、指定通りの17桁のIDを生成！
                        serial_suffix = f"{i:03d}"  # 3桁固定
                        qa_id = f"{current_timestamp}{serial_suffix}"
                        
                        category = str(row.get('分類', '未分類'))
                        question = str(row.get('質問（回答用）', ''))
                        answer = str(row.get('回答1', ''))
                        tags = str(row.get('タグ', ''))
                        
                        # 画面の絞り込みボタン（日本語）と連動させるための判定ロジック
                        user_type_str = "all"  # 初期値
                        
                        val_student = str(row.get('学生', '')).strip()
                        val_teacher = str(row.get('教員', '')).strip()
                        val_staff = str(row.get('職員', '')).strip()
                        maru_list = ['〇', '○', '◯', 'X', 'x', 'o', 'O']

                        if val_student in maru_list:
                            user_type_str = "学生"
                        elif val_teacher in maru_list:
                            user_type_str = "教員"
                        elif val_staff in maru_list:
                            user_type_str = "職員"

                        # ① 本文ファイル（Markdown）の作成
                        markdown_content = f"# 【分類：{category}】{question}\n\n## 質問\n{question}\n\n## 回答\n{answer}\n\n## 属性・タグ\n- タグ: {tags}\n- 対象者: {user_type_str}\n"
                        # ⭕ ファイル名も、指定通りの「qa_20260628174900000.txt」の形に自動で切り替わります
                        txt_filename = f"qa_{qa_id}.txt"
                        zip_file.writestr(txt_filename, markdown_content)

                        # ② メタデータファイル（JSON）の作成
                        metadata = {
                            "metadataAttributes": {
                                "document_type": "QA",
                                "category": category,
                                "user_type": user_type_str,
                                "qa_id": qa_id  # 👈 JSONの内部IDも17桁の連番と連動させます
                            }
                        }
                        # ⭕ メタデータJSONのファイル名も、テキスト名と1文字の狂いもなく完全一致します
                        json_filename = f"qa_{qa_id}.txt.metadata.json"
                        zip_file.writestr(json_filename, json.dumps(metadata, ensure_ascii=False, indent=2))

                # ダウンロードボタンの配置
                st.success("🎉 変換が完了しました！下のボタンからZIPファイルをダウンロードしてください。")
                st.download_button(
                    label="💾 変換済みデータをダウンロード(ZIP)",
                    data=zip_buffer.getvalue(),
                    file_name="bedrock_converted_data.zip",
                    mime="application/zip"
                )
        except Exception as e:
            st.error(f"ファイル処理中にエラーが発生しました: {str(e)}")


