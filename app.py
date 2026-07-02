import streamlit as st
import boto3
import pandas as pd
import json
import io
import zipfile
import traceback
from datetime import datetime

print(boto3.__version__)


# ==========================================
#  ダイアログ：フィードバック送信
# ==========================================
@st.dialog("フィードバックを送る")
def show_feedback_dialog(score, message_index, query, response_text, user_type):
    if score == 0:
        st.markdown("### 改善フィードバックを送る")

        problem_type = st.selectbox(
            "報告したい問題の種類を選択してください（任意）",
            ["選択してください", "要求を完全に満たしていない", "回答に誤りがある", "情報が古い", "その他"],
            key=f"dlg_problem_{message_index}"
        )

        st.write("詳細を入力してください（任意）：")
        user_comment = st.text_area(
            "詳細",
            placeholder="この回答のどこに不満がありましたか？",
            label_visibility="collapsed",
            key=f"dlg_cmt_{message_index}"
        )

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

    col1, col2 = st.columns([1, 1])

    with col1:
        if st.button("キャンセル", key=f"dlg_can_{message_index}", use_container_width=True):
            st.session_state.feedback_key_version[message_index] = (
                st.session_state.feedback_key_version.get(message_index, 0) + 1
            )
            st.session_state.feedback_target = None
            st.rerun()

    with col2:
        if st.button("送信", type="primary", key=f"dlg_sub_{message_index}", use_container_width=True):
            try:
                dynamodb = boto3.resource(
                    service_name="dynamodb",
                    region_name="ap-northeast-1",
                    aws_access_key_id=st.secrets["aws"]["aws_access_key_id"],
                    aws_secret_access_key=st.secrets["aws"]["aws_secret_access_key"]
                )

                table = dynamodb.Table("chatbot-feedback-table")

                table.put_item(
                    Item={
                        "feedback_id": f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{message_index}",
                        "timestamp": str(datetime.now()),
                        "query": query,
                        "response": response_text,
                        "score": int(score),
                        "problem_type": problem_type,
                        "comment": user_comment if user_comment else "なし",
                        "user_type": user_type
                    }
                )

                st.session_state.feedback_key_version[message_index] = (
                    st.session_state.feedback_key_version.get(message_index, 0) + 1
                )

                st.session_state.feedback_target = None
                st.session_state.feedback_toast = "フィードバックを送信しました。"
                st.rerun()

            except Exception as e:
                st.error(f"データベース保存エラー: {e}")


# ==========================================
#  初期設定
# ==========================================
VALID_PASSWORD = "hp_chatbot_2026"

st.set_page_config(
    page_title="ハーモニープラス チャットボットPoC",
    page_icon="🎓",
    layout="wide"
)

st.markdown("""
<style>

/* サイドバー全体 */
section[data-testid="stSidebar"] {
    background-color: #F8F9FA;
}

/* メニュータイトル */
section[data-testid="stSidebar"] label {
    font-size: 18px !important;
    font-weight: 700 !important;
}

/* ラジオボタンの文字 */
section[data-testid="stSidebar"] div[role="radiogroup"] label p {
    font-size: 18px !important;
    font-weight: 500 !important;
}

/* ラジオボタンの余白 */
section[data-testid="stSidebar"] div[role="radiogroup"] label {
    padding-top: 8px;
    padding-bottom: 8px;
}

</style>
""", unsafe_allow_html=True)

# ==========================================
#  サイドメニュー
# ==========================================
page = st.sidebar.radio(
    "メニュー",
    [
        "💬 チャット検証画面",
        "📊 Excel自動変換ツール",
        "💾 フィードバックCSV出力"
    ]
)

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if "messages" not in st.session_state:
    st.session_state.messages = []

if "feedback_target" not in st.session_state:
    st.session_state.feedback_target = None

if "feedback_key_version" not in st.session_state:
    st.session_state.feedback_key_version = {}


# ==========================================
#  パスワード認証
# ==========================================
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

