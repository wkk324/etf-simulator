"""
한국 ETF 투자 시뮬레이터 · 분배금/세금/건강보험료 정산
------------------------------------------------------
2026년 기준 세율·요율 반영
- 소득세 8단계 누진세율 (6% ~ 45%)
- 금융소득종합과세 비교과세 방식 (Gross-up 미반영, ETF 분배금은 원칙적으로 비대상)
- 건강보험료율 7.19%, 장기요양보험료율 0.9448%
"""

from datetime import datetime, timedelta, date
import math

import FinanceDataReader as fdr
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="한국 ETF 분배금·세금 시뮬레이터", layout="wide")

# =========================================================
# 상수 (2026년 기준)
# =========================================================

# 소득세법 제55조 종합소득세 기본세율 (하한, 세율, 누진공제)
TAX_BRACKETS = [
    (14_000_000, 0.06, 0),
    (50_000_000, 0.15, 1_260_000),
    (88_000_000, 0.24, 5_760_000),
    (150_000_000, 0.35, 15_440_000),
    (300_000_000, 0.38, 19_940_000),
    (500_000_000, 0.40, 25_940_000),
    (1_000_000_000, 0.42, 35_940_000),
    (float("inf"), 0.45, 65_940_000),
]

LOCAL_TAX_RATE = 0.10          # 지방소득세 = 소득세의 10%
WITHHOLDING_RATE = 0.14        # 배당소득 원천징수 세율 (지방세 별도 → 실효 15.4%)
FIN_INCOME_THRESHOLD = 20_000_000   # 금융소득종합과세 기준금액

NHIS_RATE = 0.0719             # 2026년 건강보험료율
LTC_RATE = 0.009448            # 2026년 장기요양보험료율
NHIS_REGION_FIN_THRESHOLD = 10_000_000   # 지역가입자 금융소득 반영 기준
NHIS_WORKER_THRESHOLD = 20_000_000       # 직장가입자 보수외소득 기준

PERIOD_DAYS = {"1년": 365, "3년": 365 * 3, "5년": 365 * 5, "10년": 365 * 10}

# 연 분배율 참고값 (사용자가 사이드바에서 직접 수정 가능)
DEFAULT_DIV_RATES = {
    "459580": 0.102,   # TIGER 미국배당+7%프리미엄다우존스
    "474520": 0.120,
    "402970": 0.038,   # ACE 미국배당다우존스
    "133690": 0.009,   # TIGER 미국나스닥100
    "069500": 0.018,   # KODEX 200
    "102110": 0.018,   # TIGER 200
    "368590": 0.013,
}
FALLBACK_DIV_RATE = 0.020

# 국내주식형(매매차익 비과세)으로 확정된 종목
DOMESTIC_EQUITY_CODES = {"069500", "102110", "148020", "152100", "278530", "069660"}

# 이름에 포함되면 '국내주식형이 아님'으로 판정하는 키워드
NON_DOMESTIC_KEYWORDS = [
    "미국", "나스닥", "S&P", "SP500", "다우", "차이나", "중국", "홍콩", "일본", "인도",
    "베트남", "유로", "유럽", "독일", "글로벌", "선진국", "신흥국", "아시아", "대만",
    "브라질", "멕시코", "월드", "해외", "채권", "국고채", "회사채", "금리", "통안",
    "달러", "엔화", "환율", "금현물", "은현물", "원유", "천연가스", "구리", "원자재",
    "commodity", "리츠", "TDF", "레버리지", "인버스", "선물", "커버드콜", "프리미엄",
    "합성", "TR)", "CD금리", "KOFR", "머니마켓",
]


# =========================================================
# 세금 계산 함수
# =========================================================

def progressive_tax(tax_base: float) -> float:
    """종합소득 과세표준에 기본세율을 적용한 산출세액(지방소득세 제외)."""
    tax_base = max(0.0, tax_base)
    for limit, rate, deduction in TAX_BRACKETS:
        if tax_base <= limit:
            return max(0.0, tax_base * rate - deduction)
    return 0.0


