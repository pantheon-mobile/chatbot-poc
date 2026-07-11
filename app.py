import streamlit as st
import boto3
import pandas as pd
import json
import io
import zipfile
import traceback
import re
from datetime import datetime
from typing import Optional
from pypdf import PdfReader

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
#  PDFメタデータ生成 共通関数
# ==========================================
def extract_pdf_head_text(pdf_bytes: bytes, max_pages: int = 5) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    texts = []

    for i, page in enumerate(reader.pages[:max_pages]):
        text = page.extract_text()
        if text:
            texts.append(f"\n--- page {i + 1} ---\n{text}")

    return "\n".join(texts).strip()


def extract_json_from_text(text: str) -> dict:
    """Claudeの応答からJSON部分だけを取り出してdict化する。"""
    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError("JSON形式の応答を取得できませんでした。")

    return json.loads(cleaned[start:end + 1])


def generate_pdf_metadata_with_claude(pdf_text: str, file_name: str, model_id: str) -> tuple[dict, str]:
    bedrock_runtime = boto3.client(
        service_name="bedrock-runtime",
        region_name="ap-northeast-1",
        aws_access_key_id=st.secrets["aws"]["aws_access_key_id"],
        aws_secret_access_key=st.secrets["aws"]["aws_secret_access_key"]
    )

    prompt = f"""
あなたはAmazon Bedrock Knowledge BasesのRAG設計者です。
以下のPDF先頭テキストをもとに、S3に配置する .metadata.json を作成してください。

ファイル名:
{file_name}

PDF先頭テキスト:
{pdf_text}

必ず以下のJSONのみを返してください。

{{
  "metadataAttributes": {{
    "document_type": "",
    "category": "",
    "business": "",
    "system": "",
    "school_type": "",
    "target_user": "",
    "keywords": [],
    "summary": ""
  }}
}}

ルール:
- document_type: 操作マニュアル / 規程 / FAQ / データ仕様書 / 申請書 / 通知 / その他
- target_user: 学生 / 教員 / 職員 / all
- keywords: 検索で使われそうな語を10〜20個
- summary: 100文字程度
- JSON以外は出力しない
"""

    response = bedrock_runtime.converse(
        modelId=model_id,
        messages=[
            {
                "role": "user",
                "content": [{"text": prompt}]
            }
        ],
        inferenceConfig={
            "maxTokens": 1500,
            "temperature": 0
        }
    )

    response_text = response["output"]["message"]["content"][0]["text"]
    metadata = extract_json_from_text(response_text)

    if "metadataAttributes" not in metadata:
        metadata = {"metadataAttributes": metadata}

    attrs = metadata["metadataAttributes"]
    attrs["source_file_name"] = file_name
    attrs["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return metadata, response_text


# ==========================================
#  チャット検証画面 共通関数
# ==========================================
CHAT_MODEL_ID = "jp.anthropic.claude-sonnet-4-6"


def _normalize_message_text(text: str) -> str:
    return re.sub(r"\s+", "", text.strip().lower())


def _has_any_pattern(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _format_history_for_prompt(messages: list[dict], user_query: str, limit: int = 10) -> str:
    """直近履歴を基本に、必要なら最初のassistant回答を追加してプロンプト用に整形する。"""
    selected_messages = list(messages[-limit:])
    normalized = _normalize_message_text(user_query)

    if "最初の回答" in normalized:
        first_assistant = next((message for message in messages if message.get("role") == "assistant"), None)
        if first_assistant and first_assistant not in selected_messages:
            selected_messages = [first_assistant] + selected_messages

    lines = []
    for message in selected_messages:
        role = message.get("role")
        if role == "user":
            label = "ユーザー"
        elif role == "assistant":
            label = "アシスタント"
        else:
            continue
        lines.append(f"{label}:\n{message.get('content', '')}")

    return "\n\n".join(lines)


def _select_reference_assistant_info(messages: list[dict], user_query: str) -> dict:
    """CONTEXTUAL_RAGで優先参照するassistant回答と位置を返す。"""
    assistant_messages = [
        (idx, message.get("content", ""))
        for idx, message in enumerate(messages)
        if message.get("role") == "assistant" and message.get("content")
    ]
    if not assistant_messages:
        return {
            "label": "",
            "content": "",
            "message_indexes": [],
            "context": ""
        }

    normalized = _normalize_message_text(user_query)
    selected = []
    label = ""

    if "最初と最後" in normalized:
        selected = [assistant_messages[0]]
        label = "最初と最新のassistant回答"
        if assistant_messages[-1][0] != assistant_messages[0][0]:
            selected.append(assistant_messages[-1])
    elif "最初の回答" in normalized:
        selected = [assistant_messages[0]]
        label = "最初のassistant回答"
    elif any(keyword in normalized for keyword in ["最後の回答", "直前の回答", "前の回答", "さっきの回答", "先ほどの回答"]):
        selected = [assistant_messages[-1]]
        label = "直前のassistant回答"
    elif any(keyword in normalized for keyword in ["その書類", "その制度", "その手続", "その申請", "その奨学金", "それぞれ", "挙げた", "あった"]):
        selected = [assistant_messages[-1]]
        label = "直前のassistant回答"
    else:
        selected = [assistant_messages[-1]]
        label = "直前のassistant回答"

    blocks = []
    contents = []
    indexes = []
    for block_idx, (message_idx, content) in enumerate(selected, start=1):
        indexes.append(message_idx)
        contents.append(content)
        blocks.append(f"参照対象assistant回答{block_idx}:\n{content[:3000]}")

    return {
        "label": label,
        "content": "\n\n".join(contents),
        "message_indexes": indexes,
        "context": "\n\n".join(blocks)
    }


def _select_reference_assistant_context(messages: list[dict], user_query: str) -> str:
    return _select_reference_assistant_info(messages, user_query)["context"]


def _rule_classify_user_message(user_query: str) -> Optional[str]:
    """明確な表現だけをルールで分類し、曖昧な場合はNoneを返す。"""
    normalized = _normalize_message_text(user_query)

    if not normalized:
        return "CONVERSATION"

    # 「前年度」「前期」などの制度・時期を聞く質問は、会話上の「前の回答」と区別してRAGへ送る。
    rag_domain_patterns = [
        r"奨学金",
        r"申請",
        r"提出書類",
        r"必要書類",
        r"期限",
        r"締切",
        r"制度",
        r"規程",
        r"規則",
        r"対象者",
        r"条件",
        r"手続",
        r"手続き",
        r"提出先",
        r"提出方法",
        r"申請方法",
        r"窓口",
        r"郵送先",
        r"受付時間",
        r"金額",
        r"制度名",
        r"前年度",
        r"今年度",
        r"来年度",
        r"前期",
        r"後期",
    ]

    contextual_reference_patterns = [
        r"それ",
        r"その書類",
        r"その制度",
        r"その手続",
        r"その申請",
        r"その奨学金",
        r"それぞれ",
        r"挙げた書類",
        r"あった書類",
        r"あった制度",
        r"最初の回答の",
        r"最初の回答にある",
        r"最初の回答にあった",
        r"前の回答の",
        r"前の回答にある",
        r"前の回答にあった",
        r"直前の回答の",
        r"さっきの回答の",
        r"さっき挙げた",
        r"さっきの回答にある",
        r"先ほどの回答にある",
        r"直前の回答にある",
    ]
    contextual_lookup_patterns = [
        r"提出先",
        r"提出方法",
        r"どこに提出",
        r"どこへ提出",
        r"申請期限",
        r"期限",
        r"締切",
        r"対象者",
        r"条件",
        r"申請方法",
        r"窓口",
        r"郵送先",
        r"受付時間",
        r"金額",
        r"制度名",
        r"手続き",
        r"手続",
        r"必要書類",
        r"提出書類",
        r"詳しく教えて",
        r"具体的に教えて",
        r"違いますか",
        r"異なりますか",
    ]
    conversation_reference_patterns = [
        r"さっきの回答",
        r"先ほどの回答",
        r"前の回答",
        r"以前の回答",
        r"最初の回答",
        r"最後の回答",
        r"直前の回答",
        r"今の回答",
        r"回答が違う",
        r"回答に差がある",
        r"前と何が違う",
        r"同じことを聞いた",
    ]
    conversation_feedback_patterns = [
        r"ありがとう",
        r"ありがとうございます",
        r"わかりました",
        r"分かりました",
        r"了解",
        r"違う",
        r"そうじゃない",
        r"分かりにくい",
        r"わかりにくい",
        r"なぜ最初から書かなかった",
        r"最初から具体的に",
        r"最初から書いて",
        r"具体的に書いて",
    ]
    conversation_rewrite_patterns = [
        r"もっと詳しく",
        r"もっと簡単に",
        r"短くして",
        r"短めに",
        r"要約して",
        r"言い換えて",
        r"まとめて",
        r"箇条書きにして",
    ]

    has_context_reference = _has_any_pattern(normalized, contextual_reference_patterns)
    has_lookup_intent = _has_any_pattern(normalized, contextual_lookup_patterns)
    has_conversation_rewrite = _has_any_pattern(normalized, conversation_rewrite_patterns)

    if has_context_reference and has_lookup_intent:
        return "CONTEXTUAL_RAG"

    if _has_any_pattern(normalized, contextual_reference_patterns):
        if not has_conversation_rewrite:
            return None

    if _has_any_pattern(normalized, conversation_reference_patterns):
        return "CONVERSATION"

    if _has_any_pattern(normalized, conversation_feedback_patterns):
        has_domain_context = _has_any_pattern(normalized, rag_domain_patterns)
        is_question = any(mark in user_query for mark in ["?", "？"]) or re.search(
            r"(ですか|ますか|いつ|何|どこ|誰|どれ|必要|教えて)$",
            normalized
        )
        if not (has_domain_context and is_question):
            return "CONVERSATION"

    if has_conversation_rewrite:
        has_domain_context = _has_any_pattern(normalized, rag_domain_patterns)
        if has_domain_context:
            return None
        if len(normalized) <= 30:
            return "CONVERSATION"

    if _has_any_pattern(normalized, rag_domain_patterns):
        return "RAG"

    return None


def classify_user_message(user_query: str, messages: list[dict]) -> str:
    """ユーザー発言をRAG/CONVERSATION/CONTEXTUAL_RAGに分類する。失敗時は安全側でRAGにする。"""
    rule_result = _rule_classify_user_message(user_query)
    if rule_result:
        return rule_result

    try:
        bedrock_runtime = boto3.client(
            service_name="bedrock-runtime",
            region_name="ap-northeast-1",
            aws_access_key_id=st.secrets["aws"]["aws_access_key_id"],
            aws_secret_access_key=st.secrets["aws"]["aws_secret_access_key"]
        )

        history_text = _format_history_for_prompt(messages, user_query, limit=10)

        prompt = f"""
あなたは大学向けチャットボットの入力分類器です。
ユーザーの最新発言を、次のいずれか1語だけで分類してください。

RAG:
会話履歴を参照しなくても、その質問文だけでナレッジベースを検索できる質問。

CONVERSATION:
ナレッジベース検索は不要で、過去の回答への感想、指摘、比較、訂正依頼、要約、言い換え、挨拶として会話履歴だけで回答すべき発言。

CONTEXTUAL_RAG:
「それ」「その書類」「前の回答にある制度」「最初の回答にある書類」など、会話履歴を参照しないと検索対象を特定できないが、特定後はナレッジベース検索が必要な質問。

注意:
- 「前年度の申請期限は？」のように制度・申請内容を聞く場合はRAG。
- 「提出先」「提出方法」「必要書類」「期限」「対象者」「条件」「申請方法」「窓口」「郵送先」「受付時間」「金額」「制度名」「手続き」などの業務情報を求め、かつ過去の回答や「その」「それぞれ」を参照している場合はCONTEXTUAL_RAGを優先する。
- 「最初の回答の書類の提出先は？」はCONTEXTUAL_RAG。
- 「前の回答にある申請期限は？」のように過去回答内の対象についてナレッジベース情報を聞く場合はCONTEXTUAL_RAG。
- 「前の回答と違う」「さっきの回答を短くして」のように過去回答自体を扱う場合はCONVERSATION。
- 「もっと具体的に教えて」は、直前の話題について追加の事実情報を求めている場合はCONTEXTUAL_RAG、単なる言い換えや説明改善ならCONVERSATION。
- 必ず RAG、CONVERSATION、CONTEXTUAL_RAG のいずれか1語だけを返してください。

会話履歴:
{history_text}

最新発言:
{user_query}
"""

        response = bedrock_runtime.converse(
            modelId=CHAT_MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": [{"text": prompt}]
                }
            ],
            inferenceConfig={
                "maxTokens": 20,
                "temperature": 0
            }
        )
        label = response["output"]["message"]["content"][0]["text"].strip().upper()
        if label == "CONVERSATION":
            return "CONVERSATION"
        if label == "CONTEXTUAL_RAG":
            return "CONTEXTUAL_RAG"
        return "RAG"

    except Exception:
        return "RAG"


