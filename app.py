"""
한국 ETF 투자 시뮬레이터 · 분배금/세금/건강보험료 정산
------------------------------------------------------
2026년 기준 세율·요율 반영
- 소득세 8단계 누진세율 (6% ~ 45%)
- 금융소득종합과세 비교과세 방식
- 건강보험료율 7.19%, 장기요양보험료율 0.9448%
- 국내상장 ETF 과표증분 기준 과세 반영 (분배금 / 매매차익)
"""

from datetime import datetime, timedelta
import math

import FinanceDataReader as fdr
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="ETF 분배금·세금 시뮬레이터", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 4rem; padding-bottom: 1.5rem; max-width: 1200px; }
h1 { font-size: 1.55rem !important; margin-bottom: 0.2rem !important; }
h2 { font-size: 1.05rem !important; margin-top: 0.4rem !important; margin-bottom: 0.3rem !important; }
h3 { font-size: 0.95rem !important; margin-top: 0.3rem !important; margin-bottom: 0.2rem !important; }
p, li, .stCaption, [data-testid="stCaptionContainer"] { font-size: 0.92rem !important; }
[data-testid="stMetricValue"] { font-size: 1.15rem !important; }
[data-testid="stMetricLabel"] { font-size: 0.8rem !important; }
[data-testid="stMetricDelta"] { font-size: 0.8rem !important; }
div[data-testid="stVerticalBlock"] { gap: 0.45rem !important; }
hr { margin: 0.4rem 0 !important; }
[data-testid="stDataFrame"] { font-size: 0.88rem !important; }
section[data-testid="stSidebar"] .block-container { padding-top: 1.2rem; }
section[data-testid="stSidebar"] label p { font-size: 0.9rem !important; }
section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] { gap: 0.9rem !important; }
section[data-testid="stSidebar"] div[role="radiogroup"] label { padding: 0.15rem 0 !important; }
section[data-testid="stSidebar"] hr { margin: 0.8rem 0 !important; }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 상수 (2026년 기준)
# =========================================================

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

LOCAL_TAX_RATE = 0.10
WITHHOLDING_RATE = 0.14
FIN_INCOME_THRESHOLD = 20_000_000

NHIS_RATE = 0.0719
LTC_RATE = 0.009448
NHIS_REGION_FIN_THRESHOLD = 10_000_000
NHIS_WORKER_THRESHOLD = 20_000_000

PERIOD_DAYS = {"1년": 365, "3년": 365 * 3, "5년": 365 * 5, "10년": 365 * 10}

BENCHMARK_OPTIONS = {
    "없음": None,
    "KOSPI 200 (069500)": "069500",
    "KOSPI 지수": "KS11",
    "코스닥 지수": "KQ11",
}

# (연 분배율, 분배금 과표 반영률) 참고값 — 사이드바에서 수정 가능
# 과표 반영률: 분배금 중 실제로 과세되는 비율 (과표증분 / 분배금)
DEFAULT_ETF_PARAMS = {
    "498400": (0.150, 0.02),   # KODEX 200타겟위클리커버드콜 (목표 15%, 과표증분 거의 0)
    "459580": (0.102, 0.30),   # TIGER 미국배당+7%프리미엄다우존스
    "474520": (0.120, 0.30),
    "402970": (0.038, 1.00),   # ACE 미국배당다우존스
    "133690": (0.009, 1.00),   # TIGER 미국나스닥100
    "069500": (0.018, 1.00),   # KODEX 200
    "102110": (0.018, 1.00),   # TIGER 200
    "368590": (0.013, 1.00),
}
FALLBACK_PARAMS = (0.020, 1.00)

RECOMMENDED_ETFS = [
    ("ACE 미국배당다우존스", "402970"),
    ("KODEX 200", "069500"),
    ("KODEX 200타겟위클리커버드콜", "498400"),
    ("TIGER 미국나스닥100", "133690"),
    ("TIGER 미국배당+7%프리미엄다우존스", "459580"),
]

# ETF 브랜드(상품명 접두어) → 자산운용사. 브랜드명이 종목명 맨 앞에 붙는 국내 관행을 이용해 추정한다.
BRAND_TO_ISSUER = {
    "KODEX": "삼성자산운용",
    "KOACT": "삼성액티브자산운용",
    "TIGER": "미래에셋자산운용",
    "TIMEFOLIO": "타임폴리오자산운용",
    "RISE": "KB자산운용",
    "ACE": "한국투자신탁운용",
    "VITA": "한국투자밸류자산운용",
    "SOL": "신한자산운용",
    "WOORI": "우리자산운용",
    "WON": "우리자산운용",
    "마이티": "DB자산운용",
    "UNICORN": "현대자산운용",
    "마이다스": "마이다스에셋자산운용",
    "MIDAS": "마이다스에셋자산운용",
    "PLUS": "한화자산운용",
    "DAISHIN343": "대신자산운용",
    "HANARO": "NH-Amundi자산운용",
    "에셋플러스": "에셋플러스자산운용",
    "KOSEF": "키움자산운용",
    "히어로즈": "키움자산운용",
    "HEROES": "키움자산운용",
    "KIWOOM": "키움자산운용",
    "파워": "교보악사자산운용",
    "1Q": "하나자산운용",
    "IBK": "IBK자산운용",
    "ITF": "IBK자산운용",
    "TREX": "유리자산운용",
    "HK": "흥국자산운용",
    "BNK": "BNK자산운용",
    "KCGI": "KCGI자산운용",
    "TIME": "타임폴리오자산운용",
    "TRUSTON": "트러스톤자산운용",
    "FOCUS": "브이아이자산운용",
    "DS": "DS자산운용",
    "더제이": "더제이자산운용",
    "아이엠에셋": "iM에셋자산운용",
}