def income_tax_total(financial_income: float,
                     other_comprehensive_income: float,
                     income_deduction: float) -> float:
    """
    금융소득(이자+배당)과 그 외 종합소득을 합산한 연간 소득세(지방세 포함).

    금융소득이 2,000만원을 초과하면 '비교과세'를 적용한다.
      · 종합과세 방식 : 2,000만원 x 14% + (초과분 + 기타종합소득 - 소득공제) x 기본세율
      · 분리과세 방식 : 금융소득 전액 x 14% + (기타종합소득 - 소득공제) x 기본세율
      · 실제 세액     : 위 둘 중 큰 금액
    """
    other_base = max(0.0, other_comprehensive_income - income_deduction)

    if financial_income <= FIN_INCOME_THRESHOLD:
        tax = financial_income * WITHHOLDING_RATE + progressive_tax(other_base)
    else:
        excess = financial_income - FIN_INCOME_THRESHOLD
        # ① 종합과세 방식
        base_a = max(0.0, other_comprehensive_income + excess - income_deduction)
        tax_a = FIN_INCOME_THRESHOLD * WITHHOLDING_RATE + progressive_tax(base_a)
        # ② 비교과세(전액 원천징수) 방식
        tax_b = financial_income * WITHHOLDING_RATE + progressive_tax(other_base)
        tax = max(tax_a, tax_b)

    return tax * (1 + LOCAL_TAX_RATE)


def health_insurance_annual(financial_income: float,
                            other_income: float,
                            insurance_type: str) -> float:
    """연간 건강보험료 + 장기요양보험료 (소득분만 계산, 재산·자동차 제외)."""
    if insurance_type == "지역가입자":
        # 금융소득은 1,000만원 초과 시 '전액'이 소득에 반영
        counted_fin = financial_income if financial_income > NHIS_REGION_FIN_THRESHOLD else 0.0
        income_base = counted_fin + other_income
        monthly_health = (income_base / 12) * NHIS_RATE
    else:
        # 직장가입자: 보수외소득이 2,000만원 초과할 때 초과분에만 부과 (전액 본인부담)
        extra_income = financial_income + other_income
        if extra_income <= NHIS_WORKER_THRESHOLD:
            return 0.0
        monthly_health = ((extra_income - NHIS_WORKER_THRESHOLD) / 12) * NHIS_RATE

    monthly_ltc = monthly_health * (LTC_RATE / NHIS_RATE)
    return (monthly_health + monthly_ltc) * 12


# =========================================================
# 데이터 로딩
# =========================================================

@st.cache_data(ttl=3600)
def get_etf_data(sort_by):
    recommended = [
        ("ACE 미국배당다우존스 (402970)", "402970"),
        ("KODEX 200 (069500)", "069500"),
        ("TIGER 미국나스닥100 (133690)", "133690"),
        ("TIGER 미국배당+7%프리미엄다우존스 (459580)", "459580"),
    ]
    others, error = [], None
    try:
        df = fdr.StockListing("ETF/KR")
        if not df.empty:
            df["Symbol"] = df["Symbol"].astype(str).str.zfill(6)
            rec_codes = {c for _, c in recommended}
            df = df[~df["Symbol"].isin(rec_codes)]
            df = df.sort_values(by="Name" if sort_by == "가나다 이름순" else "Symbol")
            others = [(f"{r['Name']} ({r['Symbol']})", str(r["Symbol"])) for _, r in df.iterrows()]
    except Exception as e:
        error = str(e)

    return {label: code for label, code in recommended + others}, error


@st.cache_data(ttl=3600)
def get_price_history(ticker):
    return fdr.DataReader(ticker, start="2010-01-01",
                          end=datetime.today().strftime("%Y-%m-%d"))


def guess_etf_type(label: str, code: str) -> str:
    """ETF 과세 유형 자동 추정."""
    if code in DOMESTIC_EQUITY_CODES:
        return "국내주식형"
    upper = label.upper()
    for kw in NON_DOMESTIC_KEYWORDS:
        if kw.upper() in upper:
            return "기타(해외·채권·파생 등)"
    return "국내주식형"


# =========================================================
# 사이드바
# =========================================================

st.sidebar.header("📋 시뮬레이션 조건")

