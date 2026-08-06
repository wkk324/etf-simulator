from datetime import datetime, timedelta
import math
import FinanceDataReader as fdr
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="한국 ETF 분배금 내역·세금 계산", layout="wide")

st.title("🏦 한국 ETF 분배금 내역·세금 계산")
st.divider()

# --- 데이터 준비 ---
@st.cache_data(ttl=3600)
def get_etf_data(sort_by):
    recommended_list = [("ACE 미국배당다우존스 (402970)", "402970"), ("KODEX 200 (069500)", "069500"), ("TIGER 미국나스닥100 (133690)", "133690"), ("TIGER 미국배당+7%프리미엄다우존스 (459580)", "459580")]
    df_etf = fdr.StockListing("ETF/KR")
    df_etf['Symbol'] = df_etf['Symbol'].astype(str).str.zfill(6)
    rec_symbols = [item[1] for item in recommended_list]
    df_etf = df_etf[~df_etf['Symbol'].isin(rec_symbols)]
    df_etf = df_etf.sort_values(by="Name" if sort_by == "가나다 이름순" else "Symbol")
    other_list = [(f"{row['Name']} ({row['Symbol']})", str(row['Symbol'])) for _, row in df_etf.iterrows()]
    return {label: code for label, code in (recommended_list + other_list)}

@st.cache_data
def get_price_history(ticker):
    return fdr.DataReader(ticker, start="2010-01-01", end=datetime.today().strftime("%Y-%m-%d"))

PERIOD_DAYS = {"1년": 365, "3년": 365*3, "5년": 365*5, "10년": 365*10}

# --- 사이드바 ---
st.sidebar.header("📋 설정")
ticker = get_etf_data("가나다 이름순")[st.sidebar.selectbox("종목 선택", list(get_etf_data("가나다 이름순").keys()))]
investment_amount = st.sidebar.number_input("투자금 (원)", value=100000000, step=1000000)

period_mode = st.sidebar.radio("기간 선택 방식", ["고정 기간 이동 (슬라이더)", "직접 날짜 지정"])

if period_mode == "고정 기간 이동 (슬라이더)":
    duration_label = st.sidebar.selectbox("고정 기간", ["1년", "3년", "5년", "10년"], index=1)
    duration_days = PERIOD_DAYS[duration_label]
else:
    duration_days = None

# --- 메인 연산 ---
df_all = get_price_history(ticker)
if not df_all.empty:
    earliest_date, latest_date = df_all.index.min().date(), df_all.index.max().date()
    
    if period_mode == "고정 기간 이동 (슬라이더)":
        # 슬라이더 범위를 전체 기간으로 설정
        max_start = latest_date - timedelta(days=duration_days)
        start_date = st.slider(f"{duration_label} 기간 이동", 
                               min_value=earliest_date, 
                               max_value=max_start, 
                               value=max_start) # 기본값은 최근 3년
        end_date = start_date + timedelta(days=duration_days)
    else:
        col1, col2 = st.columns(2)
        start_date = col1.date_input("매수일", value=latest_date - timedelta(days=365*3))
        end_date = col2.date_input("매도일", value=latest_date)

    st.info(f"📍 구간: {start_date} ~ {end_date} (약 {(end_date-start_date).days/365:.1f}년)")

    # 차트 출력
    fig = go.Figure(data=[go.Scatter(x=df_all.index, y=df_all['Close'], line=dict(color='royalblue'))])
    # 구간 하이라이트 (주황색)
    fig.add_vrect(x0=pd.Timestamp(start_date), x1=pd.Timestamp(end_date), 
                  fillcolor="orange", opacity=0.3, layer="below", line_width=0)
    fig.update_layout(hovermode="x unified", xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)

    # (결과 계산 부분은 이전과 동일하므로 생략 - 전체 코드에 포함하세요)
