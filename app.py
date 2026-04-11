import streamlit as st
from supabase import create_client, Client
import json
import re
import os
import random
import copy
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import streamlit.components.v1 as components
import pandas as pd

# ==========================================
# 0. 화면 기본 설정 및 로그인 로직
# ==========================================
st.set_page_config(page_title="사설 족보닷컴", layout="wide")

# 사용할 비밀번호 설정 (원하는 비밀번호로 변경하세요)
APP_PASSWORD = st.secrets["APP_PASSWORD"]

def check_password():
    """비밀번호 검증 로직"""
    def password_entered():
        if st.session_state["password"] == APP_PASSWORD:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # 보안을 위해 세션에서 비밀번호 평문 삭제
        else:
            st.session_state["password_correct"] = False

    # 아직 인증되지 않았거나 첫 접속인 경우
    if "password_correct" not in st.session_state:
        st.title("사설 족보닷컴")
        st.text_input("우리가 누구?", type="password", on_change=password_entered, key="password")
        return False
        
    # 비밀번호가 틀린 경우
    elif not st.session_state["password_correct"]:
        st.title("사설 족보닷컴")
        st.text_input("우리가 누구?", type="password", on_change=password_entered, key="password")
        st.error("다시 한번 잘 생각하기")
        return False
        
    # 비밀번호가 맞는 경우
    else:
        return True

# 인증 실패 시 st.stop()을 호출하여 아래쪽 코드(데이터베이스 연동 등)가 아예 실행되지 않도록 차단
if not check_password():
    st.stop()

# ==========================================
# 1. Supabase 연동 설정 (본인 정보로 수정)
# ==========================================
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 2. 유틸리티 함수
# ==========================================
def extract_json_from_ai(text):
    """AI 답변에서 마크다운 및 사족을 제거하고 JSON 배열만 추출"""
    markdown_pattern = r'```(json)?\s*(.*?)\s*```'
    match = re.search(markdown_pattern, text, re.DOTALL | re.IGNORECASE)
    
    if match:
        json_str = match.group(1)
    else:
        array_pattern = r'\[\s*\{.*\}\s*\]'
        match_fallback = re.search(array_pattern, text, re.DOTALL)
        json_str = match_fallback.group(0) if match_fallback else ""
    
    try:
        return json.loads(json_str)
    except Exception:
        return None

def register_fonts():
    """PDF 조판을 위한 Pretendard 폰트 등록"""
    if os.path.exists('Pretendard-Regular.ttf') and os.path.exists('Pretendard-Bold.ttf'):
        pdfmetrics.registerFont(TTFont('Pretendard', 'Pretendard-Regular.ttf'))
        pdfmetrics.registerFont(TTFont('Pretendard-Bold', 'Pretendard-Bold.ttf'))
        return True
    return False

def create_exam_pdf(questions, filename, answer_mode, exam_title="기출 모의고사", subject_title="", topic_title=""):
    """선택된 문제 리스트를 2단 A4 PDF로 렌더링 (시험 제목 및 과목/주제 추가)"""
    if not register_fonts():
        return "에러: 'Pretendard-Regular.ttf' 및 'Pretendard-Bold.ttf' 폰트 파일이 같은 폴더에 없습니다."

    # 스타일 정의
    style_title = ParagraphStyle('Title', fontName='Pretendard-Bold', fontSize=18, alignment=1, spaceAfter=20)
    style_normal = ParagraphStyle('Normal', fontName='Pretendard', fontSize=10, leading=15)
    style_bold = ParagraphStyle('Bold', fontName='Pretendard-Bold', fontSize=11, leading=16, spaceAfter=6)
    style_exp = ParagraphStyle('Exp', fontName='Pretendard', fontSize=9, leading=14, textColor='#0055A4')
    
    margin = 1.5 * cm
    col_width = (A4[0] - 2 * margin - 1 * cm) / 2
    col_height = A4[1] - 2 * margin - 1 * cm
    
    frame_left = Frame(margin, margin, col_width, col_height, id='left')
    frame_right = Frame(margin + col_width + 1 * cm, margin, col_width, col_height, id='right')
    
    doc = BaseDocTemplate(filename, pagesize=A4)
    doc.addPageTemplates([PageTemplate(id='TwoCol', frames=[frame_left, frame_right])])

    story = []
    
    # [수정] 시험지 최상단 제목 + 과목 및 주제 추가
    title_text = exam_title
    if subject_title or topic_title:
        title_text += f"<br/><font size='11' color='#666666'>{subject_title} | {topic_title}</font>"
    story.append(Paragraph(title_text, style_title))

    def render_question(i, q):
        content_text = q['content'] if q.get('content') else ""
        content_text = re.sub(r'(\[이미지 설명:.*?\])', r'<font color="#555555" size="9">\1</font>', content_text)
        
        sub_author_text = f" <font size='10' color='#555555'>({q['sub_author']})</font>" if q.get('sub_author') else ""
        paragraph_text = f"<b>{i+1}.</b>{sub_author_text}<br/>{content_text}"
        story.append(Paragraph(paragraph_text, style_bold))
        
        if q.get('options') and isinstance(q['options'], dict):
            circles = {"1": "①", "2": "②", "3": "③", "4": "④", "5": "⑤"}
            for key, val in q['options'].items():
                num_bullet = circles.get(str(key), f"{key})")
                story.append(Paragraph(f"{num_bullet} {val}", style_normal))
        story.append(Spacer(1, 0.3 * cm))

    # --- 해설 출력 로직 (동일) ---
    if answer_mode == "문제마다 해설":
        for i, q in enumerate(questions):
            render_question(i, q)
            answer_text = q['answer'] if q.get('answer') else "없음"
            story.append(Paragraph(f"[정답] {answer_text}", style_exp))
            if q.get('explanation'):
                story.append(Paragraph(f"[해설] {q['explanation']}", style_exp))
            story.append(Spacer(1, 1 * cm))

    elif answer_mode == "마지막에 해설":
        for i, q in enumerate(questions):
            render_question(i, q)
            story.append(Spacer(1, 0.7 * cm))
        
        story.append(PageBreak())
        
        story.append(Paragraph("<b>[정답 및 해설]</b>", style_bold))
        story.append(Spacer(1, 0.5 * cm))
        for i, q in enumerate(questions):
            answer_text = q['answer'] if q.get('answer') else "없음"
            story.append(Paragraph(f"<b>{i+1}번 정답:</b> {answer_text}", style_exp))
            if q.get('explanation'):
                story.append(Paragraph(f"<b>해설:</b> {q['explanation']}", style_exp))
            story.append(Spacer(1, 0.5 * cm))

    try:
        doc.build(story)
        return "성공"
    except Exception as e:
        return f"PDF 빌드 중 에러 발생: {e}"