def rewrite_query_from_history(user_query: str, messages: list[dict], model_id: str) -> str:
    bedrock_runtime = boto3.client(
        service_name="bedrock-runtime",
        region_name="ap-northeast-1",
        aws_access_key_id=st.secrets["aws"]["aws_access_key_id"],
        aws_secret_access_key=st.secrets["aws"]["aws_secret_access_key"]
    )

    assistant_messages = [message for message in messages if message.get("role") == "assistant"]
    if not assistant_messages:
        return "NEED_CLARIFICATION"

    history_text = _format_history_for_prompt(messages, user_query, limit=10)
    reference_context = _select_reference_assistant_context(messages, user_query)

    prompt = f"""
あなたは大学向けRAGチャットボットの検索クエリ書き換え担当です。
会話履歴、参照対象assistant回答、最新のユーザー質問をもとに、Knowledge Base検索に適した自己完結した日本語の質問へ書き換えてください。

参照対象の優先ルール:
- 「直前の回答」「前の回答」「さっきの回答」「最後の回答」は最新または直近のアシスタント回答を優先する。
- 「最初の回答」は現在のチャット内で最初のアシスタント回答を優先する。
- 「最初と最後」は最初と最新のアシスタント回答を比較対象にする。

書き換え方:
- 参照対象assistant回答に含まれる箇条書き、書類名、制度名、要約、条件を、検索クエリの前提情報として含める。
- 「その書類」「それぞれ」などの指示語は、参照対象assistant回答内の具体的な名称に置き換える。
- 複数の書類や制度が挙がっている場合は、名称を省略せず列挙し、現在の質問で求めている提出先・期限・対象者・条件などと対応させる。
- 出力はKnowledge Base検索に渡す文章なので、「前提: ...。質問: ...。」のように、参照対象回答の内容と現在の質問意図が両方分かる形にする。

禁止事項:
- 参照対象の回答に存在しない書類名、制度名、期限、提出先を追加しない。
- 過去の別質問に出た情報を、参照対象の回答に含まれていたと誤認しない。
- Knowledge Baseに根拠が必要な提出先や期限を、会話履歴だけで断定しない。

出力ルール:
- 書き換え後の検索質問のみを1つ返す。
- 参照対象を特定できない場合だけ NEED_CLARIFICATION と返す。
- 前置き、説明、引用符、箇条書きは不要。

会話履歴:
{history_text}

参照対象assistant回答:
{reference_context}

最新のユーザー質問:
{user_query}
"""

    response = bedrock_runtime.converse(
        modelId=model_id,
        messages=[
            {
                "role": "user",
                "content": [{"text": prompt}]
            }
        ],
        inferenceConfig={
            "maxTokens": 500,
            "temperature": 0
        }
    )

    rewritten_query = response["output"]["message"]["content"][0]["text"].strip()
    if not rewritten_query:
        return user_query
    return rewritten_query


