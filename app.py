import streamlit as st
import boto3
import pandas as pd
import json
import io
import zipfile
import traceback 

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
    st.title("🎓 奨学金Q&A AIアシスタント")
    st.caption("東京理科大学の奨学金業務に関する質問に、規程ベースでお答えします。")

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

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # ユーザーからの質問入力
    if user_query := st.chat_input("例：学生寮に入っている場合の申請書類を教えてください"):
        with st.chat_message("user"):
            st.markdown(user_query)
        st.session_state.messages.append({"role": "user", "content": user_query})

        with st.chat_message("assistant"):
            response_placeholder = st.empty()
            try:
                # Amazon Bedrock ナレッジベースを呼び出し
                response = bedrock_agent_runtime.retrieve_and_generate(
                    input={'text': user_query},
                    retrieveAndGenerateConfiguration={
                        'type': 'KNOWLEDGE_BASE',
                        'knowledgeBaseConfiguration': {
                            'knowledgeBaseId': KNOWLEDGE_BASE_ID,
                            # ⭕ 長いARNではなく、日本国内専用の「推論プロファイルID」をダイレクトに指定しました！
                            'modelArn': 'jp.anthropic.claude-sonnet-4-6'
                        }
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
                # メモリ上にZIPファイルを展開する準備
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    
                    for index, row in df.iterrows():
                        # セルが空の場合の対策を考慮しつつ文字列化
                        qa_id = str(row.get('QAID', index))
                        category = str(row.get('分類', '未分類'))
                        question = str(row.get('質問（回答用）', ''))
                        answer = str(row.get('回答1', ''))
                        tags = str(row.get('タグ', ''))
                        
                        # ユーザー属性の判定
                        target_users = []
                        if str(row.get('学生', '')).strip() in ['○', '◯']: target_users.append('student')
                        if str(row.get('教員', '')).strip() in ['○', '◯']: target_users.append('teacher')
                        if str(row.get('職員', '')).strip() in ['○', '◯']: target_users.append('staff')
                        user_type_str = ", ".join(target_users) if target_users else "all"

                        # ① 本文ファイル（Markdown）の作成
                        markdown_content = f"# 【分類：{category}】{question}\n\n## 質問\n{question}\n\n## 回答\n{answer}\n\n## 属性・タグ\n- タグ: {tags}\n- 対象者: {user_type_str}\n"
                        txt_filename = f"qa_{qa_id}.txt"
                        zip_file.writestr(txt_filename, markdown_content)

                        # ② メタデータファイル（JSON）の作成
                        metadata = {
                            "metadataAttributes": {
                                "document_type": "QA",
                                "category": category,
                                "user_type": user_type_str,
                                "qa_id": qa_id
                            }
                        }
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
