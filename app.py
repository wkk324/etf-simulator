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

# 년, 월, 일 상세 계산 함수
def get_formatted_period(start_date, end_date):
    total_days = (end_date - start_date).days + 1  # 기간 포함(+1일)
    
    if total_days > 0 and total_days % 365 == 0:
        years = total_days // 365
        return f"{years}년 ({total_days:,}일)"
    
    y1, m1, d1 = start_date.year, start_date.month, start_date.day
    y2, m2, d2 = end_date.year, end_date.month, end_date.day
    
    years = y2 - y1
    months = m2 - m1
    days = (d2 - d1) + 1  # 첫날 포함 보정
    
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

# --- 사이드바 설정 ---
st.sidebar.header("📋 이번 비교 조건")

st.sidebar.markdown("**💡 테마별 추천 ETF 퀵 선택**")
quick_etf = st.sidebar.radio(
    "추천 ETF",
    ["직접 검색", "🔥 초고배당(연~10% 커버드콜)", "💰 배당성장(연~3.8% SCHD)", "📈 대표지수(S&P500 / 200)"],
    index=0,
)

default_index = 0
if "초고배당" in quick_etf:
    for idx, opt in enumerate(etf_options):
        if "459580" in opt: default_index = idx; break
elif "배당성장" in quick_etf:
    for idx, opt in enumerate(etf_options):
        if "402970" in opt or "미국배당다우존스" in opt: default_index = idx; break
elif "대표지수" in quick_etf:
    for idx, opt in enumerate(etf_options):
        if "069500" in opt: default_index = idx; break

selected_etf_label = st.sidebar.selectbox("한국 상장 ETF 검색 및 선택", options=etf_options, index=default_index)
ticker = etf_dict[selected_etf_label]

st.sidebar.markdown("**투자금**")
quick_money = st.sidebar.radio("투자금 선택", ["1억", "3억", "5억", "10억"], horizontal=True, label_visibility="collapsed")
money_map = {"1억": 100000000, "3억": 300000000, "5억": 500000000, "10억": 1000000000}
investment_amount = st.sidebar.number_input("투자금 직접 입력 (원)", value=money_map[quick_money], step=1000000, format="%d")

st.sidebar.markdown("**투자 기간 설정 방식**")
period_mode = st.sidebar.radio("방식 선택", ["고정 기간 (1/3/5/10년)", "직접 날짜 지정"], index=0, horizontal=True)

if period_mode == "고정 기간 (1/3/5/10년)":
    period_option = st.sidebar.radio("기간 선택", ["1년", "3년", "5년", "10년", "전체"], index=1, horizontal=True, label_visibility="collapsed")
else:
    period_option = "직접지정"

st.sidebar.markdown("**현재 상황 (세금/건보료 조건)**")
insurance_type = st.sidebar.radio("건강보험 가입 유형", ["지역가입자", "직장가입자"], index=0, horizontal=True)
quick_income = st.sidebar.radio("기타 금융소득 (이자/배당)", ["없음", "3천만", "5천만", "7천만", "1억"], index=0, horizontal=True)
income_map = {"없음": 0, "3천만": 30000000, "5천만": 50000000, "7천만": 70000000, "1억": 100000000}
other_income = income_map[quick_income]

