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
        etf_dict = {"KODEX 200 (069500)": "069500", "TIGER 미국나스닥100 (133690)": "133690", "ACE 미국배당다우존스 (402970)": "402970"}
    return etf_dict

DIVIDEND_RATES = {"459580": 0.102, "474520": 0.120, "402970": 0.038, "133690": 0.009, "069500": 0.018}

def calculate_etf_dividends(ticker, buy_price, days_held):
    rate = DIVIDEND_RATES.get(ticker, 0.020)
    years = max(days_held / 365.0, 0.1)
    return math.floor(buy_price * rate * years)

etf_dict = get_etf_data()
etf_options = list(etf_dict.keys())

# --- 사이드바 설정 ---
st.sidebar.header("📋 비교 조건 설정")
selected_etf_label = st.sidebar.selectbox("ETF 선택", options=etf_options)
ticker = etf_dict[selected_etf_label]

investment_amount = st.sidebar.number_input("투자금 (원)", value=100000000, step=1000000)
period_option = st.sidebar.radio("기간 선택", ["1년", "3년", "5년", "10년", "전체"], index=1, horizontal=True)

today = datetime.today()
if period_option == "1년": calc_start = today - timedelta(days=365)
elif period_option == "3년": calc_start = today - timedelta(days=365 * 3)
elif period_option == "5년": calc_start = today - timedelta(days=365 * 5)
elif period_option == "10년": calc_start = today - timedelta(days=365 * 10)
else: calc_start = datetime(2010, 1, 1)

start_date = st.sidebar.date_input("시작일", value=calc_start)
end_date = st.sidebar.date_input("종료일", value=today)

# --- 메인 연산 ---
if ticker:
    with st.spinner("데이터 분석 중..."):
        # 1. 시뮬레이션용 데이터
        df = fdr.DataReader(ticker, start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))
        # 2. 전체 흐름용 데이터 (2010년부터)
        df_all = fdr.DataReader(ticker, start="2010-01-01", end=today.strftime("%Y-%m-%d"))
        
        if df.empty:
            st.warning("선택한 기간의 데이터가 없습니다.")
        else:
            buy_price = df.iloc[0]["Close"]
            quantity = math.floor(investment_amount / buy_price)
            current_price = df.iloc[-1]["Close"]
            total_eval = (quantity * current_price) + (investment_amount - (quantity * buy_price))
            
            eval_profit = total_eval - investment_amount
            days_held = (end_date - start_date).days
            total_dps = calculate_etf_dividends(ticker, buy_price, days_held)
            total_div_net = math.floor((quantity * total_dps) * 0.846)
            
            total_return = eval_profit + total_div_net
            return_rate = (total_return / investment_amount) * 100

            # --- 결과 출력 ---
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("매수 주식수", f"{quantity:,} 주")
            col2.metric("매수 시점 주가", f"{buy_price:,.0f} 원")
            col3.metric("현재 평가금액", f"{total_eval:,.0f} 원", delta=f"{eval_profit:,.0f} 원")
            col4.metric("최종 수익(분배금포함)", f"{total_return:,.0f} 원", delta=f"{return_rate:.2f}%")

            if eval_profit < 0:
                st.warning(f"⚠️ 주가가 {((current_price - buy_price)/buy_price)*100:.2f}% 하락했으나, 분배금 합산 시 실손실액은 {(total_return/investment_amount)*100:.2f}%로 완화됩니다.")

            # --- 차트 출력 ---
            st.divider()
            st.subheader("📈 전체 주가 흐름 및 투자 구간")
            
            df_all_reset = df_all.reset_index()
            date_col = df_all_reset.columns[0]
            
            fig = px.line(df_all_reset, x=date_col, y="Close", title="전체 기간 주가 추이")
            
            # 투자 구간 하이라이트
            fig.add_vrect(
                x0=start_date.strftime("%Y-%m-%d"), x1=end_date.strftime("%Y-%m-%d"),
                fillcolor="blue", opacity=0.1, layer="below", line_width=0,
                annotation_text="투자 구간", annotation_position="top left"
            )
            
            # 시작/종료 마커
            fig.add_trace(go.Scatter(
                x=[pd.Timestamp(start_date), pd.Timestamp(end_date)],
                y=[df.iloc[0]["Close"], df.iloc[-1]["Close"]],
                mode="markers+text", marker=dict(size=10, color=["blue", "red"]),
                text=["매수", "현재"], textposition="top center"
            ))
            
            fig.update_layout(xaxis_title="날짜", yaxis_title="종가 (원)", hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)
