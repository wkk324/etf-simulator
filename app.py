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

def calculate_etf_dividends(ticker, buy_price, days_held):
    rate = DIVIDEND_RATES.get(ticker, 0.020)
    years = max(days_held / 365.0, 0.1)
    return math.floor(buy_price * rate * years)

def get_preset_range(period_option):
    """기간 프리셋(1년/3년/5년/10년/전체)에 해당하는 (시작일, 종료일)을 반환"""
    today_ = datetime.today()
    if period_option == "1년": start_ = today_ - timedelta(days=365)
    elif period_option == "3년": start_ = today_ - timedelta(days=365 * 3)
    elif period_option == "5년": start_ = today_ - timedelta(days=365 * 5)
    elif period_option == "10년": start_ = today_ - timedelta(days=365 * 10)
    else: start_ = datetime(2010, 1, 1)
    return start_.date(), today_.date()

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

st.sidebar.markdown("**투자 기간 (프리셋 또는 차트 드래그로 선택)**")
period_option = st.sidebar.radio("기간 선택", ["1년", "3년", "5년", "10년", "전체"], index=1, horizontal=True, label_visibility="collapsed")

# 프리셋이 바뀌면 시작일/종료일을 프리셋 값으로 초기화 (차트 드래그로 지정했던 구간은 리셋)
if "_prev_period_option" not in st.session_state or st.session_state["_prev_period_option"] != period_option:
    preset_start, preset_end = get_preset_range(period_option)
    st.session_state["start_date_key"] = preset_start
    st.session_state["end_date_key"] = preset_end
    st.session_state["_prev_period_option"] = period_option

start_date = st.sidebar.date_input("시작일", key="start_date_key")
end_date = st.sidebar.date_input("종료일", key="end_date_key")

if st.sidebar.button("↩️ 프리셋 기간으로 초기화"):
    preset_start, preset_end = get_preset_range(period_option)
    st.session_state["start_date_key"] = preset_start
    st.session_state["end_date_key"] = preset_end
    st.rerun()

st.sidebar.markdown("**현재 상황 (세금/건보료 조건)**")
insurance_type = st.sidebar.radio("건강보험 가입 유형", ["지역가입자", "직장가입자"], index=0, horizontal=True)
quick_income = st.sidebar.radio("기타 금융소득 (이자/배당)", ["없음", "3천만", "5천만", "7천만", "1억"], index=0, horizontal=True)
income_map = {"없음": 0, "3천만": 30000000, "5천만": 50000000, "7천만": 70000000, "1억": 100000000}
other_income = income_map[quick_income]

# --- 메인 연산 ---
if ticker:
    with st.spinner(f"'{selected_etf_label}' 시세 데이터 로딩 중..."):
        try:
            df_all = get_price_history(ticker)

            if df_all.empty:
                st.warning("시세 데이터가 존재하지 않습니다.")
            else:
                # --- 차트: 여기서 드래그로 구간을 선택하면 투자 기간이 자동 반영됩니다 ---
                st.subheader("📈 전체 주가 흐름 및 투자 구간 선택")
                st.caption("🖱️ **차트를 드래그**하면 그 구간이 투자 기간으로 자동 반영됩니다 | 🖲️ **마우스 휠**: 확대/축소 | 화면 이동(Pan)은 상단 툴바에서 손모양 아이콘 클릭 후 사용하세요")

                df_all_reset = df_all.reset_index()
                date_col = "Date" if "Date" in df_all_reset.columns else df_all_reset.columns[0]

                fig = px.line(df_all_reset, x=date_col, y="Close", title="전체 기간 주가 추이")

                # 현재 선택된 투자 구간 하이라이트
                fig.add_vrect(
                    x0=pd.Timestamp(start_date), x1=pd.Timestamp(end_date),
                    fillcolor="blue", opacity=0.15, layer="below", line_width=0,
                    annotation_text="투자 구간", annotation_position="top left"
                )

                fig.update_layout(
                    xaxis_title="날짜",
                    yaxis_title="종가 (원)",
                    hovermode="x unified",
                    dragmode="select",  # 드래그 = 구간 선택(Box Select)
                )

                chart_event = st.plotly_chart(
                    fig,
                    use_container_width=True,
                    key="price_chart",
                    on_select="rerun",
                    selection_mode="box",
                    config={
                        "scrollZoom": True,      # 마우스 휠로 확대/축소
                        "displayModeBar": True,  # 상단 툴바(Pan/Zoom/Select 전환) 표시
                    }
                )

                # 드래그로 새 구간을 선택했으면 시작일/종료일 갱신 후 재계산
                # (Plotly 박스 선택 결과 스키마가 버전에 따라 {"x":[x0,x1]} 또는 {"x0":.., "x1":..} 로 달라질 수 있어 둘 다 대응)
                box_sel = []
                if chart_event and chart_event.get("selection"):
                    box_sel = chart_event["selection"].get("box", [])

                new_start = new_end = None
                if box_sel:
                    b = box_sel[0]
                    if "x" in b and b["x"] is not None:
                        x0, x1 = b["x"][0], b["x"][1]
                        new_start, new_end = pd.to_datetime(x0).date(), pd.to_datetime(x1).date()
                    elif "x0" in b and "x1" in b:
                        new_start = pd.to_datetime(b["x0"]).date()
                        new_end = pd.to_datetime(b["x1"]).date()

                if new_start and new_end and new_start != new_end and (new_start, new_end) != (start_date, end_date):
                    st.session_state["start_date_key"] = min(new_start, new_end)
                    st.session_state["end_date_key"] = max(new_start, new_end)
                    st.session_state["_prev_period_option"] = period_option  # 프리셋으로 되돌아가지 않도록 동기화
                    st.rerun()

                st.info(f"📌 **현재 계산 구간**: {start_date} ~ {end_date}  ({(end_date - start_date).days:,}일)")
                st.divider()

                # 선택된 구간으로 데이터 슬라이싱
                mask = (df_all.index >= pd.Timestamp(start_date)) & (df_all.index <= pd.Timestamp(end_date))
                df = df_all.loc[mask]

                if df.empty:
                    st.warning("선택하신 구간에 해당하는 시세 데이터가 없습니다. 구간을 다시 선택해주세요.")
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
                    col3.metric("현재 평가금액", f"{total_eval:,.0f} 원", delta=f"{eval_profit:,.0f} 원")
                    col4.metric("최종 수익 (분배금 포함)", f"{total_return:,.0f} 원", delta=f"{return_rate:.2f}%", help="평가 손익 + 세후 분배금 합계입니다.")

                    if eval_profit < 0:
                        st.warning(f"⚠️ 주가가 매수 시점보다 {((current_price - buy_price)/buy_price)*100:.2f}% 하락했습니다. 하지만 분배금을 합산하면 실제 손실액은 {(total_return/investment_amount)*100:.2f}%로 완화됩니다.")

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