def answer_conversation_with_claude(messages: list[dict], max_tokens: int) -> str:
    bedrock_runtime = boto3.client(
        service_name="bedrock-runtime",
        region_name="ap-northeast-1",
        aws_access_key_id=st.secrets["aws"]["aws_access_key_id"],
        aws_secret_access_key=st.secrets["aws"]["aws_secret_access_key"]
    )

    recent_messages = messages[-10:]
    normalized_query = _normalize_message_text(messages[-1]["content"] if messages else "")
    if "最初の回答" in normalized_query:
        first_assistant = next((message for message in messages if message.get("role") == "assistant"), None)
        if first_assistant and first_assistant not in recent_messages:
            recent_messages = [first_assistant] + recent_messages

    while recent_messages and recent_messages[0]["role"] != "user":
        recent_messages = recent_messages[1:]

    converse_messages = [
        {
            "role": message["role"],
            "content": [{"text": message["content"]}]
        }
        for message in recent_messages
        if message["role"] in ["user", "assistant"]
    ]

    system_prompt = """
あなたは大学の奨学金チャットボットです。
今回はナレッジベース検索ではなく、直前までの会話履歴だけを使って自然に回答してください。

ルール:
- ユーザーの発言が過去の回答への指摘や感想の場合は、まず内容を理解して自然に応答してください。
- こちらの回答が不十分だった場合は、素直に謝罪してください。
- 過去の回答同士の比較を求められた場合は、会話履歴を比較して違いを説明してください。
- 「資料に記載がありません」のようなRAG向け回答はしないでください。
- 会話履歴にない内容を捏造しないでください。
- 必要に応じて簡潔に回答してください。
"""

    response = bedrock_runtime.converse(
        modelId=CHAT_MODEL_ID,
        system=[{"text": system_prompt}],
        messages=converse_messages,
        inferenceConfig={
            "maxTokens": max_tokens,
            "temperature": 0.2
        }
    )

    return response["output"]["message"]["content"][0]["text"]