def guess_issuer(name: str) -> str:
    """종목명 앞부분의 브랜드로 자산운용사를 추정한다."""
    upper = name.upper()
    for brand, issuer in sorted(BRAND_TO_ISSUER.items(), key=lambda kv: -len(kv[0])):
        if upper.startswith(brand.upper()):
            return issuer
    return "확인 필요"

# 국내주식형(매매차익 비과세) 확정 종목
DOMESTIC_EQUITY_CODES = {
    "069500", "102110", "148020", "152100", "278530", "069660",
    "498400",  # KOSPI200 커버드콜 (국내주식 + 국내 장내파생)
    "122630", "252670",  # KODEX 레버리지 / 200선물인버스2X
}

# 해외 자산 → 국내주식형 아님
FOREIGN_KEYWORDS = [
    "미국", "나스닥", "S&P", "SP500", "다우", "차이나", "중국", "홍콩", "일본", "인도",
    "베트남", "유로", "유럽", "독일", "글로벌", "선진국", "신흥국", "아시아", "대만",
    "브라질", "멕시코", "월드", "해외", "필리핀", "인니", "인도네시아", "러시아",
]

# 주식 외 자산군 → 국내주식형 아님
ASSET_CLASS_KEYWORDS = [
    "채권", "국고채", "회사채", "금리", "통안", "CD금리", "KOFR", "머니마켓", "MMF",
    "달러", "엔화", "환율", "금현물", "은현물", "골드", "실버", "원유", "천연가스",
    "구리", "원자재", "백금", "팔라듐", "농산물", "콩", "옥수수",
    "리츠", "TDF", "혼합", "물가", "크레딧",
]

# 파생 활용 상품 → 기초자산이 국내 지수인지 추가 확인 필요
DERIVATIVE_KEYWORDS = ["커버드콜", "프리미엄", "레버리지", "인버스", "선물", "합성"]

# 국내 지수 기반임을 나타내는 키워드
DOMESTIC_INDEX_KEYWORDS = ["코스피", "KOSPI", "코스닥", "KOSDAQ", "KRX", "K200", "200"]


# =========================================================
# 세금 계산
# =========================================================

def progressive_tax(tax_base: float) -> float:
    tax_base = max(0.0, tax_base)
    for limit, rate, deduction in TAX_BRACKETS:
        if tax_base <= limit:
            return max(0.0, tax_base * rate - deduction)
    return 0.0


EARNED_INCOME_DEDUCTION_BRACKETS = [
    (5_000_000, 0.70, 0),
    (15_000_000, 0.40, 3_500_000),
    (45_000_000, 0.15, 7_500_000),
    (100_000_000, 0.05, 12_000_000),
    (float("inf"), 0.02, 14_750_000),
]


def earned_income_deduction(gross_salary: float) -> float:
    """총급여액에 대한 근로소득공제액 (공제 한도 2,000만원)."""
    gross_salary = max(0.0, gross_salary)
    prev_limit = 0
    for limit, rate, base_deduction in EARNED_INCOME_DEDUCTION_BRACKETS:
        if gross_salary <= limit:
            return min(base_deduction + (gross_salary - prev_limit) * rate, 20_000_000)
        prev_limit = limit
    return 0.0


def income_tax_total(financial_income, other_comprehensive_income, income_deduction):
    """연간 소득세(지방소득세 포함). 금융소득 2천만원 초과 시 비교과세 적용."""
    other_base = max(0.0, other_comprehensive_income - income_deduction)

    if financial_income <= FIN_INCOME_THRESHOLD:
        tax = financial_income * WITHHOLDING_RATE + progressive_tax(other_base)
    else:
        excess = financial_income - FIN_INCOME_THRESHOLD
        tax_a = FIN_INCOME_THRESHOLD * WITHHOLDING_RATE + \
            progressive_tax(max(0.0, other_comprehensive_income + excess - income_deduction))
        tax_b = financial_income * WITHHOLDING_RATE + progressive_tax(other_base)
        tax = max(tax_a, tax_b)

    return tax * (1 + LOCAL_TAX_RATE)


def health_insurance_annual(financial_income, other_income, insurance_type):
    """연간 건강보험료 + 장기요양보험료 (소득분만, 재산·자동차 제외)."""
    if insurance_type == "지역가입자":
        counted = financial_income if financial_income > NHIS_REGION_FIN_THRESHOLD else 0.0
        monthly = (counted + other_income) / 12 * NHIS_RATE
    else:
        extra = financial_income + other_income
        if extra <= NHIS_WORKER_THRESHOLD:
            return 0.0
        monthly = (extra - NHIS_WORKER_THRESHOLD) / 12 * NHIS_RATE
    return (monthly + monthly * (LTC_RATE / NHIS_RATE)) * 12


# =========================================================
# 데이터
# =========================================================

@st.cache_data(ttl=3600)
def get_etf_data(sort_by):
    recommended_fallback = [
        ("ACE 미국배당다우존스 (402970)", "402970"),
        ("KODEX 200 (069500)", "069500"),
        ("KODEX 200타겟위클리커버드콜 (498400)", "498400"),
        ("TIGER 미국나스닥100 (133690)", "133690"),
        ("TIGER 미국배당+7%프리미엄다우존스 (459580)", "459580"),
    ]
    error = None
    try:
        df = fdr.StockListing("ETF/KR")
        if df.empty:
            raise ValueError("빈 목록이 반환되었습니다.")
        df["Symbol"] = df["Symbol"].astype(str).str.zfill(6)
        df = df.sort_values(by="Name" if sort_by == "가나다 이름순" else "Symbol")
        items = [(f"{r['Name']} ({r['Symbol']})", str(r["Symbol"])) for _, r in df.iterrows()]
    except Exception as e:
        error = str(e)
        items = recommended_fallback
    return {label: code for label, code in items}, error


