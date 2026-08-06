from datetime import datetime, timedelta
import math
import FinanceDataReader as fdr
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_plotly_events import plotly_events

st.set_page_config(page_title="ETF 인터랙티브 백테스팅", layout="wide")

# --- 상태 관리 (세션) ---
if 'start_date' not in st.session_state:
    st.session_state.start_date = datetime.today() - timedelta(days=365)
if 'end_date' not in st.session_state:
    st.session_state.end_date = datetime.today()

# --- 데이터 준비 ---
@st.cache_data
def get_etf_data():
    try:
        df_etf = fdr.StockListing("ETF/KR")
        return {f"{row['Name']} ({row['Symbol']})": str(row['Symbol']) for _, row in df_etf.iterrows()}
    except:
        return {"KODEX 200 (069500)": "069500"}

DIVIDEND_RATES = {"459580": 0.102, "474520": 0.120, "402970": 0.038, "133690": 0.009, "069500": 0.018}
etf_dict = get_etf_data()

# --- 사이드바 ---
st.sidebar.header("📋 설정")
selected_etf = st.sidebar.selectbox("ETF 선택", list(etf_dict.keys()))
ticker = etf_dict[selected_etf]
investment = st.sidebar.number_input("투자금 (원)", value=100000000)

# 날짜 변경을 위한 입력
st.session_state.start_date = st.sidebar.date_input("시작일", st.session_state.start_date)
st.session_state.end_date = st.sidebar.date_input("종료일", st.session_state.end_date)

# --- 메인 로직 ---
st.title("📈 드래그로 기간을 설정하는 ETF 분석기")
st.info("💡 차트 위를 마우스로 드래그하면 해당 기간으로 자동 재계산됩니다.")

df_all = fdr.DataReader(ticker, start="2010-01-01")
df_sub = df_all.loc[st.session_state.start_date:st.session_state.end_date]

if not df_sub.empty:
    buy_price = df_sub.iloc[0]["Close"]
    quantity = math.floor(investment / buy_price)
    current_price = df_sub.iloc[-1]["Close"]
    total_eval = (quantity * current_price) + (investment - (quantity * buy_price))
    
    # 계산 출력
    col1, col2 = st.columns(2)
    col1.metric("현재 평가금액", f"{total_eval:,.0f} 원")
    col2.metric("수익률", f"{((total_eval-investment)/investment)*100:.2f}%")

    # --- 인터랙티브 차트 ---
    fig = px.line(df_all.reset_index(), x="Date", y="Close")
    fig.add_vrect(x0=st.session_state.start_date, x1=st.session_state.end_date, fillcolor="blue", opacity=0.1)
    
    # 드래그 이벤트 감지
    selected_points = plotly_events(fig, click_event=False, select_event=True)
    
    if selected_points:
        # 드래그 선택 영역의 날짜 추출
        # (plotly_events는 선택된 데이터포인트의 x축 좌표를 반환)
        dates = [p['x'] for p in selected_points]
        if len(dates) >= 2:
            new_start = min(dates)
            new_end = max(dates)
            # 세션 상태 업데이트 (자동으로 재실행됨)
            st.session_state.start_date = pd.to_datetime(new_start).date()
            st.session_state.end_date = pd.to_datetime(new_end).date()
            st.rerun()
else:
    st.error("데이터가 없습니다.")