# ==========================================
#  初期設定
# ==========================================
APP_PASSWORD = st.secrets["app"]["password"]

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
        "💾 フィードバックCSV出力",
        "🧾 PDFメタデータ生成"
    ]
)

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if "messages" not in st.session_state:
    st.session_state.messages = []

if "rag_session_id" not in st.session_state:
    st.session_state.rag_session_id = None

if "last_rag_setting_key" not in st.session_state:
    st.session_state.last_rag_setting_key = None

if "feedback_target" not in st.session_state:
    st.session_state.feedback_target = None

if "feedback_key_version" not in st.session_state:
    st.session_state.feedback_key_version = {}

if "rag_debug_info" not in st.session_state:
    st.session_state.rag_debug_info = {}


# ==========================================
#  パスワード認証
# ==========================================
if not st.session_state.authenticated:
    st.subheader("🔒 パスワード認証")

    user_password = st.text_input("検証用パスワードを入力してください", type="password")

    if st.button("ログイン"):
        if user_password == APP_PASSWORD:
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

    st.subheader("チャットボット検証")
    st.caption("AWS S3に格納したQ&Aドキュメントベースでお答えします。")

    if st.button("チャットを初期化"):
        st.session_state.messages = []
        st.session_state.feedback_target = None
        st.session_state.feedback_key_version = {}
        st.session_state.rag_debug_info = {}
        st.session_state.rag_session_id = None
        st.session_state.last_rag_setting_key = None
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

    st.sidebar.markdown("---")
    st.sidebar.subheader("⚙️ RAG設定")
    
    kb_options = {
        "階層型": "BXMG6V1XFR",
        "チャンクなし": "UFH1XNWUJE"
    }
    
    selected_kb_name = st.sidebar.selectbox(
        "ナレッジベース",
        list(kb_options.keys())
    )
    
    KNOWLEDGE_BASE_ID = kb_options[selected_kb_name]
    
    search_type_label = st.sidebar.radio(
        "検索タイプ",
        ["HYBRID", "SEMANTIC"],
        horizontal=True
    )
    
    top_k = st.sidebar.selectbox(
        "Top K（取得チャンク数）",
        [3, 5, 8, 10],
        index=1
    )
    
    max_tokens = st.sidebar.selectbox(
        "Maximum output tokens",
        [1000, 2000, 4000],
        index=2
    )

    use_chat_history = st.sidebar.checkbox(
        "会話履歴を利用する",
        value=False
    )

    show_rag_debug = st.sidebar.checkbox(
        "RAG処理内容を表示する",
        value=False
    )

    current_rag_setting_key = (
        KNOWLEDGE_BASE_ID,
        search_type_label,
        top_k,
        max_tokens,
        target_user
    )
    if st.session_state.last_rag_setting_key != current_rag_setting_key:
        st.session_state.rag_session_id = None
        st.session_state.last_rag_setting_key = current_rag_setting_key

    # 既存メッセージ表示
    for idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

            if show_rag_debug and message["role"] == "assistant":
                debug_info = st.session_state.rag_debug_info.get(idx)
                if debug_info:
                    with st.expander("RAG処理内容"):
                        st.write(f"分類結果: {debug_info.get('message_type', '')}")
                        st.write(f"元のユーザー質問: {debug_info.get('original_query', '')}")
                        if debug_info.get("reference_label"):
                            st.write(f"参照対象: {debug_info.get('reference_label', '')}")
                        if debug_info.get("reference_message_indexes"):
                            st.write(f"参照対象のメッセージ位置: {debug_info.get('reference_message_indexes', '')}")
                        if debug_info.get("reference_answer"):
                            st.write("参照した回答:")
                            st.text(debug_info.get("reference_answer", ""))
                        if debug_info.get("rewritten_query"):
                            st.write(f"書き換え後の検索クエリ: {debug_info.get('rewritten_query', '')}")
                        st.write(f"Knowledge Base ID: {debug_info.get('knowledge_base_id', '')}")
                        st.write(f"Search Type: {debug_info.get('search_type', '')}")
                        st.write(f"Top K: {debug_info.get('top_k', '')}")

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
        assistant_message_index = len(st.session_state.messages)

        with st.chat_message("user"):
            st.markdown(user_query)

        with st.chat_message("assistant"):
            response_placeholder = st.empty()

            try:
                message_type = classify_user_message(user_query, st.session_state.messages)
                rewritten_query = None
                reference_info = {
                    "label": "",
                    "content": "",
                    "message_indexes": [],
                    "context": ""
                }

                if message_type == "CONVERSATION":
                    ai_answer = answer_conversation_with_claude(
                        messages=st.session_state.messages,
                        max_tokens=max_tokens
                    )
                else:
                    rag_input_text = user_query

                    if message_type == "CONTEXTUAL_RAG":
                        reference_info = _select_reference_assistant_info(
                            st.session_state.messages,
                            user_query
                        )
                        if not reference_info["content"]:
                            ai_answer = "どの回答を指していますか？"
                            response_placeholder.markdown(ai_answer)

                            st.session_state.messages.append({
                                "role": "assistant",
                                "content": ai_answer
                            })
                            st.session_state.rag_debug_info[assistant_message_index] = {
                                "message_type": message_type,
                                "original_query": user_query,
                                "rewritten_query": "",
                                "reference_label": "",
                                "reference_answer": "",
                                "reference_message_indexes": [],
                                "knowledge_base_id": KNOWLEDGE_BASE_ID,
                                "search_type": search_type_label,
                                "top_k": top_k
                            }
                            st.rerun()

                        try:
                            rewritten_query = rewrite_query_from_history(
                                user_query=user_query,
                                messages=st.session_state.messages,
                                model_id=CHAT_MODEL_ID
                            )
                            if rewritten_query == "NEED_CLARIFICATION":
                                ai_answer = (
                                    "どの回答を指しているか確認させてください。"
                                    "直前の回答でしょうか、それともこの会話の最初の回答でしょうか。"
                                )
                                response_placeholder.markdown(ai_answer)

                                st.session_state.messages.append({
                                    "role": "assistant",
                                    "content": ai_answer
                                })
                                st.session_state.rag_debug_info[assistant_message_index] = {
                                    "message_type": message_type,
                                    "original_query": user_query,
                                    "rewritten_query": "",
                                    "reference_label": reference_info["label"],
                                    "reference_answer": reference_info["content"],
                                    "reference_message_indexes": reference_info["message_indexes"],
                                    "knowledge_base_id": KNOWLEDGE_BASE_ID,
                                    "search_type": search_type_label,
                                    "top_k": top_k
                                }
                                st.rerun()

                            rag_input_text = rewritten_query
                        except Exception:
                            rewritten_query = user_query
                            rag_input_text = user_query

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
                        "modelArn": CHAT_MODEL_ID,
                        "retrievalConfiguration": {
                            "vectorSearchConfiguration": {
                                "numberOfResults": top_k,
                                "overrideSearchType": search_type_label
                            }
                        },
                        "generationConfiguration": {
                            "inferenceConfig": {
                                "textInferenceConfig": {
                                    "maxTokens": max_tokens
                                }
                            },
                            "promptTemplate": {
                                "textPromptTemplate": (
                                    "あなたは大学の奨学金業務のベテラン職員です。"
                                    "提供された検索結果（マニュアルや規程の資料）を最優先の根拠として回答してください。"
                                    "資料に記載されていない内容は推測してはいけません。"
                                    "【重要な指示】\n"
                                    "1. 検索結果の資料内に、必要書類の名前や対象者の条件が断片的にでも記載されている場合は、"
                                    "見つかった書類名や条件をすべて漏れなく箇条書きで出力してください。\n"
                                    "2. 資料に記載されている具体的な書類名は省略せず、正式名称のまま出力してください。\n"
                                    "3. 資料に書かれていない内容は推測しないでください。\n"
                                    "4. ユーザーの元の質問が過去の会話を参照している場合は、"
                                    "検索用に具体化された質問をもとに、元の質問への自然な回答として出力してください。\n"
                                    "5. 書類や制度が複数ある場合は、それぞれの提出先や条件を対応関係が分かる形で列挙してください。\n"
                                    "6. Knowledge Baseに情報がない項目は、存在するように推測しないでください。\n"
                                    "7. 一部だけ情報が見つかった場合は、見つかった項目と見つからなかった項目を分けて回答してください。\n"
                                    "8. 検索結果に情報が存在しない場合でも、参照対象となる会話履歴に明示されている事実は、"
                                    "Knowledge Baseの内容と矛盾しない範囲で回答に含めてください。\n"
                                    "9. ただし、会話履歴にない内容やKnowledge Baseに反する内容を推測してはいけません。\n"
                                    "10. Knowledge Baseと過去回答が矛盾する場合はKnowledge Baseを優先してください。\n"
                                    "11. 提出先が大学窓口と日本学生支援機構郵送で異なる場合は、明確に区別してください。\n\n"
                                    f"ユーザーの元の質問: {user_query}\n\n"
                                    f"参照対象assistant回答:\n{reference_info['context']}\n\n"
                                    "検索結果:\n$search_results$\n\n"
                                    "検索用に具体化された質問: $query$"
                                )
                            }
                        }
                    }

                    if aws_filter:
                        kb_config["retrievalConfiguration"]["vectorSearchConfiguration"]["filter"] = aws_filter

                    retrieve_params = {
                        "input": {"text": rag_input_text},
                        "retrieveAndGenerateConfiguration": {
                            "type": "KNOWLEDGE_BASE",
                            "knowledgeBaseConfiguration": kb_config
                        }
                    }
                    if use_chat_history and st.session_state.rag_session_id:
                        retrieve_params["sessionId"] = st.session_state.rag_session_id

                    response = bedrock_agent_runtime.retrieve_and_generate(**retrieve_params)

                    if use_chat_history and "sessionId" in response:
                        st.session_state.rag_session_id = response["sessionId"]
                    if not use_chat_history:
                        st.session_state.rag_session_id = None

                    ai_answer = response["output"]["text"]

                response_placeholder.markdown(ai_answer)

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": ai_answer
                })
                st.session_state.rag_debug_info[assistant_message_index] = {
                    "message_type": message_type,
                    "original_query": user_query,
                    "rewritten_query": rewritten_query if message_type == "CONTEXTUAL_RAG" else "",
                    "reference_label": reference_info["label"],
                    "reference_answer": reference_info["content"],
                    "reference_message_indexes": reference_info["message_indexes"],
                    "knowledge_base_id": KNOWLEDGE_BASE_ID,
                    "search_type": search_type_label,
                    "top_k": top_k
                }

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

    st.subheader("💾 フィードバックCSV出力")
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