@st.cache_data(ttl=3600)
def get_price_history(ticker):
    return fdr.DataReader(ticker, start="2010-01-01",
                          end=datetime.today().strftime("%Y-%m-%d"))


def guess_etf_type(label: str, code: str):
    """ETF 과세 유형 추정. (유형, 판정근거) 반환."""
    if code in DOMESTIC_EQUITY_CODES:
        return "국내주식형", "사전 등록된 국내주식형 종목"

    upper = label.upper()
    for kw in FOREIGN_KEYWORDS:
        if kw.upper() in upper:
            return "기타", f"해외 자산 키워드 '{kw}' 감지"
    for kw in ASSET_CLASS_KEYWORDS:
        if kw.upper() in upper:
            return "기타", f"주식 외 자산군 키워드 '{kw}' 감지"

    hit_deriv = next((kw for kw in DERIVATIVE_KEYWORDS if kw.upper() in upper), None)
    if hit_deriv:
        hit_dom = next((kw for kw in DOMESTIC_INDEX_KEYWORDS if kw.upper() in upper), None)
        if hit_dom:
            return "국내주식형", f"'{hit_deriv}'이지만 국내지수('{hit_dom}') 기반 → 국내주식+국내 장내파생"
        return "기타", f"파생 활용 키워드 '{hit_deriv}' 감지 (기초자산 확인 필요)"

    return "국내주식형", "해외·타자산 키워드 없음"


# =========================================================
# 시뮬레이션 엔진 (거치식/적립식 · 분배금 재투자 · MDD)
# =========================================================

def build_anchors(df: pd.DataFrame):
    """월말 기준 매수/분배 이벤트 날짜(anchor)를 만든다. 첫 anchor=매수일, 마지막=매도일(월말이 아니면 stub)."""
    if df.empty:
        return [], set()
    first, last = df.index.min(), df.index.max()
    month_ends = [g.index.max() for _, g in df.groupby(pd.Grouper(freq="ME")) if not g.empty]
    month_ends = sorted(d for d in month_ends if first < d <= last)
    # last 날짜가 그 달의 실제 월말 근처(휴장일 포함 최근 3일 이내)가 아니라면,
    # 아직 끝나지 않은 달의 데이터일 뿐이므로 정기 매수 스케줄에서 제외하고 stub으로만 처리한다.
    if month_ends and month_ends[-1] == last and last.day < last.days_in_month - 3:
        month_ends.pop()
    scheduled = [first] + month_ends
    anchors = list(scheduled)
    if anchors[-1] < last:
        anchors.append(last)
    return anchors, set(scheduled)


def run_simulation(df: pd.DataFrame, invest_mode, lumpsum_amount, monthly_amount,
                   is_adjusted_price, div_rate, monthly_dps, reinvest):
    """월 단위 근사로 매수(거치식/적립식)·분배금·재투자를 시뮬레이션한다."""
    anchors, scheduled = build_anchors(df)

    quantity = 0.0
    cash_balance = 0.0
    total_cash_contributed = 0.0
    total_dividend_gross = 0.0
    monthly_records = []
    anchor_quantities = []
    prev_anchor = anchors[0]

    for i, anchor in enumerate(anchors):
        price = float(df.loc[anchor, "Close"])
        dividend = 0.0

        if i > 0:
            period_days = (anchor - prev_anchor).days
            if not is_adjusted_price:
                if monthly_dps is not None:
                    dividend = quantity * monthly_dps * (period_days / 30.44)
                else:
                    dividend = quantity * price * div_rate * (period_days / 365.0)
            total_dividend_gross += dividend
            monthly_records.append({
                "연도": anchor.year, "보유일수": period_days,
                "주가": price, "분배금(세전)": dividend,
            })

        contribution = 0.0
        if anchor in scheduled:
            if i == 0:
                contribution = lumpsum_amount if invest_mode == "거치식" else monthly_amount
            elif invest_mode == "적립식":
                contribution = monthly_amount
        total_cash_contributed += contribution

        cash_balance += contribution + (dividend if reinvest else 0.0)
        new_shares = math.floor(cash_balance / price) if price > 0 else 0
        quantity += new_shares
        cash_balance -= new_shares * price

        anchor_quantities.append((anchor, quantity))
        prev_anchor = anchor

    shares_series = pd.Series({a: q for a, q in anchor_quantities}).reindex(df.index, method="ffill").fillna(0.0)
    value_series = shares_series * df["Close"]
    running_max = value_series.cummax()
    drawdown = (value_series - running_max) / running_max.where(running_max > 0)
    mdd = abs(float(drawdown.min())) if not drawdown.empty and drawdown.notna().any() else 0.0

    sell_price = float(df["Close"].iloc[-1])
    total_eval = quantity * sell_price + cash_balance
    capital_gain = total_eval - total_cash_contributed - (total_dividend_gross if reinvest else 0.0)

    return {
        "quantity": quantity,
        "sell_price": sell_price,
        "total_cash_contributed": total_cash_contributed,
        "leftover_cash": cash_balance,
        "total_eval": total_eval,
        "capital_gain": capital_gain,
        "total_dividend_gross": total_dividend_gross,
        "monthly_records": monthly_records,
        "mdd": mdd,
    }


# =========================================================
# 사이드바
# =========================================================

st.sidebar.header("📋 시뮬레이션 조건")