# --- 메인 연산 ---
if ticker:
    try:
        with st.spinner(f"'{selected_etf_label}' 시세 데이터 로딩 중..."):
            df_all = get_price_history(ticker)

        if df_all.empty:
            st.warning("시세 데이터가 존재하지 않습니다.")
        else:
            earliest_date = df_all.index.min().date()
            latest_date = df_all.index.max().date()

            st.subheader("📈 전체 주가 흐름 및 투자 구간 설정")

            if period_option == "직접지정":
                st.caption("📅 달력에서 **투자 시작일**과 **투자 마지막일**을 직접 지정해 보세요.")
                col_d1, col_d2 = st.columns(2)
                default_start = max(earliest_date, latest_date - timedelta(days=365*3))
                
                with col_d1:
                    start_date = st.date_input("투자 시작일 (매수일)", value=default_start, min_value=earliest_date, max_value=latest_date)
                with col_d2:
                    end_date = st.date_input("투자 마지막일 (매도일)", value=latest_date, min_value=earliest_date, max_value=latest_date)

                if start_date > end_date:
                    st.error("⚠️ 투자 시작일이 마지막일보다 빠를 수 없습니다. 날짜를 올바르게 선택해주세요.")
                    st.stop()

            else:
                if period_option == "전체":
                    start_date, end_date = earliest_date, latest_date
                    st.caption("🖲️ '전체' 선택 시 상장일부터 최근까지 전 구간이 자동으로 계산됩니다.")
                elif earliest_date + timedelta(days=PERIOD_DAYS[period_option]) >= latest_date:
                    start_date, end_date = earliest_date, latest_date
                    st.warning(
                        f"⚠️ 선택하신 ETF의 시세 데이터는 {earliest_date} 부터 시작해서, "
                        f"'{period_option}' 구간을 옮길 만큼 데이터가 충분하지 않아요. "
                        f"데이터가 있는 전체 구간({earliest_date} ~ {latest_date})으로 계산합니다."
                    )
                else:
                    duration = timedelta(days=PERIOD_DAYS[period_option])
                    min_start = earliest_date
                    max_start = max(min_start, latest_date - duration)
                    default_start = max_start

                    if "_pending_slider_start" in st.session_state:
                        st.session_state["drag_start_key"] = st.session_state.pop("_pending_slider_start")

                    if (
                        "drag_start_key" not in st.session_state
                        or st.session_state.get("_slider_ticker") != ticker
                        or st.session_state.get("_slider_period") != period_option
                    ):
                        st.session_state["drag_start_key"] = default_start
                        st.session_state["_slider_ticker"] = ticker
                        st.session_state["_slider_period"] = period_option

                    cur_val = st.session_state["drag_start_key"]
                    if cur_val < min_start or cur_val > max_start:
                        st.session_state["drag_start_key"] = max(min_start, min(cur_val, max_start))

                    st.caption(f"🎚️ **{period_option} 고정 구간을 아래 슬라이더로 좌우로 옮겨보세요** (매수 시점이 이동합니다)")

                    col_slider, col_reset = st.columns([5, 1])
                    with col_slider:
                        start_date = st.slider(
                            "매수 시점",
                            min_value=min_start,
                            max_value=max_start,
                            key="drag_start_key",
                            format="YYYY-MM-DD",
                            label_visibility="collapsed",
                        )
                    with col_reset:
                        if st.button("↩️ 최근 기간", use_container_width=True):
                            st.session_state["_pending_slider_start"] = default_start
                            st.rerun()

                    end_date = start_date + duration

            period_str = get_formatted_period(start_date, end_date)
            st.info(f"📌 **현재 계산 구간**: {start_date} ~ {end_date} ({period_str})")

            # --- 전체 차트 고정 출력 (확대/축소 및 드래그 완전 차단) ---
            df_all_reset = df_all.reset_index()
            date_col = "Date" if "Date" in df_all_reset.columns else df_all_reset.columns[0]

            fig = px.line(df_all_reset, x=date_col, y="Close", title="전체 기간 주가 추이 (고정형)")

            fig.add_vrect(
                x0=pd.Timestamp(start_date), x1=pd.Timestamp(end_date),
                fillcolor="blue", opacity=0.15, layer="below", line_width=0,
                annotation_text="투자 구간", annotation_position="top left"
            )

            fig.update_layout(
                xaxis_title="날짜",
                yaxis_title="종가 (원)",
                hovermode="x unified",
                xaxis=dict(fixedrange=True),
                yaxis=dict(
                    fixedrange=True,
                    tickformat=",d"  # 세로축 숫자를 천 단위 콤마가 포함된 일반 정수(원 단위)로 고정
                ),
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
                config={
                    "scrollZoom": False,
                    "displayModeBar": False,
                },
            )

            st.divider()

            # 선택된 구간으로 데이터 슬라이싱
            mask = (df_all.index >= pd.Timestamp(start_date)) & (df_all.index <= pd.Timestamp(end_date))
            df = df_all.loc[mask]

            if df.empty:
                st.warning("선택하신 구간에 해당하는 시세 데이터가 없습니다. (주말이나 공휴일일 수 있으니 날짜를 살짝 조정해 보세요)")
            else:
                buy_price = df.iloc[0]["Close"]
                quantity = math.floor(investment_amount / buy_price)
                remaining_cash = investment_amount - (quantity * buy_price)
                current_price = df.iloc[-1]["Close"]
                total_eval = (quantity * current_price) + remaining_cash

                eval_profit = total_eval - investment_amount
                days_held = (end_date - start_date).days
                total_dps = calculate_etf_dividends(ticker, buy_price, days_held)

                total_div_gross = quantity * total_dps
                tax_base_154 = math.floor(total_div_gross * 0.154)
                total_div_net = total_div_gross - tax_base_154

                total_return = eval_profit + total_div_net
                return_rate = (total_return / investment_amount) * 100

                # --- 결과 출력 ---
                st.subheader(f"📌 {selected_etf_label} 시뮬레이션 결과")

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("매수 주식수", f"{quantity:,} 주")
                col2.metric("매수 시점 주가", f"{buy_price:,.0f} 원")
                col3.metric("기간 종료 평가금액", f"{total_eval:,.0f} 원", delta=f"{eval_profit:,.0f} 원")
                col4.metric("최종 수익 (분배금 포함)", f"{total_return:,.0f} 원", delta=f"{return_rate:.2f}%", help="평가 손익 + 세후 분배금 합계입니다.")

                if eval_profit < 0:
                    st.warning(f"⚠️ 주가가 매수 시점보다 {((current_price - buy_price)/buy_price)*100:.2f}% 변동했습니다. 하지만 분배금을 합산하면 실제 수익률은 {(total_return/investment_amount)*100:.2f}%가 됩니다.")

                st.divider()

                # --- 세금 및 건보료 상세 계산 ---
                total_financial_income = other_income + total_div_gross
                excess_global_income = max(0, total_financial_income - 20000000)
                est_extra_tax = math.floor(excess_global_income * 0.11)

                if insurance_type == "지역가입자" and total_financial_income > 10000000:
                    excess_health_income = total_financial_income - 10000000
                    est_extra_health_annual = math.floor(excess_health_income * 0.0801)
                    est_extra_health_monthly = math.floor(est_extra_health_annual / 12)
                else:
                    est_extra_health_annual = 0
                    est_extra_health_monthly = 0

                st.subheader("⚖️ 세금 및 건강보험료 추가 부담액 상세")
                col_a, col_b = st.columns(2)

                with col_a:
                    if excess_global_income > 0:
                        st.error(f"🚨 **금융소득종합과세 대상**\n* **총 금융소득**: {total_financial_income:,}원\n* 💰 **예상 추가 종합소득세**: **약 +{est_extra_tax:,} 원**")
                    else:
                        st.success(f"✅ **원천징수(15.4%) 분리과세 완료**\n* **총 금융소득**: {total_financial_income:,}원 (2,000만 원 이하)")

                with col_b:
                    if est_extra_health_annual > 0:
                        st.warning(f"⚠️ **건강보험료 추가 부과 대상**\n* 🏥 **연간 추가 건보료**: **약 +{est_extra_health_annual:,} 원**\n* 📅 **월평균**: **약 +{est_extra_health_monthly:,} 원/월**")
                    else:
                        st.info("ℹ️ **건강보험료 추가 인상 없음**")

    except Exception as e:
        st.error("데이터 계산 중 오류가 발생했습니다.")
        with st.expander("🔧 오류 상세 보기 (문제 해결용)"):
            st.exception(e)