sort_option = st.sidebar.radio("ETF 목록 정렬", ["가나다 이름순", "종목 코드순"],
                               index=0, horizontal=True)
etf_dict, load_error = get_etf_data(sort_option)
if load_error:
    st.sidebar.warning(f"⚠️ 전체 ETF 목록을 불러오지 못했습니다. 추천 종목만 표시합니다.\n\n({load_error})")

selected_label = st.sidebar.selectbox("ETF 선택", options=list(etf_dict.keys()))
ticker = etf_dict[selected_label]

# --- 과세 유형 ---
auto_type = guess_etf_type(selected_label, ticker)
st.sidebar.markdown("**ETF 과세 유형**")
type_choice = st.sidebar.radio(
    "유형 (자동 추정값 확인 후 필요시 변경)",
    ["자동 추정", "국내주식형 (매매차익 비과세)", "기타 (매매차익 배당소득 과세)"],
    index=0,
)
if type_choice == "자동 추정":
    etf_type = auto_type
    st.sidebar.caption(f"→ 자동 판정: **{auto_type}**")
elif type_choice.startswith("국내주식형"):
    etf_type = "국내주식형"
else:
    etf_type = "기타(해외·채권·파생 등)"

is_domestic_equity = (etf_type == "국내주식형")

# --- 분배율 ---
default_rate = DEFAULT_DIV_RATES.get(ticker, FALLBACK_DIV_RATE)
div_rate = st.sidebar.number_input(
    "연 분배율 (%)", min_value=0.0, max_value=30.0,
    value=round(default_rate * 100, 2), step=0.1,
    help="종목별 참고값이 자동 입력됩니다. 실제 분배 실적에 맞게 수정하세요.",
) / 100

# --- 투자금 ---
inv_map = {"1억": 100_000_000, "3억": 300_000_000, "5억": 500_000_000, "10억": 1_000_000_000}
inv_choice = st.sidebar.radio("투자금", list(inv_map.keys()) + ["기타"], index=0, horizontal=True)
if inv_choice == "기타":
    investment_amount = st.sidebar.number_input(
        "직접 입력 (원)", min_value=10_000, value=50_000_000, step=1_000_000, format="%d")
else:
    investment_amount = inv_map[inv_choice]

# --- 차트/기간 ---
chart_type = st.sidebar.radio("차트 종류", ["선 차트 (Line)", "캔들 차트 (Candle)"],
                              index=0, horizontal=True)
period_mode = st.sidebar.radio("기간 선택 방식",
                               ["기간 범위 자유 선택", "고정 기간 이동 (슬라이더)", "직접 날짜 지정"],
                               index=0)
if period_mode == "직접 날짜 지정":
    period_option = "직접지정"
elif period_mode == "고정 기간 이동 (슬라이더)":
    period_option = "고정기간이동"
    fixed_label = st.sidebar.selectbox("고정 기간", list(PERIOD_DAYS.keys()), index=1)
else:
    period_option = st.sidebar.radio("기본 기간", list(PERIOD_DAYS.keys()) + ["전체"],
                                     index=1, horizontal=True)

# --- 세금 조건 ---
st.sidebar.divider()
st.sidebar.markdown("**💸 세금·건강보험 조건 (연간 기준)**")

insurance_type = st.sidebar.radio("건강보험 가입 유형", ["지역가입자", "직장가입자"],
                                  index=0, horizontal=True)

fin_map = {"없음": 0, "1천만": 10_000_000, "2천만": 20_000_000,
           "3천만": 30_000_000, "5천만": 50_000_000, "1억": 100_000_000}
other_fin_income = fin_map[st.sidebar.select_slider(
    "기타 금융소득 (이자·배당)", options=list(fin_map.keys()), value="없음")]

other_comp_income = st.sidebar.number_input(
    "기타 종합소득금액 (근로·사업 등)", value=0, step=1_000_000, format="%d",
    help="세율 구간 판정에 사용됩니다. 근로소득은 근로소득공제 후 '소득금액' 기준으로 입력하세요.")

income_deduction = st.sidebar.number_input(
    "소득공제 합계", value=1_500_000, step=500_000, format="%d",
    help="인적공제·연금보험료공제 등의 합계. 기본값은 1인 기본공제(150만원)입니다.")