sort_option = st.sidebar.radio("ETF 목록 정렬", ["가나다 이름순", "종목 코드순"],
                               index=0, horizontal=True)
etf_dict, load_error = get_etf_data(sort_option)
if load_error:
    st.sidebar.warning(f"⚠️ 전체 ETF 목록 로딩 실패. 추천 종목만 표시합니다.\n\n({load_error})")

code_to_label = {code: label for label, code in etf_dict.items()}

st.sidebar.markdown("**⭐ 추천 ETF**")
for name, code in RECOMMENDED_ETFS:
    if code in code_to_label and st.sidebar.button(name, use_container_width=True, key=f"rec_{code}"):
        st.session_state["etf_select"] = code_to_label[code]

selected_label = st.sidebar.selectbox("ETF 선택", options=list(etf_dict.keys()), key="etf_select")
ticker = etf_dict[selected_label]
issuer = guess_issuer(selected_label)
st.sidebar.caption(f"🏢 자산운용사: **{issuer}**" if issuer != "확인 필요"
                   else "🏢 자산운용사: 브랜드 인식 실패 — 네이버 금융에서 확인하세요")
st.sidebar.link_button(
    "🔗 상품 상세정보 보기 (네이버 금융)",
    f"https://finance.naver.com/item/main.naver?code={ticker}",
    use_container_width=True,
    help="선택한 ETF의 시세·기초지수·자산운용사 등 기본 정보를 새 탭에서 확인합니다. "
         "운용보수·투자설명서 등 상세 자료는 자산운용사(KODEX/TIGER/ACE 등) 홈페이지를 확인하세요.")

# --- 주가 데이터 성격 ---
st.sidebar.divider()
st.sidebar.markdown("**📈 주가 데이터 기준**")
price_basis = st.sidebar.radio(
    "가격 데이터 성격",
    ["원주가 (분배락 반영, 분배금 별도 가산)", "수정주가 (분배금 재투자 반영)"],
    index=0,
    help="수정주가라면 매매차익에 분배금이 이미 포함되어 있어 별도 가산 시 이중 계산됩니다. "
         "MTS 실제 종가와 비교해 분배락일에 가격이 떨어지면 '원주가'입니다.",
)
is_adjusted_price = price_basis.startswith("수정주가")

# --- 과세 유형 ---
st.sidebar.divider()
auto_type, auto_reason = guess_etf_type(selected_label, ticker)
st.sidebar.markdown("**⚖️ ETF 과세 유형**")
type_choice = st.sidebar.radio(
    "유형",
    ["자동 추정", "국내주식형 (매매차익 비과세)", "기타 (매매차익 배당소득 과세)"],
    index=0,
    help="**국내주식형**: 코스피·코스닥 등 국내 상장주식에 60% 이상 투자하는 ETF(예: KODEX 200). "
         "매매차익은 비과세이고 분배금만 배당소득세 15.4%가 붙습니다.\n\n"
         "**기타**: 해외주식·채권·원자재·통화·파생상품 등 위 조건에 안 맞는 나머지 ETF. "
         "매매차익도 분배금과 똑같이 배당소득세 15.4%가 과세되며, 금융소득종합과세 대상이 될 수 있습니다.\n\n"
         "**자동 추정**: ETF 이름의 키워드(미국·나스닥·채권·커버드콜 등)로 앱이 유형을 추측합니다. "
         "이름만 보고 판단하므로 100% 정확하지 않을 수 있어, 애매하면 운용사 홈페이지에서 확인 후 직접 선택하세요.",
)
if type_choice == "자동 추정":
    etf_type = auto_type
    st.sidebar.caption(f"→ **{auto_type}** · {auto_reason}")
else:
    etf_type = "국내주식형" if type_choice.startswith("국내주식형") else "기타"
is_domestic_equity = (etf_type == "국내주식형")

# --- 분배금 설정 ---
st.sidebar.divider()
st.sidebar.markdown("**💵 분배금 설정**")

def_rate, def_tax_ratio = DEFAULT_ETF_PARAMS.get(ticker, FALLBACK_PARAMS)

div_input_mode = st.sidebar.radio(
    "입력 방식",
    ["연 분배율(%)", "월 주당 분배금(원)"],
    index=0, horizontal=True,
    help="실제 분배금은 그 기간 펀드가 거둔 배당·이자·옵션프리미엄 수익에 따라 매번 달라지고, "
         "이 앱은 실제 지급 내역을 갖고 있지 않아 아래 두 방식 중 하나로 **추정**합니다.\n\n"
         "**연 분배율(%)**: 분배금이 주가에 비례한다고 가정(분배금 = 주가 × 연분배율). "
         "배당주형 ETF(ACE 미국배당다우존스 등)처럼 '연 배당수익률 약 X%'로 공지되는 상품에 적합합니다.\n\n"
         "**월 주당 분배금(원)**: 주가와 무관하게 매달 고정 금액을 지급한다고 가정. "
         "위클리·월 커버드콜 ETF처럼 '월 목표 분배금 XXX원'을 타겟팅하는 상품에 적합합니다.\n\n"
         "정확한 값은 운용사 홈페이지의 실제 월별 분배금 공지를 확인해 입력하세요.")
if div_input_mode == "연 분배율(%)":
    div_rate = st.sidebar.number_input(
        "연 분배율 (%)", min_value=0.0, max_value=40.0,
        value=round(def_rate * 100, 2), step=0.1,
        help="종목별 참고값이 자동 입력됩니다. 운용사 공지의 실제 분배 실적으로 수정하세요.") / 100
    monthly_dps = None
