from datetime import datetime, timedelta
import math
import FinanceDataReader as fdr
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="한국 ETF 분배금 내역·세금 계산", layout="wide"
)

st.title("🏦 한국 ETF 분배금 내역·세금 계산")
st.caption(
    "실제 한국 상장 ETF와 투자금·기간을 고르면, 과거 지급 분배금과 현재 정책 기준 원천징수 후 금액을 확인합니다."
)

st.divider()


# --- KRX ETF 전체 목록 및 배당 데이터베이스 ---
@st.cache_data
def get_etf_data():
    try:
        df_etf = fdr.StockListing("ETF/KR")
        etf_dict = {
            f"{row['Name']} ({row['Symbol'] if 'Symbol' in row else row['Code']})": str(
                row["Symbol"] if "Symbol" in row else "Code"
            )
            for _, row in df_etf.iterrows()
        }
    except Exception:
        etf_dict = {
            "KODEX 200 (069500)": "069500",
            "TIGER 미국나스닥100 (133690)": "133690",
            "ACE 미국배당다우존스 (402970)": "402970",
            "TIGER 미국배당+7%프리미엄다우존스 (459580)": "459580",
        }
    return etf_dict


# 연간 예상 분배율 DB (대표 고배당 / 지수 / 커버드콜 종목 반영)
DIVIDEND_RATES = {
    "459580": 0.102,  # TIGER 미국배당+7%프리미엄 (약 10.2%)
    "474520": 0.120,  # 15%프리미엄 커버드콜 계열 (약 12.0%)
    "402970": 0.038,  # ACE 미국배당다우존스 (약 3.8%)
    "133690": 0.009,  # TIGER 미국나스닥100 (약 0.9%)
    "069500": 0.018,  # KODEX 200 (약 1.8%)
    "102110": 0.018,  # TIGER 200 (약 1.8%)
    "368590": 0.013,  # ACE 미국S&P500 (약 1.3%)
}


def calculate_etf_dividends(ticker, buy_price, days_held):
    rate = DIVIDEND_RATES.get(ticker, 0.020)  # 기본 평균 2.0%
    years = max(days_held / 365.0, 0.1)
    return math.floor(buy_price * rate * years)


etf_dict = get_etf_data()
etf_options = list(etf_dict.keys())

# --- 사이드바 ---
st.sidebar.header("📋 이번 비교 조건")

# 1. 추천 ETF 퀵 선택 버튼
st.sidebar.markdown("**💡 테마별 추천 ETF 퀵 선택**")
quick_etf = st.sidebar.radio(
    "추천 ETF",
    [
        "직접 검색",
        "🔥 초고배당(연~10% 커버드콜)",
        "💰 배당성장(연~3.8% SCHD)",
        "📈 대표지수(S&P500 / 200)",
    ],
    index=0,
)

default_index = 0
if "초고배당" in quick_etf:
    for idx, opt in enumerate(etf_options):
        if "459580" in opt:
            default_index = idx
            break
elif "배당성장" in quick_etf:
    for idx, opt in enumerate(etf_options):
        if "402970" in opt or "미국배당다우존스" in opt:
            default_index = idx
            break
elif "대표지수" in quick_etf:
    for idx, opt in enumerate(etf_options):
        if "069500" in opt:
            default_index = idx
            break

selected_etf_label = st.sidebar.selectbox(
    "한국 상장 ETF 검색 및 선택",
    options=etf_options,
    index=default_index,
)

ticker = etf_dict[selected_etf_label]

# 2. 투자금 선택 (1억, 3억, 5억, 10억으로 정돈)
st.sidebar.markdown("**투자금**")
quick_money = st.sidebar.radio(
    "투자금 선택",
    ["1억", "3억", "5억", "10억"],
    horizontal=True,
    label_visibility="collapsed",
)

money_map = {
    "1억": 100000000,
    "3억": 300000000,
    "5억": 500000000,
    "10억": 1000000000,
}

investment_amount = st.sidebar.number_input(
    "투자금 직접 입력 (원)",
    value=money_map[quick_money],
    step=1000000,
    format="%d",
)

# 3. 투자 기간 선택 (1년, 3년, 5년, 10년, 전체)
st.sidebar.markdown("**투자 기간**")
period_option = st.sidebar.radio(
    "기간 선택",
    ["1년", "3년", "5년", "10년", "전체"],
    index=1,
    horizontal=True,
    label_visibility="collapsed",
)

today = datetime.today()
if period_option == "1년":
    calc_start = today - timedelta(days=365)
elif period_option == "3년":
    calc_start = today - timedelta(days=365 * 3)
elif period_option == "5년":
    calc_start = today - timedelta(days=365 * 5)
elif period_option == "10년":
    calc_start = today - timedelta(days=365 * 10)
else:
    calc_start = datetime(2010, 1, 1)

start_date = st.sidebar.date_input("시작일", value=calc_start)
end_date = st.sidebar.date_input("종료일", value=today)