taxable_ratio = st.sidebar.slider(
    "매매차익 과세 반영률 (%)", 0, 100, 100, step=5,
    help="해외형 ETF는 실제 매매차익과 과표기준가 증가분 중 '작은 값'에 과세됩니다. "
         "과표기준가는 조회가 어려우므로 이 비율로 근사합니다. 보수적으로 보려면 100%로 두세요."
) / 100


# =========================================================
# 메인
# =========================================================

st.title("🏦 한국 ETF 분배금·세금 시뮬레이터")
st.caption("과거 주가 데이터를 기반으로 매매차익·분배금·세금·건강보험료를 함께 정산합니다.")

df_all = get_price_history(ticker)
if df_all.empty:
    st.error("가격 데이터를 불러오지 못했습니다. 다른 종목을 선택해 주세요.")
    st.stop()

earliest, latest = df_all.index.min().date(), df_all.index.max().date()

# --- 기간 결정 ---
if period_option == "직접지정":
    c1, c2 = st.columns(2)
    start_date = c1.date_input("매수일", value=max(earliest, latest - timedelta(days=365 * 3)),
                               min_value=earliest, max_value=latest)
    end_date = c2.date_input("매도일", value=latest, min_value=earliest, max_value=latest)
elif period_option == "전체":
    start_date, end_date = earliest, latest
elif period_option == "고정기간이동":
    dur = PERIOD_DAYS[fixed_label]
    max_start = max(earliest, latest - timedelta(days=dur))
    if max_start <= earliest:
        st.warning(f"이 종목의 상장 기간이 {fixed_label}보다 짧아 전체 구간을 사용합니다.")
        start_date, end_date = earliest, latest
    else:
        start_date = st.slider(f"📅 {fixed_label} 기간 이동", min_value=earliest,
                               max_value=max_start, value=max_start, format="YYYY-MM-DD")
        end_date = min(start_date + timedelta(days=dur), latest)
else:
    dur = timedelta(days=PERIOD_DAYS[period_option])
    if earliest >= latest:
        start_date, end_date = earliest, latest
    else:
        start_date, end_date = st.slider(
            "📅 매수·매도 시점 선택", min_value=earliest, max_value=latest,
            value=(max(earliest, latest - dur), latest), format="YYYY-MM-DD")

if start_date >= end_date:
    st.error("매도일은 매수일보다 뒤여야 합니다.")
    st.stop()

holding_days = (end_date - start_date).days
holding_years = holding_days / 365.0

badge = "🇰🇷 국내주식형 · 매매차익 비과세" if is_domestic_equity else "🌏 기타형 · 매매차익 배당소득 과세"
st.info(f"📍 **{start_date} ~ {end_date}** · 총 {holding_days:,}일 (약 {holding_years:.1f}년) 보유 　|　 {badge}")

# --- 차트 ---
dfr = df_all.reset_index()
date_col = "Date" if "Date" in dfr.columns else dfr.columns[0]

if chart_type == "선 차트 (Line)":
    fig = px.line(dfr, x=date_col, y="Close", labels={"Close": "종가", date_col: "날짜"})
    fig.update_traces(hovertemplate="날짜: %{x|%Y-%m-%d}<br>종가: %{y:,.0f}원<extra></extra>")
else:
    hover_text = [
        f"시가: {o:,.0f}원<br>고가: {h:,.0f}원<br>저가: {l:,.0f}원<br>종가: {c:,.0f}원"
        for o, h, l, c in zip(dfr["Open"], dfr["High"], dfr["Low"], dfr["Close"])
    ]
    fig = go.Figure(go.Candlestick(
        x=dfr[date_col], open=dfr["Open"], high=dfr["High"],
        low=dfr["Low"], close=dfr["Close"],
        increasing_line_color="red", decreasing_line_color="blue",
        text=hover_text, hoverinfo="text",
    ))

fig.add_vrect(x0=pd.Timestamp(start_date), x1=pd.Timestamp(end_date),
              fillcolor="blue", opacity=0.15, layer="below", line_width=0)