else:
    monthly_dps = st.sidebar.number_input(
        "월 주당 분배금 (원)", min_value=0.0, value=330.0, step=10.0,
        help="예: KODEX 200타겟위클리커버드콜은 월 320~350원 수준입니다.")
    div_rate = None

div_taxable_ratio = st.sidebar.slider(
    "분배금 과표 반영률 (%)", 0, 100, int(def_tax_ratio * 100), step=1,
    help="분배금은 '과표증분'과 '실제 분배금' 중 작은 금액에 15.4%가 과세됩니다. "
         "커버드콜 ETF의 옵션 프리미엄은 과표에 잡히지 않는 경우가 많아 과표증분이 0에 가깝습니다. "
         "운용사 분배금 공지의 '주당 과세표준액 증분'을 확인해 입력하세요.\n\n"
         "**과표증분이란?** 운용사가 시장 종가와 별도로 매일 산출·공시하는 '과세표준 기준가격(과표기준가)'이 "
         "매수 시점부터 분배(또는 매도) 시점까지 오른 차액입니다. 과표기준가는 시장가격과 달리 "
         "편입자산의 배당·이자·실현손익 등 세법상 과세 대상 소득만 누적 반영한 값이라, 실제 시세차익·분배금과는 "
         "다를 수 있습니다. 세법은 투자자에게 유리하게 실제 이익과 과표증분 중 **작은 금액에만** 과세하도록 "
         "정하고 있어, 시세는 많이 올라도 과표증분이 작으면 세금이 거의 안 붙을 수 있습니다.") / 100

# --- 투자 방식 ---
st.sidebar.divider()
st.sidebar.markdown("**💰 투자 방식**")
invest_mode_label = st.sidebar.radio("투자 방식", ["거치식 (일시불)", "적립식 (매월 정액)"],
                                     index=0, horizontal=True)
invest_mode = "거치식" if invest_mode_label.startswith("거치식") else "적립식"

if invest_mode == "거치식":
    inv_map = {"1억": 100_000_000, "3억": 300_000_000, "5억": 500_000_000, "10억": 1_000_000_000}
    inv_choice = st.sidebar.radio("투자금", list(inv_map.keys()) + ["기타"], index=0, horizontal=True)
    if inv_choice == "기타":
        lumpsum_amount = st.sidebar.number_input(
            "직접 입력 (원)", min_value=10_000, value=50_000_000, step=1_000_000, format="%d")
    else:
        lumpsum_amount = inv_map[inv_choice]
    monthly_amount = 0.0
else:
    monthly_map = {"50만원": 500_000, "100만원": 1_000_000, "200만원": 2_000_000, "300만원": 3_000_000}
    monthly_choice = st.sidebar.radio("매월 투자금액", list(monthly_map.keys()) + ["기타"],
                                      index=1, horizontal=True)
    if monthly_choice == "기타":
        monthly_amount = st.sidebar.number_input(
            "직접 입력 (원/월)", min_value=10_000, value=1_000_000, step=100_000, format="%d")
    else:
        monthly_amount = monthly_map[monthly_choice]
    lumpsum_amount = 0.0

reinvest_dividends = st.sidebar.checkbox(
    "분배금 재투자 (복리)", value=False,
    help="체크 시 분배금을 현금으로 받는 대신 매월 말 같은 ETF를 추가 매수합니다(월 단위 근사). "
         "세금은 재투자 여부와 무관하게 분배 시점마다 부과됩니다.")

# --- 차트/기간 ---
st.sidebar.divider()
chart_type = st.sidebar.radio("차트 종류", ["선 차트 (Line)", "캔들 차트 (Candle)"],
                              index=0, horizontal=True)
fixed_label = st.sidebar.radio("보유 기간", list(PERIOD_DAYS.keys()), index=0, horizontal=True)

benchmark_choice = st.sidebar.selectbox("벤치마크 비교", list(BENCHMARK_OPTIONS.keys()), index=0)
benchmark_code = BENCHMARK_OPTIONS[benchmark_choice]

# --- 세금 조건 ---
st.sidebar.divider()
st.sidebar.markdown("**💸 세금·건강보험 조건 (연간)**")

fin_map = {"없음": 0, "1천만": 10_000_000, "2천만": 20_000_000,
           "3천만": 30_000_000, "5천만": 50_000_000, "1억": 100_000_000}
other_fin_income = fin_map[st.sidebar.select_slider(
    "기타 금융소득 (이자·배당)", options=list(fin_map.keys()), value="없음")]

gross_salary = st.sidebar.number_input(
    "총급여액 (근로소득, 연)", value=0, step=1_000_000, format="%d",
    help="세전 연봉(비과세 제외). 근로소득공제를 자동 적용해 소득금액으로 환산한 뒤 세율 구간 판정에 반영합니다. "
         "재직 중이 아니면 0으로 두세요.")
salary_income_amount = max(0.0, gross_salary - earned_income_deduction(gross_salary))
if gross_salary > 0:
    st.sidebar.caption(f"→ 근로소득공제 {earned_income_deduction(gross_salary):,.0f}원 적용, "
                       f"근로소득금액 {salary_income_amount:,.0f}원")

auto_insurance = st.sidebar.checkbox(
    "건강보험 가입 유형 자동 판정", value=True,
    help="근로소득이 있으면 직장가입자(회사가 자동 가입), 없으면(자영업·프리랜서·퇴사 등) "
         "지역가입자로 자동 설정합니다. 주 15시간 미만 단시간 근로 등 예외가 있다면 체크 해제 후 직접 선택하세요.")
if auto_insurance:
    insurance_type = "직장가입자" if gross_salary > 0 else "지역가입자"
    st.sidebar.caption(f"→ **{insurance_type}**로 자동 설정됨")
