from datetime import datetime, timedelta
import math
import FinanceDataReader as fdr
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="한국 ETF 분배금 내역·세금 계산", layout="wide")

st.title("🏦 한국 ETF 분배금 내역·세금 계산")
st.caption("과거 데이터 기반 투자 시뮬레이션 및 분배금·세금 정산 결과입니다.")
st.divider()

# --- 데이터 준비 ---
@st.cache_data(ttl=3600)
def get_etf_data(sort_by):
    recommended_list = [
        ("ACE 미국배당다우존스 (402970)", "402970"),
        ("KODEX 200 (069500)", "069500"),
        ("TIGER 미국나스닥100 (133690)", "133690"),
        ("TIGER 미국배당+7%프리미엄다우존스 (459580)", "459580")
    ]
    
    other_list = []
    try:
        df_etf = fdr.StockListing("ETF/KR")
        if not df_etf.empty:
            df_etf['Symbol'] = df_etf['Symbol'].astype(str).str.zfill(6)
            rec_symbols = [item[1] for item in recommended_list]
            df_etf = df_etf[~df_etf['Symbol'].isin(rec_symbols)]
            
            if sort_by == "가나다 이름순":
                df_etf = df_etf.sort_values(by="Name", ascending=True)
            else:
                df_etf = df_etf.sort_values(by="Symbol", ascending=True)
            other_list = [(f"{row['Name']} ({row['Symbol']})", str(row['Symbol'])) for _, row in df_etf.iterrows()]
    except:
        pass
        
    final_list = recommended_list + other_list
    return {label: code for label, code in final_list}

@st.cache_data
def get_price_history(ticker):
    return fdr.DataReader(ticker, start="2010-01-01", end=datetime.today().strftime("%Y-%m-%d"))

DIVIDEND_RATES = {
    "459580": 0.102, "474520": 0.120, "402970": 0.038,
    "133690": 0.009, "069500": 0.018, "102110": 0.018, "368590": 0.013,
}
PERIOD_DAYS = {"1년": 365, "3년": 365 * 3, "5년": 365 * 5, "10년": 365 * 10}

def calculate_etf_dividends(ticker, buy_price, days_held):
    rate = DIVIDEND_RATES.get(ticker, 0.020)
    years = max(days_held / 365.0, 0.1)
    return math.floor(buy_price * rate * years)

def calculate_income_tax(total_income):
    if total_income <= 14000000: return total_income * 0.06
    elif total_income <= 50000000: return 840000 + (total_income - 14000000) * 0.15
    elif total_income <= 88000000: return 6240000 + (total_income - 50000000) * 0.24
    elif total_income <= 150000000: return 15360000 + (total_income - 88000000) * 0.35
    else: return 37060000 + (total_income - 150000000) * 0.38

# --- 사이드바 ---
st.sidebar.header("📋 이번 비교 조건")
sort_option = st.sidebar.radio("ETF 목록 정렬 방식", ["가나다 이름순", "종목 코드순"], index=0, horizontal=True)

# ETF 데이터 로드
etf_dict = get_etf_data(sort_option)

# 🔍 [명확하게 추가된 검색창]
search_query = st.sidebar.text_input("🔍 ETF 이름/코드 직접 검색", placeholder="예: 미국배당 또는 402970")

if search_query:
    filtered_dict = {k: v for k, v in etf_dict.items() if search_query.lower() in k.lower()}
    options = list(filtered_dict.keys()) if filtered_dict else list(etf_dict.keys())
    if not filtered_dict:
        st.sidebar.warning("검색 결과가 없어 전체 목록을 표시합니다.")
else:
    options = list(etf_dict.keys())

selected_etf_label = st.sidebar.selectbox("한국 상장 ETF 선택", options=options)
ticker = etf_dict[selected_etf_label]

investment_option = st.sidebar.radio("투자금 선택", ["1억", "3억", "5억", "10억", "기타"], index=0, horizontal=True)
investment_amount = 100000000 if investment_option == "1억" else (300000000 if investment_option == "3억" else (500000000 if investment_option == "5억" else (1000000000 if investment_option == "10억" else st.sidebar.number_input("직접 입력 (원)", value=50000000, step=1000000, format="%d"))))

st.sidebar.markdown("**차트 형태 선택**")
chart_type = st.sidebar.radio("차트 종류", ["선 차트 (Line)", "캔들 차트 (Candle)"], index=0, horizontal=True)

