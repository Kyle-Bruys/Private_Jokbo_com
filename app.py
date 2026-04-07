import streamlit as st
from supabase import create_client, Client
import json
import re
import os
import random
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import streamlit as st
from supabase import create_client, Client
import pandas as pd
import json
import re
import os
import random

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

def create_exam_pdf(questions, filename, answer_mode, exam_title="기출 모의고사"):
    """선택된 문제 리스트를 2단 A4 PDF로 렌더링 (시험 제목 추가)"""
    if not register_fonts():
        return "에러: 'Pretendard-Regular.ttf' 및 'Pretendard-Bold.ttf' 폰트 파일이 같은 폴더에 없습니다."

    # 스타일 정의
    style_title = ParagraphStyle('Title', fontName='Pretendard-Bold', fontSize=18, alignment=1, spaceAfter=20)
    style_normal = ParagraphStyle('Normal', fontName='Pretendard', fontSize=10, leading=15)
    style_bold = ParagraphStyle('Bold', fontName='Pretendard-Bold', fontSize=11, leading=16, spaceAfter=6)
    style_exp = ParagraphStyle('Exp', fontName='Pretendard', fontSize=9, leading=14, textColor='#0055A4')
    
    # 레이아웃 설정 (기존과 동일)
    margin = 1.5 * cm
    col_width = (A4[0] - 2 * margin - 1 * cm) / 2
    col_height = A4[1] - 2 * margin - 1 * cm # 제목 공간 확보
    
    frame_left = Frame(margin, margin, col_width, col_height, id='left')
    frame_right = Frame(margin + col_width + 1 * cm, margin, col_width, col_height, id='right')
    
    doc = BaseDocTemplate(filename, pagesize=A4)
    doc.addPageTemplates([PageTemplate(id='TwoCol', frames=[frame_left, frame_right])])

    story = []
    
    # [수정] 시험지 최상단 제목 추가
    story.append(Paragraph(exam_title, style_title))

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

    # --- 옵션: 문제마다 해설 ---
    if answer_mode == "문제마다 해설":
        for i, q in enumerate(questions):
            render_question(i, q)
            answer_text = q['answer'] if q.get('answer') else "없음"
            story.append(Paragraph(f"[정답] {answer_text}", style_exp))
            if q.get('explanation'):
                story.append(Paragraph(f"[해설] {q['explanation']}", style_exp))
            story.append(Spacer(1, 1 * cm))

    # --- 옵션: 마지막에 해설 ---
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

menu = st.sidebar.selectbox("메뉴", ["문제 추가하기", "문제 조회 및 PDF 생성", "통계 및 현황"])

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
        
        # (기존 코드) st.dataframe(filtered_questions, use_container_width=True) 아래 부분부터 교체
        
        st.subheader("📄 PDF 생성 옵션")
        col_opt1, col_opt2 = st.columns(2)
        
        with col_opt1:
            answer_mode = st.radio(
                "해설 배치 방식",
                ["마지막에 해설", "문제마다 해설"],
                horizontal=True
            )
            do_shuffle = st.checkbox("🎲 문제 순서 무작위로 섞기", value=True)
        
        with col_opt2:
            # --- [기능 추가] 출력 문제 수 설정 ---
            num_preset = st.radio("출력 문제 수", ["전체", "20문제", "직접 설정"], horizontal=True)
            custom_num = len(filtered_questions)
            
            if num_preset == "직접 설정":
                custom_num = st.number_input("문제 수 입력", min_value=1, max_value=len(filtered_questions), value=min(20, len(filtered_questions)))
        
        if st.button("PDF 시험지 생성하기", type="primary"):
            filename = "Exam_Paper.pdf"
            
            # 1. 데이터 복사 및 셔플 적용 (섞은 뒤에 잘라야 랜덤 추출이 됨)
            final_list = list(filtered_questions)
            if do_shuffle:
                random.shuffle(final_list)
            
            # 2. 문제 수 제한 적용 (Slicing)
            if num_preset == "20문제":
                final_list = final_list[:20]
            elif num_preset == "직접 설정":
                final_list = final_list[:custom_num]
            
            with st.spinner(f'총 {len(final_list)}문제로 구성된 시험지를 조판하고 있습니다...'):
                result = create_exam_pdf(final_list, filename, answer_mode, exam_title=selected_exam)
                
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
        # 전체 데이터의 메타정보만 빠르게 불러오기
        all_meta = supabase.table("questions").select("exam_name, subject, topic, author, sub_author").execute().data
    except Exception as e:
        st.error(f"DB 연결 실패: {e}")
        all_meta = []

    if all_meta:
        col_stat1, col_stat2 = st.columns(2)
        
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