else:
    insurance_type = st.sidebar.radio("건강보험 가입 유형", ["지역가입자", "직장가입자"],
                                      index=0, horizontal=True)

other_business_income = st.sidebar.number_input(
    "기타 종합소득금액 (사업소득 등)", value=0, step=1_000_000, format="%d",
    help="근로소득을 제외한 사업소득 등의 소득금액(필요경비 차감 후) 합계.")

other_comp_income = salary_income_amount + other_business_income

income_deduction = st.sidebar.number_input(
    "소득공제 합계", value=1_500_000, step=500_000, format="%d",
    help="인적공제·연금보험료공제 등의 합계. 기본값은 1인 기본공제(150만원).")

gain_taxable_ratio = st.sidebar.slider(
    "매매차익 과표 반영률 (%)", 0, 100, 100, step=5,
    help="기타형 ETF는 실제 매매차익과 과표기준가 증가분 중 작은 값에 과세됩니다. "
         "국내주식형은 이 값과 무관하게 비과세입니다.") / 100


# =========================================================
# 메인
# =========================================================

st.title("🏦 ETF 분배금·세금 시뮬레이터")
st.caption("과거 주가 데이터 기반으로 매매차익·분배금·세금·건강보험료를 함께 정산합니다.")

df_all = get_price_history(ticker)
if df_all.empty:
    st.error("가격 데이터를 불러오지 못했습니다. 다른 종목을 선택해 주세요.")
    st.stop()

earliest, latest = df_all.index.min().date(), df_all.index.max().date()

dur = PERIOD_DAYS[fixed_label]
max_start = max(earliest, latest - timedelta(days=dur))
if max_start <= earliest:
    st.warning(f"상장 기간이 {fixed_label}보다 짧아 전체 구간을 사용합니다.")
    start_date, end_date = earliest, latest
else:
    start_date = st.slider(f"📅 {fixed_label} 기간 이동 (전체 구간: {earliest} ~ {latest})",
                           min_value=earliest, max_value=max_start, value=max_start,
                           format="YYYY-MM-DD")
    end_date = min(start_date + timedelta(days=dur), latest)

    dc1, dc2 = st.columns(2)
    start_date = dc1.date_input("매수일 직접 입력", value=start_date,
                                min_value=earliest, max_value=latest)
    end_date = dc2.date_input("매도일 직접 입력", value=end_date,
                              min_value=earliest, max_value=latest)

if start_date >= end_date:
    st.error("매도일은 매수일보다 뒤여야 합니다.")
    st.stop()

holding_days = (end_date - start_date).days
holding_years = holding_days / 365.0

badge = "🇰🇷 국내주식형 · 매매차익 비과세" if is_domestic_equity else "🌏 기타형 · 매매차익 배당소득 과세"
price_badge = "수정주가(분배금 포함)" if is_adjusted_price else "원주가"
st.info(f"📍 **{start_date} ~ {end_date}** · {holding_days:,}일 (약 {holding_years:.1f}년) 　|　 {badge} 　|　 {price_badge}")

# --- 차트 ---
dfr = df_all.reset_index()
date_col = "Date" if "Date" in dfr.columns else dfr.columns[0]

if chart_type == "선 차트 (Line)":
    fig = px.line(dfr, x=date_col, y="Close", labels={"Close": "종가", date_col: "날짜"})
    fig.update_traces(hovertemplate="날짜: %{x|%Y-%m-%d}<br>종가: %{y:,.0f}원<extra></extra>")
else:
    hover_text = [f"시가: {o:,.0f}원<br>고가: {h:,.0f}원<br>저가: {l:,.0f}원<br>종가: {c:,.0f}원"
                  for o, h, l, c in zip(dfr["Open"], dfr["High"], dfr["Low"], dfr["Close"])]
    fig = go.Figure(go.Candlestick(
        x=dfr[date_col], open=dfr["Open"], high=dfr["High"],
        low=dfr["Low"], close=dfr["Close"],
        increasing_line_color="red", decreasing_line_color="blue",
        text=hover_text, hoverinfo="text"))

fig.add_vrect(x0=pd.Timestamp(start_date), x1=pd.Timestamp(end_date),
              fillcolor="blue", opacity=0.15, layer="below", line_width=0)
fig.update_layout(xaxis=dict(range=[earliest, latest], tickformat="%Y-%m-%d"),
                  yaxis=dict(tickformat=",d"), xaxis_rangeslider_visible=False,
                  dragmode="pan", margin=dict(t=20, b=20), height=320,
                  font=dict(size=11))
st.plotly_chart(fig, use_container_width=True,
                config={"scrollZoom": True, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})

# --- 매매 결과 (시뮬레이션 실행) ---
mask = (df_all.index >= pd.Timestamp(start_date)) & (df_all.index <= pd.Timestamp(end_date))
df = df_all.loc[mask]
if df.empty:
    st.error("선택한 기간에 거래 데이터가 없습니다.")
    st.stop()

sim = run_simulation(df, invest_mode, lumpsum_amount, monthly_amount,
                     is_adjusted_price, div_rate, monthly_dps, reinvest_dividends)

buy_price = float(df.iloc[0]["Close"])
sell_price = sim["sell_price"]
quantity = sim["quantity"]
if quantity == 0:
    st.error("투자금이 1주 가격보다 적어 매수할 수 없습니다.")
    st.stop()

total_cash_contributed = sim["total_cash_contributed"]
total_eval = sim["total_eval"]
capital_gain = sim["capital_gain"]
total_dividend = sim["total_dividend_gross"]
mdd = sim["mdd"]