fig.update_layout(
    xaxis=dict(range=[earliest, latest], tickformat="%Y-%m-%d"),
    yaxis=dict(tickformat=",d"),
    xaxis_rangeslider_visible=False,
    dragmode="pan", margin=dict(t=30, b=20),
)
st.plotly_chart(fig, use_container_width=True,
                config={"scrollZoom": True, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})

# --- 매매 결과 ---
mask = (df_all.index >= pd.Timestamp(start_date)) & (df_all.index <= pd.Timestamp(end_date))
df = df_all.loc[mask]
if df.empty:
    st.error("선택한 기간에 거래 데이터가 없습니다.")
    st.stop()

buy_price = float(df.iloc[0]["Close"])
sell_price = float(df.iloc[-1]["Close"])
quantity = math.floor(investment_amount / buy_price)
if quantity == 0:
    st.error("투자금이 1주 가격보다 적습니다.")
    st.stop()

actual_invested = quantity * buy_price
cash_left = investment_amount - actual_invested
total_eval = quantity * sell_price + cash_left
capital_gain = quantity * (sell_price - buy_price)
price_diff = sell_price - buy_price

st.subheader(f"📌 {selected_label} 시뮬레이션 결과")
c = st.columns(5)
c[0].metric("주식 수", f"{quantity:,} 주")
c[1].metric("매수 주가", f"{buy_price:,.0f} 원")
c[2].metric("매도 주가", f"{sell_price:,.0f} 원",
            delta=f"{price_diff:,.0f} 원 ({price_diff / buy_price * 100:.2f}%)")
c[3].metric("매수 평가금액", f"{actual_invested:,.0f} 원")
c[4].metric("매도 평가금액", f"{total_eval:,.0f} 원",
            delta=f"{capital_gain:,.0f} 원 ({capital_gain / investment_amount * 100:.2f}%)")

# --- 연도별 분배금 산정 (해당 연도 평균가 기준) ---
yearly = []
for year in range(start_date.year, end_date.year + 1):
    y_start = max(start_date, date(year, 1, 1))
    y_end = min(end_date, date(year, 12, 31))
    days = (y_end - y_start).days
    if days <= 0:
        continue
    ymask = (df.index >= pd.Timestamp(y_start)) & (df.index <= pd.Timestamp(y_end))
    avg_price = float(df.loc[ymask, "Close"].mean()) if ymask.any() else buy_price
    dividend = quantity * avg_price * div_rate * (days / 365.0)
    yearly.append({"연도": year, "보유일수": days, "평균주가": avg_price, "분배금(세전)": dividend})

total_dividend = sum(y["분배금(세전)"] for y in yearly)

# --- 매매차익 과세 대상액 ---
if is_domestic_equity:
    taxable_gain = 0.0
else:
    taxable_gain = max(0.0, capital_gain) * taxable_ratio

# --- 연도별 세금·건보료 (한계 부담분) ---
sell_year = end_date.year
total_tax = total_nhis = 0.0
for y in yearly:
    etf_fin = y["분배금(세전)"] + (taxable_gain if y["연도"] == sell_year else 0.0)

    tax_with = income_tax_total(other_fin_income + etf_fin, other_comp_income, income_deduction)
    tax_without = income_tax_total(other_fin_income, other_comp_income, income_deduction)
    nhis_with = health_insurance_annual(other_fin_income + etf_fin, other_comp_income, insurance_type)
    nhis_without = health_insurance_annual(other_fin_income, other_comp_income, insurance_type)

    y["ETF 금융소득"] = etf_fin
    y["소득세(지방세 포함)"] = tax_with - tax_without
    y["건강보험료"] = nhis_with - nhis_without
    y["종합과세"] = (other_fin_income + etf_fin) > FIN_INCOME_THRESHOLD

    total_tax += y["소득세(지방세 포함)"]
    total_nhis += y["건강보험료"]

st.divider()
st.subheader("⚖️ 세금 및 건강보험료")

m = st.columns(4)
m[0].metric("분배금 (세전)", f"{total_dividend:,.0f} 원")
m[1].metric("매매차익 과세대상", f"{taxable_gain:,.0f} 원",
            help="국내주식형 ETF는 매매차익이 비과세이므로 0원입니다.")
