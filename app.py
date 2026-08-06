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

# --- 데이터 준비 (리스트 기반 추천 ETF 최상단 고정) ---
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
etf_dict = get_etf_data(sort_option)
selected_etf_label = st.sidebar.selectbox("한국 상장 ETF 검색 및 선택", options=list(etf_dict.keys()))
ticker = etf_dict[selected_etf_label]

investment_option = st.sidebar.radio("투자금 선택", ["1억", "3억", "5억", "10억", "기타"], index=0, horizontal=True)

if investment_option == "1억":
    investment_amount = 100000000
elif investment_option == "3억":
    investment_amount = 300000000
elif investment_option == "5억":
    investment_amount = 500000000
elif investment_option == "10억":
    investment_amount = 1000000000
else:
    investment_amount = st.sidebar.number_input("직접 입력 (원)", value=50000000, step=1000000, format="%d")

st.sidebar.markdown("**차트 형태 선택**")
chart_type = st.sidebar.radio("차트 종류", ["선 차트 (Line)", "캔들 차트 (Candle)"], index=0, horizontal=True)

period_mode = st.sidebar.radio("기간 설정 방식", ["고정 기간 통째로 이동", "자유 범위 지정", "직접 날짜 지정"], index=0, horizontal=True)

if period_mode == "고정 기간 통째로 이동":
    fixed_period_label = st.sidebar.selectbox("고정할 투자 기간", ["1년", "3년", "5년", "10년"], index=1)
    period_option = "고정이동"
elif period_mode == "자유 범위 지정":
    period_option = "자유범위"