st.subheader(f"📌 {selected_label} 시뮬레이션 결과")
badge_line = invest_mode_label + (" · 🔁 분배금 재투자" if reinvest_dividends else "")
st.caption(badge_line)

gain_pct = (total_eval - total_cash_contributed) / total_cash_contributed * 100 if total_cash_contributed else 0.0

c = st.columns(6)
c[0].metric("최종 보유 주식 수", f"{quantity:,.0f} 주")
c[1].metric("매수 주가 (최초)", f"{buy_price:,.0f} 원")
c[2].metric("매도 주가", f"{sell_price:,.0f} 원",
            delta=f"{(sell_price - buy_price) / buy_price * 100:.2f}%")
c[3].metric("누적 투자원금", f"{total_cash_contributed:,.0f} 원")
c[4].metric("최종 평가금액", f"{total_eval:,.0f} 원",
            delta=f"{total_eval - total_cash_contributed:,.0f} 원 ({gain_pct:.2f}%)")
c[5].metric("최대낙폭 (MDD)", f"-{mdd * 100:.2f}%",
            help="보유 기간 중 평가금액 고점 대비 최대 하락폭입니다. 적립식 매수·분배금 재투자도 반영됩니다.")

# --- 연도별 분배금 (월 단위 시뮬레이션 결과 집계) ---
records_df = pd.DataFrame(sim["monthly_records"])
yearly = []
if not records_df.empty:
    for year, g in records_df.groupby("연도"):
        yearly.append({
            "연도": int(year),
            "보유일수": int(g["보유일수"].sum()),
            "평균주가": float(g["주가"].mean()),
            "분배금(세전)": float(g["분배금(세전)"].sum()),
        })

# --- 과세 대상액 ---
taxable_gain = 0.0 if is_domestic_equity else max(0.0, capital_gain) * gain_taxable_ratio

# --- 연도별 세금·건보료 (한계 부담분) ---
sell_year = end_date.year
total_tax = total_nhis = total_taxable_div = 0.0

base_tax = income_tax_total(other_fin_income, other_comp_income, income_deduction)
base_nhis = health_insurance_annual(other_fin_income, other_comp_income, insurance_type)

for y in yearly:
    taxable_div = y["분배금(세전)"] * div_taxable_ratio
    etf_fin = taxable_div + (taxable_gain if y["연도"] == sell_year else 0.0)

    y["과세대상 분배금"] = taxable_div
    y["ETF 금융소득"] = etf_fin
    y["소득세(지방세 포함)"] = income_tax_total(
        other_fin_income + etf_fin, other_comp_income, income_deduction) - base_tax
    y["건강보험료"] = health_insurance_annual(
        other_fin_income + etf_fin, other_comp_income, insurance_type) - base_nhis
    y["종합과세"] = (other_fin_income + etf_fin) > FIN_INCOME_THRESHOLD

    total_taxable_div += taxable_div
    total_tax += y["소득세(지방세 포함)"]
    total_nhis += y["건강보험료"]

st.divider()
st.subheader("⚖️ 세금 및 건강보험료")

if is_adjusted_price:
    st.warning("📊 **수정주가 모드**: 분배금이 매매차익에 이미 반영된 것으로 보아 별도 가산하지 않습니다. "
               "다만 실제로는 분배 시점마다 배당소득세가 원천징수되므로, 세금은 별도 확인이 필요합니다.")

m = st.columns(4)
m[0].metric("분배금 (세전)", f"{total_dividend:,.0f} 원")
m[1].metric("과세대상 분배금", f"{total_taxable_div:,.0f} 원",
            help="분배금 × 과표 반영률. 커버드콜 ETF는 과표증분이 작아 대부분 비과세될 수 있습니다.")
m[2].metric("매매차익 과세대상", f"{taxable_gain:,.0f} 원",
            help="국내주식형 ETF는 매매차익 비과세이므로 0원입니다.")
m[3].metric("세금 + 건보료", f"-{total_tax + total_nhis:,.0f} 원")

detail = pd.DataFrame(yearly)
detail["과세방식"] = detail["종합과세"].map({True: "종합과세", False: "분리과세 15.4%"})
st.dataframe(
    detail[["연도", "보유일수", "평균주가", "분배금(세전)", "과세대상 분배금",
            "ETF 금융소득", "과세방식", "소득세(지방세 포함)", "건강보험료"]].style.format({
        "평균주가": "{:,.0f}", "분배금(세전)": "{:,.0f}", "과세대상 분배금": "{:,.0f}",
        "ETF 금융소득": "{:,.0f}", "소득세(지방세 포함)": "{:,.0f}", "건강보험료": "{:,.0f}"}),
    use_container_width=True, hide_index=True)

if detail["종합과세"].any():
    st.warning("⚠️ 일부 연도가 **금융소득종합과세 대상**입니다. 종합과세·분리과세 중 큰 금액(비교과세)을 적용했습니다.")
else:
    st.success("✅ 전 기간 분리과세(15.4%) 구간입니다.")

if div_taxable_ratio < 1.0 and total_dividend > 0:
    saved = (total_dividend - total_taxable_div)
    st.info(f"💡 과표 반영률 {div_taxable_ratio * 100:.0f}% 적용으로 **{saved:,.0f}원**이 과세 대상에서 제외되었습니다. "
            "실제 과표증분은 운용사 분배금 공지에서 매월 확인하세요.")

# --- 최종 요약 ---
st.divider()
st.subheader("💰 최종 총수익 (세후)")

net_profit = capital_gain + total_dividend - total_tax - total_nhis
cagr = ((total_cash_contributed + net_profit) / total_cash_contributed) ** (1 / holding_years) - 1 \
    if holding_years > 0 and total_cash_contributed > 0 else 0