period_mode = st.sidebar.radio("방식 선택", ["기간 범위 자유 선택", "고정 기간 이동 (슬라이더)", "직접 날짜 지정"], index=0, horizontal=True)

if period_mode == "직접 날짜 지정":
    period_option = "직접지정"
elif period_mode == "고정 기간 이동 (슬라이더)":
    period_option = "고정기간이동"
    fixed_duration_label = st.sidebar.selectbox("고정할 투자 기간 선택", ["1년", "3년", "5년", "10년"], index=1)
else:
    period_option = st.sidebar.radio("기본 기간 선택", ["1년", "3년", "5년", "10년", "전체"], index=1, horizontal=True)

insurance_type = st.sidebar.radio("건강보험 가입 유형", ["지역가입자", "직장가입자"], index=0, horizontal=True)
income_map = {"없음": 0, "3천만": 30000000, "5천만": 50000000, "7천만": 70000000, "1억": 100000000}
other_income = income_map[st.sidebar.radio("기타 금융소득", list(income_map.keys()), index=0, horizontal=True)]

# --- 메인 연산 ---
if ticker:
    df_all = get_price_history(ticker)
    if not df_all.empty:
        earliest_date, latest_date = df_all.index.min().date(), df_all.index.max().date()
        
        if period_option == "직접지정":
            col_d1, col_d2 = st.columns(2)
            start_date = col_d1.date_input("매수일", value=max(earliest_date, latest_date - timedelta(days=365*3)), min_value=earliest_date, max_value=latest_date)
            end_date = col_d2.date_input("매도일", value=latest_date, min_value=earliest_date, max_value=latest_date)
        elif period_option == "전체":
            start_date, end_date = earliest_date, latest_date
        elif period_option == "고정기간이동":
            duration_days = PERIOD_DAYS[fixed_duration_label]
            max_start = max(earliest_date, latest_date - timedelta(days=duration_days))
            start_date = st.slider(f"📅 {fixed_duration_label} 기간 이동 (매수 시점 조절)", min_value=earliest_date, max_value=max_start, value=max(earliest_date, latest_date - timedelta(days=duration_days)), format="YYYY-MM-DD")
            end_date = min(start_date + timedelta(days=duration_days), latest_date)
        else:
            duration = timedelta(days=PERIOD_DAYS[period_option])
            default_start = max(earliest_date, latest_date - duration)
            start_date, end_date = st.slider("📅 매수 시점 및 매도 시점 선택 (범위)", min_value=earliest_date, max_value=latest_date, value=(default_start, latest_date), format="YYYY-MM-DD")

        holding_days = (end_date - start_date).days
        st.info(f"📍 **선택된 투자 기간:** {start_date} ~ {end_date} (총 **{holding_days:,}일** 보유)")

        df_all_reset = df_all.reset_index()
        date_col = "Date" if "Date" in df_all_reset.columns else df_all_reset.columns[0]

        if chart_type == "선 차트 (Line)":
            fig = px.line(df_all_reset, x=date_col, y="Close")
        else:
            fig = go.Figure(data=[go.Candlestick(x=df_all_reset[date_col], open=df_all_reset['Open'], high=df_all_reset['High'], low=df_all_reset['Low'], close=df_all_reset['Close'])])

        fig.add_vrect(x0=pd.Timestamp(start_date), x1=pd.Timestamp(end_date), fillcolor="blue", opacity=0.15, layer="below", line_width=0)
        fig.update_layout(xaxis=dict(range=[earliest_date, latest_date]), hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

        # 결과 계산
        mask = (df_all.index >= pd.Timestamp(start_date)) & (df_all.index <= pd.Timestamp(end_date))
        df = df_all.loc[mask]
        if not df.empty:
            buy_price, sell_price = df.iloc[0]["Close"], df.iloc[-1]["Close"]
            quantity = math.floor(investment_amount / buy_price)
            actual_invested = quantity * buy_price
            total_eval = (quantity * sell_price) + (investment_amount - actual_invested)
            eval_profit = total_eval - investment_amount
            
            st.subheader(f"📌 {selected_etf_label} 결과")
            col1, col2, col3 = st.columns(3)
            col1.metric("주식수", f"{quantity:,} 주")
            col2.metric("매수 평가금액", f"{actual_invested:,.0f} 원")
            col3.metric("매도 평가금액", f"{total_eval:,.0f} 원", delta=f"{eval_profit:,.0f} 원")