# ==========================================
#  メニュー4：PDFメタデータ生成ツール
# ==========================================
elif page == "🧾 PDFメタデータ生成":
    st.title("🧾 PDF ➡ Bedrock Knowledge Base メタデータ生成")
    st.write(
        "PDFを複数アップロードすると、Claude Sonnetで内容を解析し、"
        "Bedrock Knowledge Base用の `.metadata.json` を一括生成します。"
    )

    st.info(
        "115件のような大量PDFにも対応できるよう、複数ファイルを順番に処理し、"
        "最後にZIPで一括ダウンロードします。処理時間やBedrockのレート制限を考慮し、"
        "まずは10〜20件程度で試験することを推奨します。"
    )

    model_id = st.text_input(
        "生成モデルID",
        value="jp.anthropic.claude-sonnet-4-6"
    )

    uploaded_pdfs = st.file_uploader(
        "PDFファイルをアップロードしてください（複数選択可）",
        type=["pdf"],
        accept_multiple_files=True
    )

    if uploaded_pdfs:
        st.write(f"アップロード数: {len(uploaded_pdfs)} 件")

        preview_df = pd.DataFrame([
            {
                "ファイル名": f.name,
                "サイズ(KB)": round(len(f.getvalue()) / 1024, 1)
            }
            for f in uploaded_pdfs
        ])
        st.dataframe(preview_df, use_container_width=True)

        if st.button("🚀 メタデータを一括生成", type="primary"):
            zip_buffer = io.BytesIO()
            results = []
            progress_bar = st.progress(0)
            status_area = st.empty()
            detail_area = st.container()

            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                total = len(uploaded_pdfs)

                for idx, uploaded_pdf in enumerate(uploaded_pdfs, start=1):
                    file_name = uploaded_pdf.name
                    status_area.info(f"{idx}/{total} 処理中: {file_name}")

                    try:
                        pdf_bytes = uploaded_pdf.getvalue()

                        pdf_text = extract_pdf_head_text(pdf_bytes, max_pages=5)

                        if not pdf_text:
                            raise ValueError("PDFからテキストを抽出できませんでした。画像PDFの可能性があります。")
                        
                        metadata, raw_response = generate_pdf_metadata_with_claude(
                            pdf_text=pdf_text,
                            file_name=file_name,
                            model_id=model_id
                        )

                        metadata_json = json.dumps(metadata, ensure_ascii=False, indent=2)
                        metadata_filename = f"{file_name}.metadata.json"

                        zip_file.writestr(metadata_filename, metadata_json)

                        attrs = metadata.get("metadataAttributes", {})
                        results.append({
                            "ファイル名": file_name,
                            "結果": "成功",
                            "document_type": attrs.get("document_type", ""),
                            "category": attrs.get("category", ""),
                            "business": attrs.get("business", ""),
                            "target_user": attrs.get("target_user", ""),
                            "summary": attrs.get("summary", "")
                        })

                        with detail_area.expander(f"✅ {file_name}"):
                            st.code(metadata_json, language="json")

                    except Exception as e:
                        error_metadata = {
                            "metadataAttributes": {
                                "document_type": "エラー",
                                "category": "未分類",
                                "business": "",
                                "system": "",
                                "school_type": "不明",
                                "target_user": "all",
                                "keywords": [],
                                "summary": "メタデータ生成時にエラーが発生しました。",
                                "source_file_name": file_name,
                                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "error_message": str(e)
                            }
                        }

                        error_json = json.dumps(error_metadata, ensure_ascii=False, indent=2)
                        zip_file.writestr(f"{file_name}.metadata.json", error_json)

                        results.append({
                            "ファイル名": file_name,
                            "結果": "エラー",
                            "document_type": "",
                            "category": "",
                            "business": "",
                            "target_user": "",
                            "summary": str(e)
                        })

                        with detail_area.expander(f"❌ {file_name}"):
                            st.error(str(e))
                            st.code(traceback.format_exc())

                    progress_bar.progress(idx / total)

            status_area.success("メタデータ生成が完了しました。")

            result_df = pd.DataFrame(results)
            st.subheader("処理結果")
            st.dataframe(result_df, use_container_width=True)

            zip_file_name = datetime.now().strftime("pdf_metadata_%Y%m%d%H%M%S.zip")

            st.download_button(
                label="💾 metadata.json一式をZIPでダウンロード",
                data=zip_buffer.getvalue(),
                file_name=zip_file_name,
                mime="application/zip"
            )