s = st.columns(5)
s[0].metric("매매차익", f"{capital_gain:,.0f} 원",
            help="가격 상승분만 반영한 순수 매매차익입니다. 재투자된 분배금 원금은 제외됩니다.")
s[1].metric("분배금 (세전)", f"{total_dividend:,.0f} 원")
s[2].metric("세금·건보료", f"-{total_tax + total_nhis:,.0f} 원")
s[3].metric("최종 총수익 (세후)", f"{net_profit:,.0f} 원",
            delta=f"{net_profit / total_cash_contributed * 100:.2f}%" if total_cash_contributed else None)
s[4].metric("세후 CAGR", f"{cagr * 100:.2f}%",
            help="적립식의 경우 현금흐름 가중 수익률(IRR)이 아닌 근사 연환산 수익률입니다.")

# --- 벤치마크 비교 ---
if benchmark_code:
    st.divider()
    st.subheader("📊 벤치마크 비교")
    bench_df_all = get_price_history(benchmark_code)
    bench_mask = (bench_df_all.index >= pd.Timestamp(start_date)) & (bench_df_all.index <= pd.Timestamp(end_date))
    bench_df = bench_df_all.loc[bench_mask]
    if bench_df.empty:
        st.warning("벤치마크 데이터를 불러오지 못했습니다.")
    else:
        etf_norm = df["Close"] / df["Close"].iloc[0] * 100
        bench_norm = bench_df["Close"] / bench_df["Close"].iloc[0] * 100
        cmp_df = pd.DataFrame({selected_label: etf_norm, benchmark_choice: bench_norm})
        cmp_df.index.name = "날짜"
        cmp_long = cmp_df.reset_index().melt(id_vars="날짜", var_name="구분", value_name="지수 (시작=100)")
        fig_cmp = px.line(cmp_long, x="날짜", y="지수 (시작=100)", color="구분")
        fig_cmp.update_layout(margin=dict(t=20, b=20), height=280, font=dict(size=11))
        st.plotly_chart(fig_cmp, use_container_width=True)

        etf_price_return = (float(df["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1) * 100
        bench_return = (float(bench_df["Close"].iloc[-1]) / float(bench_df["Close"].iloc[0]) - 1) * 100
        bc = st.columns(2)
        bc[0].metric(f"{selected_label} 가격 수익률", f"{etf_price_return:.2f}%",
                    help="세금·분배금 재투자를 제외한 순수 가격 등락률입니다.")
        bc[1].metric(f"{benchmark_choice} 가격 수익률", f"{bench_return:.2f}%",
                    delta=f"{etf_price_return - bench_return:+.2f}%p (ETF 기준 초과분)")

with st.expander("📖 계산 기준 및 한계"):
    st.markdown("""
**적용 기준 (2026년)**
- 종합소득세: 8단계 누진세율(6%~45%), 산출세액 = 과세표준 × 세율 − 누진공제
- 금융소득종합과세: 연 2,000만원 초과 시 비교과세(종합과세 vs 전액 14% 중 큰 금액)
- 지방소득세: 소득세의 10%
- 건강보험료율 7.19%, 장기요양보험료율 0.9448%
- 지역가입자: 금융소득 1,000만원 초과 시 **전액** 소득 반영
- 직장가입자: 보수외소득 2,000만원 **초과분**에 소득월액보험료 부과

**과표증분 과세**
국내상장 ETF의 분배금과 매매차익은 실제 금액이 아니라 **'과세표준 기준가격 증가분'과 실제 금액 중 작은 값**에 15.4%가 과세됩니다.
커버드콜 ETF의 옵션 프리미엄은 과표에 반영되지 않는 경우가 많아, 분배금을 많이 받아도 세금이 거의 없을 수 있습니다.
정확한 값은 운용사(KODEX/TIGER/ACE 등) 홈페이지의 월별 분배금 공지에서 **'주당 과세표준액'**을 확인해 사이드바에 입력하세요.

**적립식 · 재투자 · MDD 시뮬레이션**
- 매수(적립식)·분배·재투자는 실제 지급일이 아니라 **매월 말 영업일**에 일괄 발생한다고 근사합니다.
- 재투자·적립식 매수는 소수점 주식을 지원하지 않는 국내 ETF 특성을 반영해 **정수 주 단위**로만 매수하고, 남는 금액은 다음 달로 이월됩니다.
- MDD(최대낙폭)는 일별 종가 기준 평가금액(보유 주식 수 × 종가)의 고점 대비 최대 하락폭입니다.
- 적립식의 CAGR은 투자 시점이 분산되어 있어 실제 IRR(현금흐름 가중 수익률)과 다를 수 있는 근사치입니다.
- 벤치마크 비교는 가격 등락률만 비교하며 세금·분배금·수수료는 반영하지 않습니다.

**한계**
- 분배금은 실제 지급 내역이 아니라 입력한 분배율 또는 월 주당 분배금으로 추정합니다.
- 과표 반영률은 기간 내내 고정값으로 적용됩니다. 실제로는 매월 달라집니다.
- 건강보험료는 소득분만 계산하며 재산·자동차분, 지역가입자 최저보험료는 미반영입니다.
- 세액은 한계 부담분(ETF 소득이 있을 때 − 없을 때)입니다.
- 매매 수수료·증권거래세·운용보수(TER)는 반영되지 않았습니다.
- ISA·연금계좌 등 절세계좌를 통한 투자는 별도 계산이 필요합니다.

실제 신고 전에는 반드시 홈택스·건강보험공단 모의계산 또는 세무 전문가를 통해 확인하시기 바랍니다.
""")