# ==========================================
# 3. Streamlit 화면 (UI) 설정
# ==========================================
st.set_page_config(page_title="사설 족보닷컴", layout="wide")
st.title("사설 족보닷컴")

menu = st.sidebar.selectbox("메뉴", ["문제 추가하기", "문제 조회 및 PDF 생성", "통계 및 현황", "스마트 학습", "주관식 출제 예측"])

# ------------------------------------------
# 메뉴 1: 문제 추가하기
# ------------------------------------------
if menu == "문제 추가하기":
    st.header("📝 AI 추출 데이터 입력")
    # [추가] 이번에 저장할 데이터의 시험 이름 지정
    exam_name_input = st.text_input("현재 입력하는 데이터의 시험 명칭 (예: 본1-1 중간)")
    
    ai_input = st.text_area("AI 답변 붙여넣기", placeholder="AI가 변환한 JSON 답변 전체를 붙여넣으세요. AI 답변의 사족은 자동으로 걸러집니다.", height=300)
    
    if st.button("데이터베이스에 저장"):
        if not exam_name_input.strip():
            st.error("시험 명칭을 입력하세요.")
        elif ai_input.strip():
            data = extract_json_from_ai(ai_input)
            if data:
                # [핵심] 추출된 모든 문제 객체에 exam_name을 주입
                for item in data:
                    item['exam_name'] = exam_name_input
                
                try:
                    supabase.table("questions").insert(data).execute()
                    st.success(f"'{exam_name_input}' 항목으로 {len(data)}개의 문제가 저장되었습니다.")
                except Exception as e:
                    st.error(f"DB 저장 오류: {e}")

