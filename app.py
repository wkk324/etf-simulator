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
        df_etf['Symbol'] = df_etf['Symbol'].astype(str).str.zfill(6)
        rec_symbols = [item[1] for item in recommended_list]
        df_etf = df_etf[~df_etf['Symbol'].isin(rec_symbols)]
        df_etf = df_etf.sort_values(by="Name" if sort_by == "가나다 이름순" else "Symbol")
        other_list = [(f"{row['Name']} ({row['Symbol']})", str(row['Symbol'])) for _, row in df_etf.iterrows()]
    except: pass
    return {label: code for label, code in (recommended_list + other_list)}

@st.cache_data
def get_price_history(ticker):
    return fdr.DataReader(ticker, start="2010-01-01", end=datetime.today().strftime("%Y-%m-%d"))

def calculate_etf_dividends(ticker, buy_price, days_held):
    # 예시 배당률 적용
    rate = {"459580": 0.102, "474520": 0.120, "402970": 0.038}.get(ticker, 0.020)
    return math.floor(buy_price * rate * (days_held / 365.0))

def calculate_income_tax(total_income):
    if total_income <= 14000000: return total_income * 0.06
    elif total_income <= 50000000: return 840000 + (total_income - 14000000) * 0.15
    else: return 6240000 + (total_income - 50000000) * 0.24

# --- 사이드바 ---
ticker = get_etf_data("가나다 이름순")[st.sidebar.selectbox("종목 선택", list(get_etf_data("가나다 이름순").keys()))]
investment_amount = st.sidebar.number_input("투자금 (원)", value=100000000, step=1000000)
other_income = st.sidebar.number_input("기타 금융소득 (원)", value=0, step=1000000)

# --- 메인 연산 ---
df_all = get_price_history(ticker)
if not df_all.empty:
    earliest_date, latest_date = df_all.index.min().date(), df_all.index.max().date()
    
    # 날짜 범위 슬라이더
    date_range = st.slider("📅 투자 기간 선택", min_value=earliest_date, max_value=latest_date, 
                           value=(latest_date - timedelta(days=365*3), latest_date))
    start_date, end_date = date_range

    # 차트
    fig = px.line(df_all, x=df_all.index, y="Close")
    fig.add_vrect(x0=pd.Timestamp(start_date), x1=pd.Timestamp(end_date), fillcolor="blue", opacity=0.15)
    st.plotly_chart(fig, use_container_width=True)

    # 계산
    df = df_all.loc[start_date:end_date]
    buy_price = df.iloc[0]["Close"]
    sell_price = df.iloc[-1]["Close"]
    quantity = math.floor(investment_amount / buy_price)
    
    eval_profit = (sell_price - buy_price) * quantity
    total_div_gross = quantity * calculate_etf_dividends(ticker, buy_price, (end_date - start_date).days)
    
    # 세금 계산
    combined_income = other_income + total_div_gross
    if combined_income > 20000000:
        tax = calculate_income_tax(combined_income) * 1.1
        net_dividend = total_div_gross - tax
    else:
        net_dividend = total_div_gross * (1 - 0.154)

    # 결과 출력
    col1, col2, col3 = st.columns(3)
    col1.metric("매도 차액", f"{eval_profit:,.0f} 원")
    col2.metric("세후 예상 배당금", f"{net_dividend:,.0f} 원")
    col3.metric("최종 총수익 (세후)", f"{eval_profit + net_dividend:,.0f} 원")
