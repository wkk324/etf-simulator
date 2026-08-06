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
@st.cache_data
def get_etf_data():
    try:
        df_etf = fdr.StockListing("ETF/KR")
        etf_dict = {f"{row['Name']} ({row['Symbol']})": str(row['Symbol']) for _, row in df_etf.iterrows()}
    except:
        etf_dict = {
            "KODEX 200 (069500)": "069500",
            "TIGER 미국나스닥100 (133690)": "133690",
            "ACE 미국배당다우존스 (402970)": "402970",
            "TIGER 미국배당+7%프리미엄다우존스 (459580)": "459580"
        }
    return etf_dict

@st.cache_data
def get_price_history(ticker):
    return fdr.DataReader(ticker, start="2010-01-01", end=datetime.today().strftime("%Y-%m-%d"))

DIVIDEND_RATES = {
    "459580": 0.102,
    "474520": 0.120,
    "402970": 0.038,
    "133690": 0.009,
    "069500": 0.018,
    "102110": 0.018,
    "368590": 0.013,
}

PERIOD_DAYS = {"1년": 365, "3년": 365 * 3, "5년": 365 * 5, "10년": 365 * 10}

def calculate_etf_dividends(ticker, buy_price, days_held):
    rate = DIVIDEND_RATES.get(ticker, 0.020)
    years = max(days_held / 365.0, 0.1)
    return math.floor(buy_price * rate * years)

def get_formatted_period(start_date, end_date):
    total_days = (end_date - start_date).days + 1
    if total_days > 0 and total_days % 365 == 0:
        years = total_days // 365
        return f"{years}년 ({total_days:,}일)"
    y1, m1, d1 = start_date.year, start_date.month, start_date.day
    y2, m2, d2 = end_date.year, end_date.month, end_date.day
    years = y2 - y1
    months = m2 - m1
    days = (d2 - d1) + 1
    if days < 0:
        months -= 1
        import calendar
        prev_month = m2 - 1 if m2 > 1 else 12
        prev_year = y2 if m2 > 1 else y2 - 1
        days += calendar.monthrange(prev_year, prev_month)[1]
    if months < 0:
        years -= 1
        months += 12
    parts = []
    if years > 0: parts.append(f"{years}년")
    if months > 0: parts.append(f"{months}개월")
    if days > 0: parts.append(f"{days}일")
    return f"{' '.join(parts)} ({total_days:,}일)"

etf_dict = get_etf_data()
etf_options = list(etf_dict.keys())

# --- 사이드바 ---
st.sidebar.header("📋 이번 비교 조건")
selected_etf_label = st.sidebar.selectbox("한국 상장 ETF 검색 및 선택", options=etf_options)
ticker = etf_dict[selected_etf_label]
investment_amount = st.sidebar.number_input("투자금 (원)", value=100000000, step=1000000, format="%d")
period_mode = st.sidebar.radio("방식 선택", ["고정 기간 (1/3/5/10년)", "직접 날짜 지정"], index=0, horizontal=True)
period_option = st.sidebar.radio("기간 선택", ["1년", "3년", "5년", "10년", "전체"], index=1, horizontal=True) if period_mode == "고정 기간 (1/3/5/10년)" else "직접지정"
insurance_type = st.sidebar.radio("건강보험 가입 유형", ["지역가입자", "직장가입자"], index=0, horizontal=True)
other_income = st.sidebar.radio("기타 금융소득", ["없음", "3천만", "5천만", "7천만", "1억"], index=0, horizontal=True)
income_map = {"없음": 0, "3천만": 30000000, "5천만": 50000000, "7천만": 70000000, "1억": 100000000}
other_income = income_map[other_income]

# --- 메인 연산 ---
if ticker:
    df_all = get_price_history(ticker)
    if df_all.empty:
        st.warning("데이터가 없습니다.")
    else:
        earliest_date, latest_date = df_all.index.min().date(), df_all.index.max().date()
        
        if period_option == "직접지정":
            col_d1, col_d2 = st.columns(2)
            start_date = col_d1.date_input("매수일", value=max(earliest_date, latest_date - timedelta(days=365*3)), min_value=earliest_date, max_value=latest_date)
            end_date = col_d2.date_input("매도일", value=latest_date, min_value=earliest_date, max_value=latest_date)
        else:
            if period_option == "전체": start_date, end_date = earliest_date, latest_date
            else:
                duration = timedelta(days=PERIOD_DAYS[period_option])
                start_date = st.slider("매수 시점", min_value=earliest_date, max_value=max(earliest_date, latest_date - duration), value=max(earliest_date, latest_date - duration))
                end_date = start_date + duration

        # --- 차트 출력 (날짜 상세 표시 및 라벨 변경) ---
        df_all_reset = df_all.reset_index()
        fig = px.line(df_all_reset, x="Date", y="Close", labels={"Close": "종가", "Date": "날짜"})
        
        fig.add_vrect(x0=pd.Timestamp(start_date), x1=pd.Timestamp(end_date), fillcolor="blue", opacity=0.15, layer="below", line_width=0)
        
        fig.update_layout(
            title="전체 기간 주가 추이",
            xaxis_title="날짜",
            yaxis_title="종가 (원)",
            hovermode="x unified",
            xaxis=dict(fixedrange=True, tickformat="%Y-%m-%d"), # X축 날짜 형식
            yaxis=dict(fixedrange=True, tickformat=",d"),
        )
        
        # 툴팁 날짜 상세 포맷 적용
        fig.update_traces(hovertemplate="날짜: %{x|%Y-%m-%d}<br>종가: %{y:,.0f}원")
        
        st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": False, "displayModeBar": False})

        # --- 계산부 (생략된 기존 로직 유지) ---
        mask = (df_all.index >= pd.Timestamp(start_date)) & (df_all.index <= pd.Timestamp(end_date))
        df = df_all.loc[mask]
        buy_price = df.iloc[0]["Close"]
        quantity = math.floor(investment_amount / buy_price)
        current_price = df.iloc[-1]["Close"]
        total_eval = (quantity * current_price) + (investment_amount - (quantity * buy_price))
        st.metric("최종 평가금액", f"{total_eval:,.0f} 원")