# ------------------------------------------
# 메뉴 2: 문제 조회 및 PDF 생성
# ------------------------------------------
elif menu == "문제 조회 및 PDF 생성":
    st.header("🔍 시험, 주제 및 출처별 문제 필터링")
    
    # 0. 저장된 모든 시험 이름(exam_name) 가져오기
    try:
        exam_data = supabase.table("questions").select("exam_name").execute().data
        exams = sorted(list(set([d['exam_name'] for d in exam_data if d.get('exam_name')])))
    except Exception as e:
        st.error(f"DB 연결 실패: {e}")
        exams = []

    # 화면 최상단: 시험 선택
    selected_exam = st.selectbox("🎯 시험 선택", ["시험을 선택하세요"] + exams)

    filtered_questions = []

    if selected_exam != "시험을 선택하세요":
        # 1. 선택된 시험에 해당하는 과목 리스트 가져오기
        try:
            subject_data = supabase.table("questions").select("subject").eq("exam_name", selected_exam).execute().data
            subjects = sorted(list(set([d['subject'] for d in subject_data if d.get('subject')])))
        except Exception as e:
            subjects = []

        # 화면 상단 필터 레이아웃 (기존 디자인 유지)
        col_filter1, col_filter2 = st.columns(2)
        with col_filter1:
            selected_subject = st.selectbox("1️⃣ 과목 선택", ["과목을 선택하세요"] + subjects)
        with col_filter2:
            source_filter = st.selectbox(
                "2️⃣ 출처 필터", 
                ["모든 문제", "족보 문제만", "족보 제외"]
            )

        if selected_subject != "과목을 선택하세요":
            # 2. 선택된 시험, 과목 및 출처 조건에 맞는 주제(Topic) 리스트 가져오기
            topic_query = supabase.table("questions").select("topic").eq("exam_name", selected_exam).eq("subject", selected_subject)
            
            # 출처 필터에 따른 topic_query 조건 추가
            if source_filter == "족보 문제만":
                topic_query = topic_query.eq("author", "족보")
            elif source_filter == "족보 제외":
                topic_query = topic_query.neq("author", "족보")

            try:
                topic_data = topic_query.execute().data
                topics = sorted(list(set([d['topic'] for d in topic_data if d.get('topic')])))
            except:
                topics = []

            # 주제 선택 (멀티)
            selected_topics = st.multiselect(f"3️⃣ '{selected_subject}'의 주제 선택 (복수 선택 가능)", topics)

            if selected_topics:
                # 3. 최종 문제 데이터 쿼리
                final_query = supabase.table("questions").select("*").eq("exam_name", selected_exam).eq("subject", selected_subject).in_("topic", selected_topics)
                
                # 출처 필터에 따른 final_query 조건 추가
                if source_filter == "족보 문제만":
                    final_query = final_query.eq("author", "족보")
                elif source_filter == "족보 제외":
                    final_query = final_query.neq("author", "족보")
                    
                filtered_questions = final_query.execute().data
            else:
                if topics:
                    st.info("주제를 하나 이상 선택해 주세요.")
                else:
                    st.warning("해당 과목/출처 조건에 등록된 주제가 없습니다.")
    
    if filtered_questions:
        st.write(f"✅ 조건에 맞는 문제: 총 **{len(filtered_questions)}**개")
        st.dataframe(filtered_questions, use_container_width=True)
        
        # (기존 코드) st.dataframe(filtered_questions, use_container_width=True) 
        # 이 아래 부분부터 교체합니다!
        
        st.subheader("📄 PDF 생성 옵션")
        col_opt1, col_opt2 = st.columns(2)
        
        with col_opt1:
            answer_mode = st.radio("해설 배치 방식", ["마지막에 해설", "문제마다 해설"], horizontal=True)
            
            # [추가] 취약점 우선 추출 로직
            sort_mode = st.radio("문제 정렬/추출 방식", ["랜덤 섞기", "내 취약점 우선 추출 (오답 위주)"], horizontal=True)
            if sort_mode == "내 취약점 우선 추출 (오답 위주)":
                pdf_username = st.text_input("학습자 닉네임", placeholder="기록을 불러올 닉네임 입력")
            else:
                pdf_username = ""
        
        with col_opt2:
            num_preset = st.radio("출력 문제 수", ["전체", "20문제", "직접 설정"], horizontal=True)
            custom_num = len(filtered_questions)
            if num_preset == "직접 설정":
                custom_num = st.number_input("문제 수 입력", min_value=1, max_value=len(filtered_questions), value=min(20, len(filtered_questions)))
            
            # [추가] 선지 섞기 옵션
            shuffle_options = st.checkbox("🎲 각 문제의 선지(①~⑤) 내용 무작위로 섞기", value=True)
            if shuffle_options:
                st.caption("※ 섞인 선지에 맞춰 정답 번호도 자동으로 보정됩니다.")

        if st.button("PDF 시험지 생성하기", type="primary"):
            filename = "Exam_Paper.pdf"
            
            # 원본 데이터 보호를 위해 깊은 복사(Deepcopy) 수행
            final_list = copy.deepcopy(filtered_questions)
            
            with st.spinner('문제를 분석하고 조판을 준비 중입니다...'):
                
                # 1. 문제 정렬 (취약점 기반 OR 랜덤)
                if sort_mode == "내 취약점 우선 추출 (오답 위주)" and pdf_username.strip():
                    logs_res = supabase.table("study_logs").select("question_id, is_correct, studied_at").eq("username", pdf_username).execute()
                    stats = {}
                    for log in logs_res.data:
                        qid = log['question_id']
                        if qid not in stats: stats[qid] = {'attempts': 0, 'correct': 0, 'last_studied': log['studied_at']}
                        stats[qid]['attempts'] += 1
                        if log['is_correct']: stats[qid]['correct'] += 1
                        if log['studied_at'] > stats[qid]['last_studied']: stats[qid]['last_studied'] = log['studied_at']
                    
                    for q in final_list:
                        qid = q['id']
                        if qid in stats:
                            q['sort_accuracy'] = stats[qid]['correct'] / stats[qid]['attempts']
                            q['sort_last_studied'] = stats[qid]['last_studied']
                        else:
                            q['sort_accuracy'] = -1.0 # 안 푼 문제 최우선
                            q['sort_last_studied'] = '0000-00-00'
                    # 오답률 높고 오래된 순으로 정렬
                    final_list.sort(key=lambda x: (x['sort_accuracy'], x['sort_last_studied']))
                else:
                    random.shuffle(final_list)
                
                # 2. 개수 자르기
                if num_preset == "20문제": final_list = final_list[:20]
                elif num_preset == "직접 설정": final_list = final_list[:custom_num]

                # [선택] 취약점 추출 후 잘린 리스트 안에서 다시 한번 순서 섞기
                if sort_mode == "내 취약점 우선 추출 (오답 위주)":
                    random.shuffle(final_list)

                # 3. [핵심] 선지 무작위 섞기 및 정답 번호 재매핑
                if shuffle_options:
                    for q in final_list:
                        if q.get('question_type') == 'MCQ' and isinstance(q.get('options'), dict):
                            orig_ans = str(q.get('answer', ''))
                            options_dict = q['options']
                            
                            # 기존 정답이 가리키던 실제 텍스트 내용을 추출
                            correct_text = options_dict.get(orig_ans, orig_ans)
                            
                            # 선지 값들만 모아서 섞기
                            vals = list(options_dict.values())
                            random.shuffle(vals)
                            
                            # 1~5번으로 새 딕셔너리 구성
                            new_options = {str(k+1): v for k, v in enumerate(vals)}
                            q['options'] = new_options
                            
                            # 섞인 선지 중에서 정답 텍스트가 몇 번으로 갔는지 찾아서 정답 업데이트
                            for k, v in new_options.items():
                                if v == correct_text:
                                    q['answer'] = k
                                    break
                
                # 4. 타이틀 정리 및 PDF 생성
                topic_title_str = ", ".join(selected_topics) if len(selected_topics) <= 3 else f"{selected_topics[0]} 등 {len(selected_topics)}개 주제"
                result = create_exam_pdf(final_list, filename, answer_mode, exam_title=selected_exam, subject_title=selected_subject, topic_title=topic_title_str)
                
            if result == "성공":
                st.success("PDF 생성이 완료되었습니다!")
                with open(filename, "rb") as pdf_file:
                    st.download_button(
                        label="📥 만들어진 시험지 다운로드",
                        data=pdf_file,
                        file_name=f"{selected_exam}_{selected_subject}_{len(final_list)}제.pdf",
                        mime="application/pdf"
                    )
            else:
                st.error(result)
                