else:
    period_option = "직접지정"

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
        elif period_option == "고정이동":
            duration_days = PERIOD_DAYS[fixed_period_label]
            max_start = max(earliest_date, latest_date - timedelta(days=duration_days))
            
            # 슬라이더로 매수 시점(시작일)만 움직이면, 종료일은 기간만큼 자동 계산되어 덩어리째 이동
            start_date = st.slider(
                f"📅 {fixed_period_label} 기간 통째로 이동 (매수 시점 조절)",
                min_value=earliest_date,
                max_value=max_start,
                value=max_start,
                format="YYYY-MM-DD"
            )
            end_date = start_date + timedelta(days=duration_days)
            if end_date > latest_date:
                end_date = latest_date
        else:
            duration = timedelta(days=365 * 3)
            default_start = max(earliest_date, latest_date - duration)
            date_range = st.slider(
                "📅 매수 및 매도 시점 범위 선택",
                min_value=earliest_date,
                max_value=latest_date,
                value=(default_start, latest_date),
                format="YYYY-MM-DD"
            )
            start_date, end_date = date_range

        # 선택된 기간 안내
        holding_days = (end_date - start_date).days
        holding_years = holding_days / 365.0
        st.info(f"📍 **선택된 투자 기간:** {start_date} ~ {end_date} (총 **{holding_days:,}일** / 약 **{holding_years:.1f}년** 보유)")

        # 차트 출력 (주황색 하이라이트 적용)
        df_all_reset = df_all.reset_index()
        date_col = "Date" if "Date" in df_all_reset.columns else df_all_reset.columns[0]

        if chart_type == "선 차트 (Line)":
            fig = px.line(df_all_reset, x=date_col, y="Close", labels={"Close": "종가", date_col: "날짜"})
            fig.update_traces(hovertemplate="날짜: %{x|%Y-%m-%d}<br>종가: %{y:,.0f}원")
        else:
            fig = go.Figure(data=[go.Candlestick(
                x=df_all_reset[date_col],
                open=df_all_reset['Open'],
                high=df_all_reset['High'],
                low=df_all_reset['Low'],
                close=df_all_reset['Close'],
                increasing_line_color='red',
                decreasing_line_color='blue',
                hovertemplate="날짜: %{x|%Y-%m-%d}<br>시가: %{open:,.0f}원<br>고가: %{high:,.0f}원<br>저가: %{low:,.0f}원<br>종가: %{close:,.0f}원<extra></extra>"
            )])

        fig.add_vrect(x0=pd.Timestamp(start_date), x1=pd.Timestamp(end_date), fillcolor="orange", opacity=0.25, layer="below", line_width=0)
        fig.update_layout(xaxis=dict(tickformat="%Y-%m-%d", fixedrange=False), yaxis=dict(tickformat=",d", fixedrange=False), xaxis_rangeslider_visible=False, hovermode="x unified", dragmode="pan")
        
        st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True, "displayModeBar": True, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})

        # 계산 결과
        mask = (df_all.index >= pd.Timestamp(start_date)) & (df_all.index <= pd.Timestamp(end_date))
        df = df_all.loc[mask]
        if not df.empty:
            buy_price = df.iloc[0]["Close"]
            sell_price = df.iloc[-1]["Close"]  
            price_diff = sell_price - buy_price  
            price_diff_pct = (price_diff / buy_price) * 100  
            
            quantity = math.floor(investment_amount / buy_price)
            actual_invested = quantity * buy_price  
            total_eval = (quantity * sell_price) + (investment_amount - actual_invested)
            eval_profit = total_eval - investment_amount
            eval_profit_pct = (eval_profit / investment_amount) * 100  
            
            st.subheader(f"📌 {selected_etf_label} 시뮬레이션 결과")
            
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("주식수", f"{quantity:,} 주")
            col2.metric("매수 주가", f"{buy_price:,.0f} 원")
            col3.metric("매도 주가", f"{sell_price:,.0f} 원", delta=f"{price_diff:,.0f} 원 ({price_diff_pct:.2f}%)")
            col4.metric("매수 평가금액", f"{actual_invested:,.0f} 원")
            col5.metric("매도 평가금액", f"{total_eval:,.0f} 원", delta=f"{eval_profit:,.0f} 원 ({eval_profit_pct:.2f}%)")
            
            total_dps = calculate_etf_dividends(ticker, buy_price, holding_days)
            total_div_gross = quantity * total_dps
            combined_income = other_income + total_div_gross
            
            st.divider()
            st.subheader("⚖️ 세금 및 건강보험료 상세")
            st.info(f"예상 배당 수익(세전): {total_div_gross:,.0f} 원")
            
            if combined_income > 20000000:
                excess_income = combined_income - 20000000
                est_tax_base = calculate_income_tax(combined_income)
                est_tax_total = est_tax_base * 1.1  # 지방세(10%) 포함
                net_dividend = total_div_gross - est_tax_total  
                
                st.error("⚠️ 금융소득종합과세 대상입니다.")
                st.write(f"- **합산 금융소득:** {combined_income:,.0f} 원")
                st.write(f"- **종합과세 적용 대상액:** {excess_income:,.0f} 원")
                st.write(f"- **예상 추가 소득세(지방세 포함):** 약 {est_tax_total:,.0f} 원 (소득세 {est_tax_base:,.0f} 원 + 지방세 {est_tax_base * 0.1:,.0f} 원)")
                st.caption("※ 실제 세액은 기본공제 및 기타 소득 환경에 따라 크게 달라질 수 있습니다.")
            else:
                tax_154 = total_div_gross * 0.154
                net_dividend = total_div_gross - tax_154
                st.success("원천징수 분리과세 구간입니다.")
                st.write(f"- **원천징수 예상 세액(15.4%):** {tax_154:,.0f} 원")
                st.write(f"- **세후 예상 수령액:** {net_dividend:,.0f} 원")

            # --- 최종 총수익 요약 ---
            st.divider()
            st.subheader("💰 최종 총수익 요약 (세후 기준)")
            
            total_net_profit = eval_profit + net_dividend
            total_net_profit_pct = (total_net_profit / investment_amount) * 100
            
            col_t1, col_t2, col_t3 = st.columns(3)
            col_t1.metric("매도 차액 (자본이익)", f"{eval_profit:,.0f} 원")
            col_t2.metric("세후 예상 배당금", f"{net_dividend:,.0f} 원")
            col_t3.metric("최종 총수익 (세후)", f"{total_net_profit:,.0f} 원", delta=f"수익률 {total_net_profit_pct:.2f}%")