# ==========================================
#  メニュー1：チャット検証画面
# ==========================================
if page == "💬 チャット検証画面":
    if "feedback_toast" in st.session_state:
        st.toast(st.session_state.feedback_toast)
        del st.session_state.feedback_toast

    st.markdown(
        """
        <style>
        .stChatMessage h1 {
            font-size: 20px !important;
            font-weight: 600 !important;
            margin-bottom: 8px !important;
        }
        .stChatMessage h2 {
            font-size: 18px !important;
            font-weight: 600 !important;
            margin-bottom: 6px !important;
        }
        .stChatMessage h3 {
            font-size: 17px !important;
            font-weight: 600 !important;
            margin-bottom: 6px !important;
        }
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

    if st.button("チャットを初期化"):
        st.session_state.messages = []
        st.session_state.feedback_target = None
        st.session_state.feedback_key_version = {}
        st.rerun()

    target_user = st.radio(
        "対象者を選択してください：",
        ["すべて", "学生", "教員", "職員"],
        horizontal=True
    )

    bedrock_agent_runtime = boto3.client(
        service_name="bedrock-agent-runtime",
        region_name="ap-northeast-1",
        aws_access_key_id=st.secrets["aws"]["aws_access_key_id"],
        aws_secret_access_key=st.secrets["aws"]["aws_secret_access_key"]
    )

    KNOWLEDGE_BASE_ID = "TZKVQ8D3M6"

    # 既存メッセージ表示
    for idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

        if message["role"] == "assistant":
            version = st.session_state.feedback_key_version.get(idx, 0)
            feedback = st.feedback("thumbs", key=f"fb_{idx}_{version}")

            if feedback is not None:
                user_query_text = st.session_state.messages[idx - 1]["content"] if idx > 0 else "不明な質問"

                st.session_state.feedback_target = {
                    "score": feedback,
                    "message_index": idx,
                    "query": user_query_text,
                    "response_text": message["content"],
                    "user_type": target_user
                }

    # ダイアログ表示はループ外で1回だけ
    if st.session_state.feedback_target is not None:
        fb = st.session_state.feedback_target

        show_feedback_dialog(
            score=fb["score"],
            message_index=fb["message_index"],
            query=fb["query"],
            response_text=fb["response_text"],
            user_type=fb["user_type"]
        )
    # 入力
    user_query = st.chat_input("例：学生寮に入っている場合の申請書類を教えてください")
    
    if user_query:
        st.session_state.messages.append({"role": "user", "content": user_query})

        with st.chat_message("user"):
            st.markdown(user_query)

        with st.chat_message("assistant"):
            response_placeholder = st.empty()

            try:
                aws_filter = None

                if target_user == "学生":
                    aws_filter = {
                        "orAll": [
                            {"equals": {"key": "user_type", "value": "学生"}},
                            {"equals": {"key": "user_type", "value": "all"}}
                        ]
                    }

                elif target_user == "教員":
                    aws_filter = {
                        "orAll": [
                            {"equals": {"key": "user_type", "value": "教員"}},
                            {"equals": {"key": "user_type", "value": "all"}}
                        ]
                    }

                elif target_user == "職員":
                    aws_filter = {
                        "orAll": [
                            {"equals": {"key": "user_type", "value": "職員"}},
                            {"equals": {"key": "user_type", "value": "all"}}
                        ]
                    }

                kb_config = {
                    "knowledgeBaseId": KNOWLEDGE_BASE_ID,
                    "modelArn": "jp.anthropic.claude-sonnet-4-6",
                    "retrievalConfiguration": {
                        "vectorSearchConfiguration": {
                            "numberOfResults": 5,
                            "overrideSearchType": "HYBRID"
                        }
                    },
                    "generationConfiguration": {
                        "inferenceConfig": {
                            "textInferenceConfig": {
                                "maxTokens": 4000
                            }
                        },
                        "promptTemplate": {
                            "textPromptTemplate": (
                                "あなたは大学の奨学金業務のベテラン職員です。"
                                "提供された検索結果（マニュアルや規程の資料）のみに基づいて、"
                                "ユーザーの質問に正確に答えてください。\n\n"
                                "【重要な指示】\n"
                                "1. 検索結果の資料内に、必要書類の名前や対象者の条件が断片的にでも記載されている場合は、"
                                "見つかった書類名や条件をすべて漏れなく箇条書きで出力してください。\n"
                                "2. 資料に記載されている具体的な書類名は省略せず、正式名称のまま出力してください。\n"
                                "3. 資料に書かれていない内容は混ぜないでください。\n\n"
                                "検索結果:\n$search_results$\n\n"
                                "ユーザーの質問: $query$"
                            )
                        }
                    }
                }

                if aws_filter:
                    kb_config["retrievalConfiguration"]["vectorSearchConfiguration"]["filter"] = aws_filter

                response = bedrock_agent_runtime.retrieve_and_generate(
                    input={"text": user_query},
                    retrieveAndGenerateConfiguration={
                        "type": "KNOWLEDGE_BASE",
                        "knowledgeBaseConfiguration": kb_config
                    }
                )

                ai_answer = response["output"]["text"]

                response_placeholder.markdown(ai_answer)

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": ai_answer
                })

                st.rerun()

            except Exception as e:
                st.error(f"エラーが発生しました: {str(e)}")
                st.warning("詳細なエラーログ：")
                st.code(traceback.format_exc())


# ==========================================
#  メニュー2：管理者専用 Excel自動変換ツール
# ==========================================
elif page == "📊 Excel自動変換ツール":
    st.title("📊 Excel ➡ Bedrockデータ一括自動変換")
    st.write(
        "Q&A管理用のExcelファイルをアップロードすると、"
        "Bedrock用のテキストとJSON(メタデータ)に自動変換し、ZIPでまとめてダウンロードできます。"
    )

    uploaded_file = st.file_uploader("Excelファイルをアップロードしてください", type=["xlsx", "xls"])

    if uploaded_file is not None:
        try:
            df = pd.read_excel(uploaded_file)

            st.success("Excelファイルを正常に読み込みました。")
            st.dataframe(df.head(3))

            if st.button("🚀 変換を実行してZIPを作成"):
                current_timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

                zip_buffer = io.BytesIO()

                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    for i, (_, row) in enumerate(df.iterrows()):
                        serial_suffix = f"{i:03d}"
                        qa_id = f"{current_timestamp}{serial_suffix}"

                        category = str(row.get("分類", "未分類"))
                        question = str(row.get("質問（回答用）", ""))
                        answer = str(row.get("回答1", ""))
                        tags = str(row.get("タグ", ""))

                        user_type_str = "all"

                        val_student = str(row.get("学生", "")).strip()
                        val_teacher = str(row.get("教員", "")).strip()
                        val_staff = str(row.get("職員", "")).strip()

                        maru_list = ["〇", "○", "◯", "X", "x", "o", "O"]

                        if val_student in maru_list:
                            user_type_str = "学生"
                        elif val_teacher in maru_list:
                            user_type_str = "教員"
                        elif val_staff in maru_list:
                            user_type_str = "職員"

                        markdown_content = (
                            f"# 【分類：{category}】{question}\n\n"
                            f"## 質問\n{question}\n\n"
                            f"## 回答\n{answer}\n\n"
                            f"## 属性・タグ\n"
                            f"- タグ: {tags}\n"
                            f"- 対象者: {user_type_str}\n"
                        )

                        txt_filename = f"qa_{qa_id}.txt"
                        zip_file.writestr(txt_filename, markdown_content)

                        metadata = {
                            "metadataAttributes": {
                                "document_type": "QA",
                                "category": category,
                                "user_type": user_type_str,
                                "qa_id": qa_id
                            }
                        }

                        json_filename = f"qa_{qa_id}.txt.metadata.json"
                        zip_file.writestr(
                            json_filename,
                            json.dumps(metadata, ensure_ascii=False, indent=2)
                        )

                st.success("🎉 変換が完了しました。下のボタンからZIPファイルをダウンロードしてください。")

                st.download_button(
                    label="💾 変換済みデータをダウンロード(ZIP)",
                    data=zip_buffer.getvalue(),
                    file_name="bedrock_converted_data.zip",
                    mime="application/zip"
                )

        except Exception as e:
            st.error(f"ファイル処理中にエラーが発生しました: {str(e)}")

# ==========================================
#  メニュー3：管理者専用 フィードバックCSV出力ツール
# ==========================================
elif page == "💾 フィードバックCSV出力":

    st.title("💾 フィードバックCSV出力")
    st.write("Good/Badボタンで保存されたフィードバックデータをCSVファイルとして出力します。")

    if st.button("CSVファイルを作成"):
        try:
            dynamodb = boto3.resource(
                service_name="dynamodb",
                region_name="ap-northeast-1",
                aws_access_key_id=st.secrets["aws"]["aws_access_key_id"],
                aws_secret_access_key=st.secrets["aws"]["aws_secret_access_key"]
            )

            table = dynamodb.Table("chatbot-feedback-table")

            items = []
            response = table.scan()
            items.extend(response.get("Items", []))

            while "LastEvaluatedKey" in response:
                response = table.scan(
                    ExclusiveStartKey=response["LastEvaluatedKey"]
                )
                items.extend(response.get("Items", []))

            if not items:
                st.warning("出力対象のフィードバックデータがありません。")
            else:
                df = pd.DataFrame(items)

                # 見やすい順番に並べ替え
                columns = [
                    "feedback_id",
                    "timestamp",
                    "user_type",
                    "score",
                    "problem_type",
                    "comment",
                    "query",
                    "response"
                ]

                existing_columns = [col for col in columns if col in df.columns]
                remaining_columns = [col for col in df.columns if col not in existing_columns]

                df = df[existing_columns + remaining_columns]

                csv_data = df.to_csv(index=False, encoding="utf-8-sig")

                file_name = datetime.now().strftime("%Y%m%d%H%M%S.csv")

                st.success("CSVファイルを作成しました。")

                st.download_button(
                    label="CSVファイルをダウンロード",
                    data=csv_data,
                    file_name=file_name,
                    mime="text/csv"
                )

        except Exception as e:
            st.error(f"CSV出力中にエラーが発生しました: {e}")