# ------------------------------------------
# 메뉴 3: 통계 및 현황
# ------------------------------------------
elif menu == "통계 및 현황":
    st.header("📊 주제 및 출처별 문제 통계")
    st.info("현재 데이터베이스에 적재된 문제들의 현황을 한눈에 파악합니다.")

    try:
        # [수정] 1000개 제한을 우회하여 전체 데이터를 가져오는 페이지네이션 로직
        all_meta = []
        start = 0
        limit = 1000
        
        while True:
            # 1000개씩 구간을 나누어 요청
            response = supabase.table("questions").select("exam_name, subject, topic, author, sub_author").range(start, start + limit - 1).execute()
            data = response.data
            
            if not data:
                break
                
            all_meta.extend(data)
            
            # 받아온 데이터가 1000개 미만이면 마지막 페이지라는 뜻이므로 반복 중단
            if len(data) < limit:
                break
                
            start += limit
            
    except Exception as e:
        st.error(f"DB 연결 실패: {e}")
        all_meta = []

    if all_meta:
        col_stat1, col_stat2 = st.columns(2)
        # (이하 기존 코드 동일: exams = sorted(list(set... 부터 끝까지))
        
        # 필터링 요소 추출
        exams = sorted(list(set([d.get('exam_name') for d in all_meta if d.get('exam_name')])))
        with col_stat1:
            stat_exam = st.selectbox("🎯 시험 선택", ["전체보기"] + exams)
            
        filtered_stat_data = all_meta
        if stat_exam != "전체보기":
            filtered_stat_data = [d for d in filtered_stat_data if d.get('exam_name') == stat_exam]

        subjects = sorted(list(set([d.get('subject') for d in filtered_stat_data if d.get('subject')])))
        with col_stat2:
            stat_subject = st.selectbox("1️⃣ 과목 선택", ["전체보기"] + subjects)
            
        if stat_subject != "전체보기":
            filtered_stat_data = [d for d in filtered_stat_data if d.get('subject') == stat_subject]

        if filtered_stat_data:
            # 통계 데이터 계산 (Dictionary 활용)
            stats_dict = {}
            for row in filtered_stat_data:
                t = row.get('topic') or "미분류 주제"
                
                # [수정된 부분] 열(Column)의 분류 기준을 author로 고정
                category = row.get('author') or "미분류 출처"
                
                if t not in stats_dict:
                    stats_dict[t] = {'총합': 0}
                    
                stats_dict[t]['총합'] += 1
                
                if category not in stats_dict[t]:
                    stats_dict[t][category] = 0
                stats_dict[t][category] += 1

            # Pandas 데이터프레임으로 변환 및 정렬
            df = pd.DataFrame.from_dict(stats_dict, orient='index').fillna(0).astype(int)
            
            # 컬럼 순서 정리 ('총합'을 맨 앞으로)
            cols = ['총합'] + sorted([c for c in df.columns if c != '총합'])
            df = df[cols]
            # 총합이 많은 주제부터 내림차순 정렬
            df = df.sort_values(by='총합', ascending=False)
            
            st.write(f"총 **{len(filtered_stat_data)}** 문항 요약 표")
            st.dataframe(df, use_container_width=True)
            
            # 간단한 바 차트 제공 (총합 기준)
            st.subheader("📈 주제별 문항 수 차트")
            st.bar_chart(df['총합'])
            
        else:
            st.warning("해당 조건에 일치하는 문제가 없습니다.")
    else:
        st.info("데이터베이스에 등록된 문제가 없습니다.")