# 4. 현재 상황 (세금 조건)
st.sidebar.markdown("**현재 상황 (세금/건보료 조건)**")
insurance_type = st.sidebar.radio(
    "건강보험 가입 유형",
    ["지역가입자", "직장가입자"],
    index=0,
    horizontal=True,
)

quick_income = st.sidebar.radio(
    "기타 금융소득 (이자/배당)",
    ["없음", "3천만", "5천만", "7천만", "1억"],
    index=0,
    horizontal=True,
)

income_map = {
    "없음": 0,
    "3천만": 30000000,
    "5천만": 50000000,
    "7천만": 70000000,
    "1억": 100000000,
}
other_income = income_map[quick_income]


# --- 메인 실행 연산 ---
if ticker:
    with st.spinner(f"'{selected_etf_label}' 정산 중..."):
        try:
            df = fdr.DataReader(
                ticker,
                start=start_date.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
            )

            if df.empty:
                st.warning("시세 데이터가 존재하지 않습니다.")
            else:
                buy_price = df.iloc[0]["Close"]
                quantity = math.floor(investment_amount / buy_price)
                remaining_cash = investment_amount - (
                    quantity * buy_price
                )
                current_price = df.iloc[-1]["Close"]
                total_eval = (quantity * current_price) + remaining_cash

                # 보유 일수 및 분배금 계산
                days_held = (end_date - start_date).days
                total_dps = calculate_etf_dividends(
                    ticker, buy_price, days_held
                )

                # 분배금 수입 산정
                total_div_gross = quantity * total_dps
                tax_base_154 = math.floor(
                    total_div_gross * 0.154
                )  # 원천징수(15.4%)
                total_div_net = total_div_gross - tax_base_154

                # 금융소득 계산 (기타 금융소득 + 이번 ETF 분배금)
                total_financial_income = other_income + total_div_gross

                # --- 1. 금융소득종합과세 예상 추가 세액 산출 ---
                excess_global_income = max(
                    0, total_financial_income - 20000000
                )
                est_extra_tax = math.floor(
                    excess_global_income * 0.11
                )

                # --- 2. 건강보험료 연간 추가 부과액 산출 ---
                if (
                    insurance_type == "지역가입자"
                    and total_financial_income > 10000000
                ):
                    excess_health_income = total_financial_income - 10000000
                    est_extra_health_annual = math.floor(
                        excess_health_income * 0.0801
                    )
                    est_extra_health_monthly = math.floor(
                        est_extra_health_annual / 12
                    )
                else:
                    est_extra_health_annual = 0
                    est_extra_health_monthly = 0

                # --- 결과 리포트 출력 ---
                st.subheader(f"📌 {selected_etf_label} 시뮬레이션 결과")

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("매수 주식수", f"{quantity:,} 주")
                col2.metric("매수 시점 주가", f"{buy_price:,.0f} 원")
                col3.metric("현재 평가금액", f"{total_eval:,.0f} 원")
                col4.metric(
                    "세후 실수령 분배금",
                    f"{total_div_net:,} 원",
                    delta=f"주당 {total_dps:,}원 (원천징수 -{tax_base_154:,}원)",
                )

                st.divider()

                # --- 세금 및 건보료 상세 계산 결과 박스 ---
                st.subheader("⚖️ 세금 및 건강보험료 추가 부담액 상세")

                col_a, col_b = st.columns(2)

                with col_a:
                    if excess_global_income > 0:
                        st.error(
                            f"""🚨 **금융소득종합과세 대상**
* **총 금융소득**: {total_financial_income:,}원 (기준 2,000만 원 초과)
* **초과 과세표준**: {excess_global_income:,}원
* 💰 **예상 추가 종합소득세**: **약 +{est_extra_tax:,} 원** *(원천징수 15.4% 외 추가 부담)*
"""
                        )
                    else:
                        st.success(
                            f"""✅ **원천징수(15.4%) 분리과세 완료**
* **총 금융소득**: {total_financial_income:,}원 (2,000만 원 이하)
* 💡 추가로 내야 할 종합소득세가 없습니다.
"""
                        )

                with col_b:
                    if est_extra_health_annual > 0:
                        st.warning(
                            f"""⚠️ **건강보험료 추가 부과 대상**
* **총 금융소득**: {total_financial_income:,}원 (지역가입자 기준 1,000만 원 초과)
* 🏥 **연간 추가 건보료**: **약 +{est_extra_health_annual:,} 원**
* 📅 **월평균 추가 건보료**: **약 +{est_extra_health_monthly:,} 원/월**
"""
                        )
                    else:
                        st.info(
                            """ℹ️ **건강보험료 추가 인상 없음**
* 기준 금액(1,000만 원) 이하이거나 직장가입자 요건을 충족합니다.
"""
                        )

                st.divider()

                st.subheader("📈 해당 기간 주가 흐름")
                st.line_chart(df["Close"])

        except Exception as e:
            st.error("데이터 계산 중 오류가 발생했습니다.")