m[2].metric("소득세 (지방세 포함)", f"-{total_tax:,.0f} 원")
m[3].metric("건강보험료 증가분", f"-{total_nhis:,.0f} 원")

detail = pd.DataFrame(yearly)
detail["과세방식"] = detail["종합과세"].map({True: "종합과세", False: "분리과세 15.4%"})
st.dataframe(
    detail[["연도", "보유일수", "평균주가", "분배금(세전)", "ETF 금융소득",
            "과세방식", "소득세(지방세 포함)", "건강보험료"]].style.format({
        "평균주가": "{:,.0f}", "분배금(세전)": "{:,.0f}", "ETF 금융소득": "{:,.0f}",
        "소득세(지방세 포함)": "{:,.0f}", "건강보험료": "{:,.0f}",
    }),
    use_container_width=True, hide_index=True,
)

if detail["종합과세"].any():
    st.warning("⚠️ 일부 연도가 **금융소득종합과세 대상**입니다. 위 세액은 종합과세·분리과세 중 큰 금액(비교과세)을 적용한 결과입니다.")
else:
    st.success("✅ 전 기간 분리과세(15.4%) 구간입니다.")

if insurance_type == "지역가입자" and not any(y["건강보험료"] > 0 for y in yearly):
    st.caption("💡 지역가입자는 연 금융소득 1,000만원 초과 시부터 보험료가 부과됩니다. (현재 기준 미달)")

# --- 최종 요약 ---
st.divider()
st.subheader("💰 최종 총수익 (세후)")

net_profit = capital_gain + total_dividend - total_tax - total_nhis
cagr = ((investment_amount + net_profit) / investment_amount) ** (1 / holding_years) - 1 \
    if holding_years > 0 else 0

s = st.columns(5)
s[0].metric("매매차익", f"{capital_gain:,.0f} 원")
s[1].metric("분배금 (세전)", f"{total_dividend:,.0f} 원")
s[2].metric("세금·건보료 합계", f"-{total_tax + total_nhis:,.0f} 원")
s[3].metric("최종 총수익 (세후)", f"{net_profit:,.0f} 원",
            delta=f"{net_profit / investment_amount * 100:.2f}%")
s[4].metric("세후 연평균 수익률 (CAGR)", f"{cagr * 100:.2f}%")

with st.expander("📖 계산 기준 및 한계"):
    st.markdown("""
**적용 기준 (2026년)**
- 종합소득세: 8단계 누진세율 (6% ~ 45%), 산출세액 = 과세표준 × 세율 − 누진공제
- 금융소득종합과세: 연 2,000만원 초과 시 비교과세 (종합과세 방식 vs 전액 14% 방식 중 큰 금액)
- 지방소득세: 소득세의 10%
- 건강보험료율 7.19%, 장기요양보험료율 0.9448%
- 지역가입자: 금융소득 1,000만원 초과 시 **전액** 소득에 반영
- 직장가입자: 보수외소득 2,000만원 **초과분**에 소득월액보험료 부과

**한계**
- 분배금은 실제 지급 내역이 아니라 '연 분배율 × 해당 연도 평균주가'로 추정합니다. 사이드바에서 분배율을 조정하세요.
- 해외형 ETF의 매매차익 과세표준은 실제 차익과 과표기준가 증가분 중 작은 값입니다. 과표기준가 조회가 불가하여 '과세 반영률' 슬라이더로 근사합니다.
- 건강보험료는 소득분만 계산하며 재산·자동차분은 제외했습니다. 지역가입자 최저보험료도 미반영입니다.
- 배당소득 Gross-up은 미반영입니다 (ETF 분배금은 원칙적으로 Gross-up 대상이 아님).
- 세액은 한계 부담분(ETF 소득이 있을 때 − 없을 때)으로 산출했습니다.
- 매매 수수료·증권거래세·운용보수(TER)는 반영되지 않았습니다.

실제 신고 시에는 반드시 세무 전문가 또는 홈택스·건강보험공단 모의계산을 통해 확인하시기 바랍니다.
""")