# ==========================================
# 메뉴 4: 스마트 학습 (답치기 모드)
# ==========================================
elif menu == "스마트 학습":
    st.header("🧠 개인별 맞춤 스마트 학습")
    
    col_user1, col_user2 = st.columns([1, 1])
    with col_user1:
        username = st.text_input("👤 학습자 닉네임", placeholder="기록용 닉네임")
    with col_user2:
        try:
            exam_data = supabase.table("questions").select("exam_name").execute().data
            exams = sorted(list(set([d['exam_name'] for d in exam_data if d.get('exam_name')])))
            selected_exam = st.selectbox("🎯 시험 선택", ["시험 선택"] + exams)
        except:
            selected_exam = "시험 선택"

    if username.strip() and selected_exam != "시험 선택":
        try:
            subject_data = supabase.table("questions").select("subject").eq("exam_name", selected_exam).execute().data
            subjects = sorted(list(set([d['subject'] for d in subject_data if d.get('subject')])))
        except:
            subjects = []
            
        selected_subject = st.selectbox("1️⃣ 과목 선택", ["과목 선택"] + subjects)
        
        if selected_subject != "과목 선택":
            topic_data = supabase.table("questions").select("topic").eq("exam_name", selected_exam).eq("subject", selected_subject).execute().data
            topics = sorted(list(set([d['topic'] for d in topic_data if d.get('topic')])))
            selected_topics = st.multiselect("2️⃣ 학습할 주제 선택 (다중 가능)", topics, default=topics)

            st.divider()
            col_opt1, col_opt2 = st.columns(2)
            with col_opt1:
                num_to_study = st.number_input("📝 학습할 문제 수", min_value=1, value=min(20, 100), step=5)
            with col_opt2:
                shuffle_distractors = st.checkbox("🎲 선지 순서 무작위 섞기", value=True)
            
            if st.button("🚀 맞춤 학습 시작", type="primary"):
                # 1. 문제 데이터 가져오기
                query = supabase.table("questions").select("*").eq("exam_name", selected_exam).eq("subject", selected_subject).in_("topic", selected_topics)
                questions_data = query.execute().data
                
                if not questions_data:
                    st.warning("선택한 조건에 맞는 문제가 없습니다.")
                else:
                    with st.spinner("🧠 학습 알고리즘이 내 취약점을 분석하고 있습니다..."):
                        # 2. 내 학습 기록(study_logs) 가져오기
                        logs_res = supabase.table("study_logs").select("question_id, is_correct, studied_at").eq("username", username).execute()
                        user_logs = logs_res.data
                        
                        # 3. 문제별 통계 계산
                        stats = {}
                        for log in user_logs:
                            qid = log['question_id']
                            if qid not in stats:
                                stats[qid] = {'attempts': 0, 'correct': 0, 'last_studied': log['studied_at']}
                            
                            stats[qid]['attempts'] += 1
                            if log['is_correct']:
                                stats[qid]['correct'] += 1
                            
                            if log['studied_at'] > stats[qid]['last_studied']:
                                stats[qid]['last_studied'] = log['studied_at']

                        # 4. 안키(Anki) 알고리즘 적용
                        for q in questions_data:
                            qid = q['id']
                            if qid in stats:
                                q['stats'] = stats[qid]
                                acc = stats[qid]['correct'] / stats[qid]['attempts']
                                q['sort_accuracy'] = acc
                                q['sort_last_studied'] = stats[qid]['last_studied']
                            else:
                                q['stats'] = {'attempts': 0, 'correct': 0, 'last_studied': 'Never'}
                                q['sort_accuracy'] = -1.0 
                                q['sort_last_studied'] = '0000-00-00' 

                        questions_data.sort(key=lambda x: (x['sort_accuracy'], x['sort_last_studied']))
                        study_list = questions_data[:int(num_to_study)]
                        random.shuffle(study_list)
                        
                        import json
                        questions_json = json.dumps(study_list).replace("</", "<\\/")
                        
                        # 5. HTML/JS 인터페이스
                        html_code = f"""
                        <!DOCTYPE html>
                        <html>
                        <head>
                            <script src="https://cdn.tailwindcss.com"></script>
                            <script src="https://unpkg.com/@supabase/supabase-js@2"></script>
                            <style>
                                .fade-in {{ animation: fadeIn 0.3s ease-in; }}
                                @keyframes fadeIn {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
                            </style>
                        </head>
                        <body class="bg-gray-50 p-4 font-sans">
                            <div id="app" class="max-w-3xl mx-auto bg-white rounded-xl shadow-lg p-6 border border-gray-100">
                                <div class="flex justify-between items-center mb-4">
                                    <div class="text-sm font-bold text-blue-600" id="progress-text">준비 중...</div>
                                    <div class="text-xs text-gray-400">{selected_subject} | {len(study_list)}문제</div>
                                </div>
                                <div class="w-full bg-gray-200 rounded-full h-2 mb-6">
                                    <div id="progress-bar" class="bg-blue-500 h-2 rounded-full transition-all duration-500" style="width: 0%"></div>
                                </div>

                                <div id="question-container" class="fade-in min-h-[200px]">
                                    <div class="flex justify-between items-center mb-2">
                                        <div id="q-topic" class="text-[10px] uppercase tracking-widest text-gray-400"></div>
                                        <div id="q-stats" class="flex space-x-2 text-xs font-bold"></div>
                                    </div>
                                    <h2 id="q-content" class="text-lg font-medium text-gray-800 mb-6 leading-relaxed"></h2>
                                    <div id="options-container" class="space-y-3 mb-6"></div>
                                    <button id="reveal-btn" class="hidden w-full bg-slate-800 text-white font-bold py-4 rounded-xl shadow-lg hover:bg-black transition">
                                        정답 확인하기
                                    </button>
                                </div>

                                <div id="explanation-container" class="hidden fade-in mt-8 p-5 bg-blue-50 rounded-xl border border-blue-100">
                                    <div class="flex items-start mb-3">
                                        <span class="text-blue-700 font-bold mr-2 whitespace-nowrap">🎯 정답:</span>
                                        <span id="exp-answer" class="text-blue-900 font-black"></span>
                                    </div>
                                    <p id="exp-text" class="text-gray-600 text-sm leading-relaxed mb-6 italic"></p>
                                    
                                    <div id="anki-buttons" class="hidden grid grid-cols-2 gap-4">
                                        <button onclick="handleAnswer(false)" class="bg-white border-2 border-red-200 text-red-500 font-bold py-3 rounded-xl hover:bg-red-50 transition">틀림 ❌</button>
                                        <button onclick="handleAnswer(true)" class="bg-white border-2 border-green-200 text-green-600 font-bold py-3 rounded-xl hover:bg-green-50 transition">맞춤 ⭕</button>
                                    </div>
                                    <button id="next-btn" onclick="nextQuestion()" class="hidden w-full bg-blue-600 text-white font-bold py-3 rounded-xl hover:bg-blue-700 transition">
                                        다음 문제로 넘어가기 →
                                    </button>
                                </div>

                                <div id="result-screen" class="hidden text-center fade-in py-12">
                                    <div class="text-5xl mb-4">🏆</div>
                                    <h2 class="text-2xl font-bold text-gray-800 mb-2">학습 완료!</h2>
                                    <p id="score-text" class="text-gray-600 mb-8"></p>
                                    <button onclick="window.location.reload()" class="text-blue-600 font-medium hover:underline">다른 과목 학습하기</button>
                                </div>
                            </div>

                            <script>
                                const supabaseClient = supabase.createClient('{SUPABASE_URL}', '{SUPABASE_KEY}');
                                const rawQuestions = {questions_json};
                                const username = '{username}';
                                const shouldShuffleOptions = {str(shuffle_distractors).lower()};
                                
                                let currentIndex = 0;
                                let correctCount = 0;
                                let logs = [];

                                function formatDateTime(dateStr) {{
                                    if(dateStr === 'Never') return '없음';
                                    const d = new Date(dateStr);
                                    return `${{d.getMonth()+1}}/${{d.getDate()}} ${{d.getHours()}}:${{String(d.getMinutes()).padStart(2, '0')}}`;
                                }}

                                function shuffleArray(array) {{
                                    for (let i = array.length - 1; i > 0; i--) {{
                                        const j = Math.floor(Math.random() * (i + 1));
                                        [array[i], array[j]] = [array[j], array[i]];
                                    }}
                                    return array;
                                }}

                                function loadQuestion() {{
                                    if (currentIndex >= rawQuestions.length) {{
                                        finishStudy();
                                        return;
                                    }}

                                    const q = rawQuestions[currentIndex];
                                    document.getElementById('explanation-container').classList.add('hidden');
                                    document.getElementById('options-container').innerHTML = '';
                                    document.getElementById('reveal-btn').classList.add('hidden');
                                    
                                    // 진행바 업데이트
                                    document.getElementById('progress-text').innerText = `STEP ${{currentIndex + 1}} / ${{rawQuestions.length}}`;
                                    document.getElementById('progress-bar').style.width = `${{(currentIndex / rawQuestions.length) * 100}}%`;

                                    // [수정1] 주제와 함께 출처(sub_author) 표시
                                    let topicDisplay = q.topic || 'GENERAL';
                                    if (q.sub_author) {{
                                        topicDisplay += ` <span class="mx-1 text-gray-300">|</span> <span class="text-indigo-400 font-bold">${{q.sub_author}}</span>`;
                                    }}
                                    document.getElementById('q-topic').innerHTML = topicDisplay;
                                    
                                    // 통계 뱃지 세팅
                                    const s = q.stats;
                                    let statHtml = "";
                                    if (s.attempts === 0) {{
                                        statHtml = `<span class="bg-purple-100 text-purple-700 px-2 py-1 rounded">🆕 새 문제</span>`;
                                    }} else {{
                                        const acc = Math.round((s.correct / s.attempts) * 100);
                                        let color = "red";
                                        if(acc >= 70) color = "green";
                                        else if(acc >= 40) color = "yellow";
                                        
                                        statHtml = `
                                            <span class="bg-${{color}}-100 text-${{color}}-800 px-2 py-1 rounded">정답률 ${{acc}}% (${{s.correct}}/${{s.attempts}})</span>
                                            <span class="bg-gray-100 text-gray-500 px-2 py-1 rounded hidden sm:inline">최근: ${{formatDateTime(s.last_studied)}}</span>
                                        `;
                                    }}
                                    document.getElementById('q-stats').innerHTML = statHtml;

                                    // 본문 렌더링
                                    document.getElementById('q-content').innerHTML = (q.content || '').replace(/(\[이미지 설명:.*?\])/g, '<br><span class="text-xs text-gray-400 italic">$1</span>');

                                    if (q.question_type === 'MCQ' && q.options) {{
                                        let entries = Object.entries(q.options);
                                        if (shouldShuffleOptions) entries = shuffleArray(entries);

                                        entries.forEach(([key, val]) => {{
                                            const btn = document.createElement('button');
                                            btn.className = "w-full text-left p-4 border-2 border-gray-100 rounded-xl hover:border-blue-300 hover:bg-blue-50 transition font-medium text-gray-700 shadow-sm";
                                            btn.innerHTML = val;
                                            btn.onclick = () => checkMcq(key, val, btn, q);
                                            document.getElementById('options-container').appendChild(btn);
                                        }});
                                    }} else {{
                                        document.getElementById('reveal-btn').classList.remove('hidden');
                                        document.getElementById('reveal-btn').onclick = () => showExp(q, true);
                                    }}
                                }}

                                function checkMcq(selectedKey, selectedVal, btn, q) {{
                                    Array.from(document.getElementById('options-container').children).forEach(b => b.disabled = true);
                                    
                                    const isCorrect = (selectedKey === q.answer || selectedVal === q.answer);
                                    
                                    if (isCorrect) {{
                                        btn.classList.replace('border-gray-100', 'border-green-500');
                                        btn.classList.add('bg-green-50', 'text-green-700');
                                        correctCount++;
                                    }} else {{
                                        btn.classList.replace('border-gray-100', 'border-red-500');
                                        btn.classList.add('bg-red-50', 'text-red-700');
                                    }}
                                    
                                    logs.push({{ username, question_id: q.id, is_correct: isCorrect, studied_at: new Date().toISOString() }});
                                    showExp(q, false);
                                }}

                                function showExp(q, isShortAnswer) {{
                                    document.getElementById('reveal-btn').classList.add('hidden');
                                    const expDiv = document.getElementById('explanation-container');
                                    expDiv.classList.remove('hidden');
                                    
                                    // [수정2] 정답 번호 대신 선지의 실제 텍스트 내용을 가져오기
                                    let answerText = q.answer || "없음";
                                    if (q.question_type === 'MCQ' && q.options && q.options[q.answer]) {{
                                        answerText = q.options[q.answer];
                                    }}
                                    document.getElementById('exp-answer').innerHTML = answerText;
                                    
                                    document.getElementById('exp-text').innerText = q.explanation || "별도의 해설이 등록되지 않았습니다.";
                                    
                                    if (isShortAnswer) {{
                                        document.getElementById('anki-buttons').classList.remove('hidden');
                                        document.getElementById('next-btn').classList.add('hidden');
                                    }} else {{
                                        document.getElementById('anki-buttons').classList.add('hidden');
                                        document.getElementById('next-btn').classList.remove('hidden');
                                    }}
                                }}

                                function handleAnswer(isCorrect) {{
                                    if (isCorrect) correctCount++;
                                    logs.push({{ username, question_id: rawQuestions[currentIndex].id, is_correct: isCorrect, studied_at: new Date().toISOString() }});
                                    nextQuestion();
                                }}

                                function nextQuestion() {{
                                    currentIndex++;
                                    loadQuestion();
                                }}

                                async function finishStudy() {{
                                    document.getElementById('question-container').classList.add('hidden');
                                    document.getElementById('explanation-container').classList.add('hidden');
                                    document.getElementById('progress-bar').style.width = '100%';
                                    
                                    document.getElementById('result-screen').classList.remove('hidden');
                                    document.getElementById('score-text').innerHTML = `성취도: <b>${{correctCount}} / ${{rawQuestions.length}}</b><br>데이터베이스에 학습 기록을 전송했습니다.`;

                                    if (logs.length > 0) {{
                                        await supabaseClient.from('study_logs').insert(logs);
                                    }}
                                }}

                                loadQuestion();
                            </script>
                        </body>
                        </html>
                        """
                        components.html(html_code, height=750, scrolling=True)
    else:
        st.info("닉네임을 입력하고 시험을 선택하면 학습이 시작됩니다.")

# ------------------------------------------
# 메뉴 5: 주관식 출제 예측 및 PDF 생성 (빈출순 정렬 옵션 추가)
# ------------------------------------------
elif menu == "주관식 출제 예측":
    st.header("🔮 주관식 출제 예측 및 통합 PDF 생성")
    st.info("A형(빈출 통합) 원리로 문제를 예측하고, 기존 족보와 합쳐 체계적인 PDF를 생성합니다.")

    # 1. 필터링 설정
    try:
        exam_data = supabase.table("questions").select("exam_name").execute().data
        exams = sorted(list(set([d['exam_name'] for d in exam_data if d.get('exam_name')])))
        selected_exam = st.selectbox("🎯 대상 시험 선택", ["시험 선택"] + exams, key="predict_exam")
    except:
        selected_exam = "시험 선택"

    if selected_exam != "시험 선택":
        try:
            subject_data = supabase.table("questions").select("subject").eq("exam_name", selected_exam).execute().data
            subjects = sorted(list(set([d['subject'] for d in subject_data if d.get('subject')])))
        except:
            subjects = []
            
        selected_subject = st.selectbox("1️⃣ 대상 과목 선택", subjects, key="predict_sub")

        # 2. 문제 생성 옵션
        st.divider()
        st.subheader("⚙️ 문제 생성 및 PDF 옵션")
        col_gen1, col_gen2 = st.columns(2)
        
        with col_gen1:
            use_a_type = st.checkbox("✅ A형: 빈출 정답 통합형 (힌트 모음)", value=True)
            include_original = st.checkbox("✅ 기존 주관식 족보 포함", value=True)
            # [추가] 정렬 옵션 추가
            a_type_sort = st.radio("A형 예상 문제 정렬 방식", ["빈출순 (자주 출제된 순서)", "무작위 섞기 (실전 모드)"], horizontal=True)
        
        with col_gen2:
            answer_mode = st.radio("해설 배치 방식", ["마지막에 해설", "문제마다 해설"], horizontal=True, key="predict_ans")
            max_predict = st.number_input("생성할 A형 문제 수", min_value=5, max_value=100, value=20)

        if st.button("🔮 주관식 마스터 PDF 생성하기", type="primary"):
            with st.spinner("데이터를 분석하여 문제를 재구성 중입니다..."):
                # 데이터 로드
                all_data = supabase.table("questions").select("*").eq("exam_name", selected_exam).eq("subject", selected_subject).execute().data
                
                mcqs = [q for q in all_data if q['question_type'] == 'MCQ']
                original_shorts = [q for q in all_data if q['question_type'] != 'MCQ']
                
                # 유형별 리스트 초기화
                a_type_list = []
                final_original_list = []

                # --- [A형] 빈출 정답 통합형 로직 ---
                if use_a_type and mcqs:
                    answer_map = {}
                    for q in mcqs:
                        ans_key = str(q.get('answer', ''))
                        opts = q.get('options', {})
                        actual_ans = opts.get(ans_key, ans_key) if isinstance(opts, dict) else ans_key
                        actual_ans = str(actual_ans).strip()
                        
                        if len(actual_ans) >= 2 and not actual_ans.isdigit():
                            if actual_ans not in answer_map: answer_map[actual_ans] = []
                            answer_map[actual_ans].append(q)
                    
                    # 가장 많이 출제된 순서대로 정렬
                    sorted_a = sorted([item for item in answer_map.items() if len(item[1]) >= 2], key=lambda x: len(x[1]), reverse=True)
                    
                    for ans_text, q_list in sorted_a[:max_predict]:
                        hints = ""
                        for idx, q in enumerate(q_list):
                            clean_c = re.sub(r'(\[이미지 설명:.*?\])', '', q.get('content', ''))
                            hints += f"- 힌트 {idx+1}: {clean_c}<br/>"
                        
                        a_type_list.append({
                            'content': f"[A형: 개념 통합] 다음 설명들이 공통적으로 가리키는 것을 쓰시오.<br/><br/>{hints}",
                            'answer': ans_text,
                            'explanation': f"객관식에서 총 {len(q_list)}회 정답으로 출제된 핵심 키워드입니다.",
                            'sub_author': "AI 예상(A형)"
                        })
                    
                    # [적용] 사용자가 무작위 섞기를 선택한 경우에만 셔플 실행 (빈출순 선택 시 원본 sorted_a 순서 유지)
                    if a_type_sort == "무작위 섞기 (실전 모드)":
                        random.shuffle(a_type_list)

                # --- 기존 주관식 정리 ---
                if include_original:
                    for q in original_shorts:
                        q_copy = copy.deepcopy(q)
                        q_copy['sub_author'] = f"{q_copy.get('sub_author', '')} (기존 족보)"
                        final_original_list.append(q_copy)
                    # 기존 족보는 언제나 무작위로 섞어서 제공
                    random.shuffle(final_original_list)

                # --- 최종 리스트 병합 (A형 -> 기존 족보 순서) ---
                final_predict_list = a_type_list + final_original_list

                # PDF 생성
                if not final_predict_list:
                    st.error("생성된 문제가 없습니다. 조건을 확인해 주세요.")
                else:
                    filename = "Subjective_Master.pdf"
                    topic_str = f"주관식 통합 (A형:{len(a_type_list)}제, 족보:{len(final_original_list)}제)"
                    
                    result = create_exam_pdf(
                        final_predict_list, 
                        filename, 
                        answer_mode, 
                        exam_title=f"{selected_exam} 주관식 예측",
                        subject_title=selected_subject,
                        topic_title=topic_str
                    )
                    
                    if result == "성공":
                        st.success(f"준비 완료! 총 {len(final_predict_list)}문항이 정렬되었습니다.")
                        with open(filename, "rb") as f:
                            st.download_button(
                                label="📥 주관식 마스터 PDF 다운로드",
                                data=f,
                                file_name=f"{selected_exam}_{selected_subject}_주관식_마스터.pdf",
                                mime="application/pdf"
                            )
                    else:
                        st.error(result)