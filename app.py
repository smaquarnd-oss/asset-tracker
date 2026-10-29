# -*- coding: utf-8 -*-
"""
================================================================================
실시간 자산 관제 시스템 (v12.0 - 글래스 디자인 / 월말 추이 / 소유주 자동 인식)
================================================================================
CSV 형식 (헤더 1줄 + 보유 종목 1줄씩):
    날짜,소유주명,계좌ID,평가금액,매수금액,평가손익,수량,평균단가,종목,종목코드,통화

규칙
- 어떤 계좌를 갱신할 때는 그 날짜에 해당 계좌의 '모든 보유 종목'을 적는다.
  (앱은 계좌별로 가장 최근 날짜의 행들만 현재 보유분으로 본다. 매도한 종목은 빼면 된다.)
- 통화: 금액이 달러면 USD, 원화면 KRW (비워두면 KRW. 기존 데이터는 자동 추정).
- 종목코드: 국내는 6자리(앞자리 0 포함), 해외는 티커(SOXL 등). 있으면 실시간 시세 반영.
"""

import io
import json
import re
import datetime
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="자산 관제",
    page_icon="💰",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# =============================================================================
# 폰트 / 모바일 CSS
#  - 한글: Noto Sans KR 웹폰트 → 서버(리눅스) 폰트 유무와 상관없이 브라우저가 그림
#  - 아이콘: Streamlit 아이콘(Material Symbols) 폰트를 직접 로드하고 덮어쓰지 않도록 보호
#    (폰트 로드 실패 시 'keyboard_arrow_right' 같은 글자가 보이는 문제 방지)
# =============================================================================
FONT_STACK = "'Noto Sans KR', 'Malgun Gothic', 'Apple SD Gothic Neo', 'Nanum Gothic', sans-serif"

st.html(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=block');
:root {
    --glass-bg: rgba(255, 255, 255, 0.08);
    --glass-border: rgba(255, 255, 255, 0.16);
    --ink: #f4f5ff;
    --ink-2: rgba(244, 245, 255, 0.68);
    --up: #ff8fa3;
    --down: #7cc4ff;
}
html, body, .stApp, .stMarkdown, .stCaption, p, h1, h2, h3, h4, label, input, button, textarea {
    font-family: 'Noto Sans KR', 'Malgun Gothic', 'Apple SD Gothic Neo', 'Nanum Gothic', sans-serif;
}
[data-testid="stIconMaterial"], .material-symbols-rounded {
    font-family: 'Material Symbols Rounded' !important;
}
[data-testid="stFileUploaderDropzone"] [data-testid="stIconMaterial"] { display: none; }

/* 배경: 짙은 그라데이션 + 은은한 색 번짐 (blur 필터 없이 radial-gradient로 → 모바일에서도 가벼움) */
.stApp {
    background: linear-gradient(160deg, #161a42 0%, #261a4a 45%, #0e2643 100%) !important;
    color: var(--ink);
}
.stApp::before {
    content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
    background:
        radial-gradient(420px circle at 88% 6%, rgba(124, 92, 255, 0.40), transparent 70%),
        radial-gradient(380px circle at 0% 45%, rgba(0, 184, 212, 0.28), transparent 70%),
        radial-gradient(360px circle at 100% 95%, rgba(232, 67, 147, 0.28), transparent 70%);
}
[data-testid="stHeader"] { background: transparent !important; }
[data-testid="stToolbar"] { opacity: 0.6; }

/* 유리 카드: key가 glass 로 시작하는 st.container + HTML 카드 */
[class*="st-key-glass"], .glass {
    background: var(--glass-bg) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: 18px !important;
    backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
}
[class*="st-key-glass"] { padding: 14px 14px 6px !important; }
[class*="st-key-glass"] h4 { font-size: 1rem !important; margin: 0 0 2px !important; padding: 0 !important; }

/* 모바일 여백/글자 크기 */
.block-container { padding-top: 2.2rem; padding-bottom: 3rem; position: relative; z-index: 1; }
@media (max-width: 640px) {
    .block-container { padding-left: 0.9rem; padding-right: 0.9rem; }
}

/* 상단 제목 */
.app-head .t { font-size: 1.45rem; font-weight: 700; letter-spacing: -0.3px; line-height: 1.3; }
.app-head .s { font-size: 0.8rem; color: var(--ink-2); margin-top: 2px; }

/* 요약 카드 */
.kpi-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin: 6px 0 8px; }
.kpi { padding: 13px 14px; min-width: 0; }
.kpi.wide { grid-column: 1 / -1; padding: 16px; }
.kpi .lbl { font-size: 0.78rem; color: var(--ink-2); margin-bottom: 2px; }
.kpi .val { font-size: 1.2rem; font-weight: 700; line-height: 1.3; word-break: keep-all; overflow-wrap: anywhere; }
.kpi.wide .val { font-size: 1.85rem; letter-spacing: -0.5px; }
.kpi .sub { font-size: 0.8rem; margin-top: 3px; color: var(--ink-2); }
.up { color: var(--up) !important; }
.down { color: var(--down) !important; }
@media (max-width: 380px) {
    .kpi .val { font-size: 1.02rem; }
    .kpi.wide .val { font-size: 1.5rem; }
}

/* 종목 리스트 */
.items .it { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 9px 0; font-size: 0.88rem; }
.items .it + .it { border-top: 1px solid rgba(255, 255, 255, 0.10); }
.items .nm { display: flex; align-items: center; gap: 8px; min-width: 0; }
.items .nm span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.items .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.items .v { white-space: nowrap; text-align: right; }
.items .v small { display: block; font-size: 0.72rem; color: var(--ink-2); }
.pill { font-size: 0.7rem; padding: 2px 8px; border-radius: 99px; background: rgba(255, 255, 255, 0.14); margin-left: 6px; }

/* 구분선/캡션 */
hr { border-color: rgba(255, 255, 255, 0.12) !important; }
[data-testid="stCaptionContainer"] { color: var(--ink-2) !important; }

/* 제목 줄: 모바일에서도 제목과 잠금 버튼을 한 줄에 */
.st-key-headrow [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 8px; }
.st-key-headrow [data-testid="stColumn"] { min-width: 0 !important; width: auto !important; }
.st-key-headrow [data-testid="stColumn"]:last-child { flex: 0 0 72px !important; }
.st-key-headrow [data-testid="stColumn"]:first-child { flex: 1 1 auto !important; }
</style>
"""
)

# 계좌 유형별 색 (검증된 범주형 팔레트 1~5번, 고정 순서)
ACC_ORDER = ["ISA", "PSA", "IRP", "CA", "CMA"]
ACC_COLORS = {"ISA": "#60a5fa", "PSA": "#34d399", "IRP": "#c084fc", "CA": "#fbbf24", "CMA": "#f472b6"}  # 색약 구분 검사 통과 순서
BAR_ALPHA = 0.55  # 반투명 유리 막대 채우기 진하기 (테두리는 원색)


def glass_fill(hex_color, alpha=BAR_ALPHA):
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"

ACC_LABELS = {"ISA": "ISA", "PSA": "연금저축(PSA)", "IRP": "IRP", "CA": "일반(CA)", "CMA": "현금(CMA)"}

STD_COLS = ["날짜", "소유주명", "계좌ID", "평가금액", "매수금액", "평가손익", "수량", "평균단가", "종목", "종목코드", "통화"]
NUM_COLS = ["평가금액", "매수금액", "평가손익", "수량", "평균단가"]

PLOTLY_CONFIG = {"displayModeBar": False, "scrollZoom": False, "responsive": True}
ITEM_COLOR = "#8c7cff"


# =============================================================================
# 시세 조회
# =============================================================================
def _fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


@st.cache_data(ttl=600, show_spinner=False)
def get_usd_krw_rate():
    try:
        data = _fetch_json("https://query1.finance.yahoo.com/v8/finance/chart/KRW=X")
        return float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception:
        return 1400.0


def _kr_price(code):
    try:
        data = _fetch_json(f"https://m.stock.naver.com/api/stock/{code}/basic")
        return float(str(data["closePrice"]).replace(",", ""))
    except Exception:
        return None


def _us_price(ticker):
    try:
        data = _fetch_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}")
        return float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def get_live_prices(kr_codes, us_codes):
    """종목코드 → 현재가. 병렬 조회 + 10분 캐시."""
    jobs = [(c, _kr_price) for c in kr_codes] + [(t, _us_price) for t in us_codes]
    if not jobs:
        return {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda j: (j[0], j[1](j[0])), jobs))
    return {k: v for k, v in results if v is not None}


# --- 과거 시세 (월말 추정용) ---
def _kr_history(code, start, end):
    """네이버 일별 시세 → {날짜: 종가}"""
    url = (
        "https://api.finance.naver.com/siseJson.naver?symbol={}&requestType=1"
        "&startTime={}&endTime={}&timeframe=day"
    ).format(code, start.replace("-", ""), end.replace("-", ""))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
        rows = re.findall(r'\["(\d{8})",\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)', text)
        return {pd.Timestamp(r[0]): float(r[4]) for r in rows}
    except Exception:
        return {}


def _yahoo_history(symbol, start, end):
    """야후 일별 시세(해외 종목, 환율 KRW=X) → {날짜: 종가}"""
    p1 = int(pd.Timestamp(start).timestamp())
    p2 = int(pd.Timestamp(end).timestamp()) + 86400
    try:
        data = _fetch_json(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={p1}&period2={p2}&interval=1d"
        )
        r = data["chart"]["result"][0]
        closes = r["indicators"]["quote"][0]["close"]
        return {
            pd.Timestamp(t, unit="s").normalize(): float(c)
            for t, c in zip(r["timestamp"], closes) if c is not None
        }
    except Exception:
        return {}


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def get_price_history(kr_codes, us_codes, start, end):
    """{종목코드: {날짜: 종가}}. 환율은 'KRW=X' 키. 실패한 종목은 빠짐."""
    jobs = [(c, _kr_history) for c in kr_codes] + [(t, _yahoo_history) for t in (*us_codes, "KRW=X")]
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda j: (j[0], j[1](j[0], start, end)), jobs))
    return {k: v for k, v in results if v}


def price_on(hist, date, max_gap_days=10):
    """date 이전 가장 가까운 거래일 종가 (주말/휴일 대응)."""
    if not hist:
        return None
    cands = [d for d in hist if date - pd.Timedelta(days=max_gap_days) <= d <= date]
    return hist[max(cands)] if cands else None


# =============================================================================
# CSV 읽기 / 정리
# =============================================================================
def decode_bytes(raw):
    """엑셀 CSV(CP949)와 UTF-8(BOM 포함)을 모두 지원."""
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(손상 문자 대체)"


def map_columns(df_in):
    col_map = {}
    for c in df_in.columns:
        name = str(c).strip().replace("﻿", "")
        low = name.lower()
        if name in STD_COLS:
            col_map[c] = name
        elif "소유" in name or name == "이름":
            col_map[c] = "소유주명"
        elif "계좌" in name and ("id" in low or "코드" in name or "번호" in name):
            col_map[c] = "계좌ID"
        elif "계좌" in name or "구분" in name:
            col_map[c] = "계좌종류"
        elif "손익" in name:
            col_map[c] = "평가손익"
        elif "평가" in name:
            col_map[c] = "평가금액"
        elif "단가" in name:
            col_map[c] = "평균단가"
        elif "매수" in name or "원금" in name or "투자금" in name:
            col_map[c] = "매수금액"
        elif "수량" in name or "주수" in name:
            col_map[c] = "수량"
        elif "코드" in name or "티커" in name or "ticker" in low:
            col_map[c] = "종목코드"
        elif "종목" in name:
            col_map[c] = "종목"
        elif "통화" in name or "currency" in low:
            col_map[c] = "통화"
        elif "날짜" in name or "일자" in name or "기준일" in name:
            col_map[c] = "날짜"
        else:
            col_map[c] = name
    return df_in.rename(columns=col_map)


def to_number(s):
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False).str.replace("원", "", regex=False).str.strip(),
        errors="coerce",
    )


def normalize_code(v):
    if v is None or pd.isna(v):
        return ""
    s = str(v).strip().upper()
    if s in ("", "NAN", "NONE"):
        return ""
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    if s.isdigit() and len(s) <= 6:
        s = s.zfill(6)
    return s


def code_market(code):
    if re.fullmatch(r"[0-9][0-9A-Z]{5}", code):
        return "KR"
    if re.fullmatch(r"[A-Z]{1,5}", code):
        return "US"
    return ""


def account_type(acc_id, acc_kind=""):
    s = f"{acc_id} {acc_kind}".upper()
    if "ISA" in s:
        return "ISA"
    if "IRP" in s or "퇴직" in s:
        return "IRP"
    if "PSA" in s or "연금" in s:
        return "PSA"
    if "CMA" in s or "현금" in s or "네이버" in s:
        return "CMA"
    return "CA"


def prepare_data(df_raw):
    """원본 CSV → 분석용 표. (정리된 표, 안내 메시지 목록) 반환."""
    notes = []
    df = map_columns(df_raw.copy())
    df = df.loc[:, ~df.columns.duplicated()]

    for c in STD_COLS:
        if c not in df.columns:
            df[c] = None
    df = df.replace({"": None})

    # 예전 행 보정: 종목명이 '수량' 칸에 들어가고 종목 칸이 빈 경우 (열 밀림)
    qty_num = to_number(df["수량"])
    shifted = df["수량"].notna() & qty_num.isna() & df["종목"].isna()
    if shifted.any():
        df.loc[shifted, "종목"] = df.loc[shifted, "수량"]
        df.loc[shifted, "수량"] = None
        notes.append(f"종목명이 '수량' 칸에 들어간 {int(shifted.sum())}개 행을 자동 보정했습니다.")

    for c in NUM_COLS:
        df[c] = to_number(df[c])

    df["날짜_dt"] = pd.to_datetime(
        df["날짜"].astype(str).str.strip().str.replace(r"[./]", "-", regex=True), errors="coerce"
    )
    bad_date = df["날짜_dt"].isna()
    if bad_date.any():
        notes.append(f"날짜를 읽을 수 없는 {int(bad_date.sum())}개 행은 제외했습니다.")
        df = df[~bad_date].copy()

    df["소유주명"] = df["소유주명"].fillna("공동").astype(str).str.strip()
    if df["계좌ID"].isna().all():
        kind = df["계좌종류"] if "계좌종류" in df.columns else "계좌"
        df["계좌ID"] = df["소유주명"] + "_" + pd.Series(kind, index=df.index).astype(str)
    df["계좌ID"] = df["계좌ID"].fillna("미지정").astype(str).str.strip()
    df["종목"] = df["종목"].astype(object).where(df["종목"].notna(), df["계좌ID"] + " (합계)").astype(str).str.strip()
    df["종목코드"] = df["종목코드"].map(normalize_code)
    df["시장"] = df["종목코드"].map(code_market)

    kind_col = df["계좌종류"] if "계좌종류" in df.columns else pd.Series("", index=df.index)
    df["계좌유형"] = [account_type(a, k if pd.notna(k) else "") for a, k in zip(df["계좌ID"], kind_col)]

    # 통화: 지정값 우선, 없으면 '해외 종목이고 매수금액 ≈ 수량×평균단가(달러)'일 때 USD로 추정
    cur = df["통화"].astype(str).str.upper().str.strip()
    looks_usd = (
        (df["시장"] == "US")
        & (df["수량"] > 0)
        & (df["평균단가"] > 0)
        & (df["매수금액"] > 0)
        & ((df["매수금액"] - df["수량"] * df["평균단가"]).abs() <= df["매수금액"] * 0.05)
    )
    df["통화"] = cur.where(cur.isin(["KRW", "USD"]), None)
    guessed = df["통화"].isna() & looks_usd
    if guessed.any():
        notes.append(f"달러 금액으로 보이는 {int(guessed.sum())}개 행을 USD로 처리했습니다 (현재 환율 적용).")
    df.loc[guessed, "통화"] = "USD"
    df["통화"] = df["통화"].fillna("KRW")

    return df, notes


# =============================================================================
# 시점별 스냅샷: 계좌마다 '기준일 이전 가장 최근 날짜'의 행 전체 = 그 계좌 보유분
# =============================================================================
def snapshot(df, as_of, usd_krw, live_prices=None):
    d = df[df["날짜_dt"] <= as_of]
    if d.empty:
        return None
    last = d.groupby("계좌ID")["날짜_dt"].transform("max")
    snap = d[d["날짜_dt"] == last].copy()

    fx = snap["통화"].eq("USD").map({True: usd_krw, False: 1.0})
    snap["평가_원"] = snap["평가금액"].fillna(0) * fx
    snap["매수_원"] = snap["매수금액"].fillna(0) * fx
    # 현금(CMA)은 원금 칸이 비어 있거나 0이면 평가금액 = 원금 (현금이 수익으로 잡히지 않도록)
    cash_no_cost = snap["계좌유형"].eq("CMA") & snap["매수_원"].le(0)
    snap.loc[cash_no_cost, "매수_원"] = snap.loc[cash_no_cost, "평가_원"]
    snap["시세반영"] = False

    if live_prices:
        for i, row in snap.iterrows():
            code, qty = row["종목코드"], row["수량"]
            if code in live_prices and pd.notna(qty) and qty > 0:
                px_ = live_prices[code] * (usd_krw if row["시장"] == "US" else 1.0)
                snap.at[i, "평가_원"] = qty * px_
                snap.at[i, "시세반영"] = True

    snap["손익_원"] = snap["평가_원"] - snap["매수_원"]
    return snap


def map_underlying_asset(item_name):
    raw = str(item_name)
    n = raw.upper().replace(" ", "")
    if "TQQQ" in n:
        return "TQQQ (나스닥 3배)"
    if "SOXL" in n:
        return "SOXL (반도체 3배)"
    if "나스닥100" in n or "NASDAQ100" in n or "QQQ" in n:
        return "나스닥100 미국채혼합" if ("미국채" in n or "혼합" in n) else "미국 나스닥100"
    if any(k in n for k in ["S&P500", "SPYM", "VOO", "SPLG", "IVV"]):
        return "미국 S&P500"
    if any(k in n for k in ["미국반도체", "SOXX", "SMH"]):
        return "미국 반도체"
    if any(k in n for k in ["빅테크TOP7", "MAG7"]):
        return "미국 빅테크TOP7"
    if "테크TOP10" in n:
        return "미국 테크TOP10"
    if "AI반도체" in n:
        return "KODEX AI반도체"
    if "하이닉스" in n:
        return "SK하이닉스 레버리지"
    if "레버리지" in n:
        return "코스피200 레버리지"
    if "KODEX200" in n:
        return "KODEX 200"
    if "TDF" in n:
        return "TDF 2060"
    if "네이버페이" in n or "CMA" in n or "현금" in n:
        return "현금 / CMA"
    return raw


# =============================================================================
# 표시 도우미
# =============================================================================
def fmt_won(v):
    """원 단위 → '1억 2,345만' 형식."""
    sign = "-" if v < 0 else ""
    v = abs(v)
    eok, man = int(v // 1e8), int(round((v % 1e8) / 1e4))
    if man == 10000:
        eok, man = eok + 1, 0
    if eok:
        return f"{sign}{eok}억 {man:,}만" if man else f"{sign}{eok}억"
    return f"{sign}{man:,}만"


def signed(v, pct=None):
    cls = "up" if v > 0 else ("down" if v < 0 else "")
    arrow = "▲" if v > 0 else ("▼" if v < 0 else "")
    txt = f"{arrow} {fmt_won(abs(v))}원" if v else "변동 없음"
    if pct is not None:
        txt += f" ({pct:+.2f}%)"
    return f'<span class="{cls}">{txt}</span>'


def kpi_cards(cards):
    html = '<div class="kpi-grid">'
    for c in cards:
        cls = "kpi wide" if c.get("wide") else "kpi"
        sub = f'<div class="sub">{c["sub"]}</div>' if c.get("sub") else ""
        html += f'<div class="{cls} glass"><div class="lbl">{c["label"]}</div><div class="val">{c["value"]}</div>{sub}</div>'
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def style_fig(fig, height):
    fig.update_layout(
        font=dict(family=FONT_STACK, size=12, color="rgba(244,245,255,0.85)"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=height,
        margin=dict(l=52, r=10, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0, title_text=""),
        dragmode=False,
        hoverlabel=dict(font_family=FONT_STACK, bgcolor="rgba(22,24,60,0.95)", bordercolor="rgba(255,255,255,0.3)", font_color="#f4f5ff"),
        bargap=0.25,
    )
    fig.update_xaxes(fixedrange=True, showgrid=False, linecolor="rgba(255,255,255,0.15)")
    fig.update_yaxes(fixedrange=True, gridcolor="rgba(255,255,255,0.10)", zeroline=False)
    return fig


def stacked_by_account(df_plot, x_col, x_order, height, label_last_only=False):
    fig = go.Figure()
    for acc in ACC_ORDER:
        part = df_plot[df_plot["계좌유형"] == acc].set_index(x_col).reindex(x_order)
        if part["평가_만원"].fillna(0).sum() == 0:
            continue
        fig.add_bar(
            x=x_order,
            y=part["평가_만원"].fillna(0),
            name=ACC_LABELS[acc],
            marker=dict(color=glass_fill(ACC_COLORS[acc]), line=dict(width=1.5, color=ACC_COLORS[acc])),
            hovertemplate="%{x}<br>" + ACC_LABELS[acc] + ": %{y:,.0f}만원<extra></extra>",
        )
    totals = df_plot.groupby(x_col)["평가_만원"].sum().reindex(x_order).fillna(0)
    # 막대가 많으면 합계 라벨이 겹치므로 마지막 막대만 표시 (나머지는 터치/호버로 확인)
    texts = [f"{v:,.0f}" if (not label_last_only or i == len(totals) - 1) else "" for i, v in enumerate(totals)]
    fig.add_scatter(
        x=x_order, y=totals, mode="text", text=texts,
        textposition="top left" if label_last_only else "top center", textfont=dict(size=11), showlegend=False, cliponaxis=False,
        hovertemplate="%{x}<br>합계: %{y:,.0f}만원<extra></extra>",
    )
    fig.update_layout(barmode="stack")
    fig.update_yaxes(range=[0, max(totals.max(), 1) * 1.15], tickformat=",.0f")
    return style_fig(fig, height)


def build_month_end_trend(df, month_ends, usd_krw):
    """
    월말마다 계좌별 평가액을 계산.
    - 그 달에 기록이 있는 계좌: 기록값 그대로 (상태 '기록')
    - 그 달 기록이 없는 계좌: 직전 기록의 수량 × 그 월말 종가로 추정 (상태 '추정')
    - 수량/종목코드가 없거나 시세 조회 실패: 직전 기록값 사용 (상태 '이월')
    """
    snaps, need_kr, need_us = [], set(), set()
    for m in month_ends:
        s = snapshot(df, m, usd_krw)
        if s is None:
            continue
        acc_last = s.groupby("계좌ID")["날짜_dt"].transform("max")
        same_month = (acc_last.dt.year == m.year) & (acc_last.dt.month == m.month)
        s["상태"] = same_month.map({True: "기록", False: "이월"})
        stale = s[(s["상태"] == "이월") & (s["수량"] > 0) & (s["시장"] != "")]
        need_kr |= set(stale.loc[stale["시장"] == "KR", "종목코드"])
        need_us |= set(stale.loc[stale["시장"] == "US", "종목코드"])
        snaps.append((m, s))
    if not snaps:
        return None

    start = (snaps[0][0] - pd.Timedelta(days=15)).strftime("%Y-%m-%d")
    end = snaps[-1][0].strftime("%Y-%m-%d")
    hist = get_price_history(tuple(sorted(need_kr)), tuple(sorted(need_us)), start, end)
    fx_hist = hist.get("KRW=X", {})

    out = []
    for m, s in snaps:
        fx_m = price_on(fx_hist, m) or usd_krw
        usd = s["통화"].eq("USD")
        s.loc[usd, "평가_원"] = s.loc[usd, "평가금액"].fillna(0) * fx_m
        for i in s.index[(s["상태"] == "이월") & (s["수량"] > 0)]:
            code = s.at[i, "종목코드"]
            p = price_on(hist.get(code), m)
            if p:
                s.at[i, "평가_원"] = s.at[i, "수량"] * p * (fx_m if s.at[i, "시장"] == "US" else 1.0)
                s.at[i, "상태"] = "추정"
        out.append(s.assign(시점=m))
    return pd.concat(out, ignore_index=True)


STATUS_OPACITY = {"기록": 1.0, "실시간": 1.0, "추정": 0.75, "이월": 0.5}


def trend_figure(trend, x_order, height):
    """월말 추이 누적 막대. 상태(기록/추정/이월)에 따라 막대 진하기를 다르게."""
    def seg_status(st_list):
        st_set = set(st_list)
        if "이월" in st_set:
            return "이월"
        if "추정" in st_set:
            return "추정"
        return "실시간" if "실시간" in st_set else "기록"

    grp = (
        trend.groupby(["라벨", "계좌유형"])
        .agg(평가=("평가_원", "sum"), 상태=("상태", seg_status), 기준일=("날짜_dt", "max"))
        .reset_index()
    )
    fig = go.Figure()
    for acc in ACC_ORDER:
        part = grp[grp["계좌유형"] == acc].set_index("라벨").reindex(x_order)
        if part["평가"].fillna(0).sum() == 0:
            continue
        status = part["상태"].fillna("기록")
        recdate = part["기준일"].dt.strftime("%y.%m.%d").fillna("-")
        fig.add_bar(
            x=x_order,
            y=part["평가"].fillna(0) / 1e4,
            name=ACC_LABELS[acc],
            marker=dict(
                color=glass_fill(ACC_COLORS[acc]),
                opacity=[STATUS_OPACITY[s] for s in status],
                line=dict(width=1.5, color=ACC_COLORS[acc]),
            ),
            customdata=list(zip(status, recdate)),
            hovertemplate="%{x} · " + ACC_LABELS[acc]
            + "<br>%{y:,.0f}만원<br>%{customdata[0]} (마지막 기록 %{customdata[1]})<extra></extra>",
        )
    totals = grp.groupby("라벨")["평가"].sum().reindex(x_order).fillna(0) / 1e4
    fig.add_scatter(
        x=x_order, y=totals, mode="text",
        text=[f"{v:,.0f}" if i == len(totals) - 1 else "" for i, v in enumerate(totals)],
        textposition="top left", textfont=dict(size=11), showlegend=False, cliponaxis=False,
        hovertemplate="%{x}<br>합계: %{y:,.0f}만원<extra></extra>",
    )
    fig.update_layout(barmode="stack")
    fig.update_yaxes(range=[0, max(totals.max(), 1) * 1.15], tickformat=",.0f")
    fig.update_xaxes(type="category", tickangle=-45, tickfont=dict(size=10), automargin=True)
    return style_fig(fig, height)


TEMPLATE_CSV = (
    "날짜,소유주명,계좌ID,평가금액,매수금액,평가손익,수량,평균단가,종목,종목코드,통화\n"
    "2026-10-29,성민,ISA_01,15213842,11940481,3273361,496,24075,ACE 미국나스닥100,367380,KRW\n"
    "2026-10-29,성민,CA_01,878.56,1196.51,-317.49,9.11989,131.19,SOXL,SOXL,USD\n"
    "2026-10-29,공동,CMA_01,6300000,6300000,0,,,네이버페이,,KRW\n"
)

SHARED_OWNERS = {"공동", "공통", "미지정", "가족"}


def owners_title(df_all, df_snap):
    """CSV 소유주명으로 제목 생성. 공동 계좌는 제외, CSV에 처음 나온 순서대로."""
    current = set(df_snap["소유주명"])
    names = [o for o in dict.fromkeys(df_all["소유주명"]) if o in current and o not in SHARED_OWNERS]
    if not names:
        return "우리 가족 자산"
    if len(names) <= 3:
        return " & ".join(names) + " 자산"
    return f"{names[0]} 외 {len(names) - 1}명 자산"


def render_head(target, title, sub):
    target.markdown(
        f'<div class="app-head"><div class="t">{title}</div><div class="s">{sub}</div></div>',
        unsafe_allow_html=True,
    )


def items_html(item_grp, total):
    top = item_grp.sort_values("평가_원", ascending=False)
    vmax = max(top["평가_원"].max(), 1)
    rows = []
    for _, r in top.iterrows():
        share = r["평가_원"] / total * 100 if total else 0
        ret = (r["평가_원"] - r["매수_원"]) / r["매수_원"] * 100 if r["매수_원"] > 0 else None
        if ret is None:
            ret_txt = ""
        else:
            cls = "up" if ret > 0 else ("down" if ret < 0 else "")
            ret_txt = f'<small class="{cls}">{ret:+.1f}%</small>'
        bar = r["평가_원"] / vmax * 100
        rows.append(
            f'<div class="it" style="background:linear-gradient(90deg, rgba(140,124,255,0.22) {bar:.1f}%, '
            f'transparent {bar:.1f}%);border-radius:8px;padding-left:8px;padding-right:8px">'
            f'<span class="nm"><i class="dot" style="background:{ITEM_COLOR}"></i><span>{r["통합종목명"]}</span></span>'
            f'<span class="v">{fmt_won(r["평가_원"])}<span class="pill">{share:.0f}%</span>{ret_txt}</span></div>'
        )
    return '<div class="items">' + "".join(rows) + "</div>"


# =============================================================================
# 화면
# =============================================================================
with st.container(key="headrow"):
    head_c1, head_c2 = st.columns([4, 1], vertical_alignment="center")
head_box = head_c1.empty()
render_head(head_box, "자산 관제", "보유 자산 CSV로 현재 자산을 추정합니다")

# --- 보안 인증 (Streamlit Secrets) ---
if "PASSWORD" not in st.secrets:
    st.error("🔒 시스템 설정 오류: Streamlit Secrets에 비밀번호(PASSWORD)가 설정되지 않았습니다.")
    st.stop()
SECRET_PASSWORD = str(st.secrets["PASSWORD"])

if not st.session_state.get("authenticated", False):
    with st.container(key="glass_login"):
        st.markdown("#### 🔒 보안 인증")
        with st.form("login", border=False):
            entered_pw = st.text_input("접속 비밀번호", type="password")
            ok = st.form_submit_button("접속하기", width="stretch", type="primary")
        if ok:
            if entered_pw == SECRET_PASSWORD:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
    st.stop()

if head_c2.button("잠금", width="stretch"):
    st.session_state["authenticated"] = False
    st.rerun()

# 화면 순서: 대시보드가 위, 데이터 업로드는 아래 (업로드 후 결과가 먼저 보이도록)
dash = st.container()
data_box = st.container(key="glass_data")

# --- 데이터 입력 ---
with data_box:
    st.markdown("#### 📂 자산 데이터")
    uploaded = st.file_uploader(
        "자산 대장 CSV 파일",
        type=["csv", "txt"],
        help="엑셀에서 'CSV UTF-8' 또는 일반 'CSV'로 저장한 파일 모두 가능합니다.",
    )
    st.download_button(
        "CSV 양식 내려받기", TEMPLATE_CSV.encode("utf-8-sig"),
        file_name="자산대장_양식.csv", mime="text/csv", width="stretch",
    )
    show_settings = st.toggle("⚙️ 분석 기준일 · 환율 설정")
    analysis_date = datetime.date.today()
    usd_krw = get_usd_krw_rate()
    use_live = True
    if show_settings:
        analysis_date = st.date_input("분석 기준일", value=analysis_date)
        usd_krw = st.number_input("원/달러 환율 (KRW/USD)", value=float(usd_krw), format="%.2f", step=1.0)
        use_live = analysis_date >= datetime.date.today()
        st.caption("기준일이 오늘이면 실시간 시세를 반영하고, 과거 날짜면 CSV에 적힌 평가금액을 그대로 씁니다.")
    info_box = st.container()

if uploaded is None:
    info_box.info("최신 자산 대장 CSV 파일을 업로드해 주세요.")
    st.stop()

# --- 파일 읽기 ---
try:
    text, used_enc = decode_bytes(uploaded.getvalue())
    df_loaded = pd.read_csv(io.StringIO(text), dtype=str, skip_blank_lines=True)
    df, notes = prepare_data(df_loaded)
except Exception as e:
    info_box.error(f"CSV 파일을 읽지 못했습니다: {e}")
    st.stop()

if df.empty:
    info_box.warning("분석할 데이터가 없습니다. CSV 내용을 확인해 주세요.")
    st.stop()

with info_box:
    st.caption(f"📄 {uploaded.name} · {len(df):,}행 · 인코딩 {used_enc} · 환율 {usd_krw:,.2f}원")
    for n in notes:
        st.caption(f"ℹ️ {n}")

curr_dt = pd.Timestamp(analysis_date)

# --- 현재 스냅샷 (실시간 시세) ---
with dash, st.spinner("⚡ 실시간 시세 반영 중..."):
    base = snapshot(df, curr_dt, usd_krw)
    live = {}
    if base is not None and use_live:
        held = base[(base["수량"] > 0) & (base["시장"] != "")]
        kr = tuple(sorted(set(held.loc[held["시장"] == "KR", "종목코드"])))
        us = tuple(sorted(set(held.loc[held["시장"] == "US", "종목코드"])))
        live = get_live_prices(kr, us)
    df_curr = snapshot(df, curr_dt, usd_krw, live_prices=live)

if df_curr is None or df_curr.empty:
    dash.warning(f"{analysis_date} 이전 데이터가 없습니다.")
    st.stop()

eval_curr = df_curr["평가_원"].sum()
buy_curr = df_curr["매수_원"].sum()
gain_curr = eval_curr - buy_curr
ret_curr = gain_curr / buy_curr * 100 if buy_curr > 0 else 0.0
live_cnt = int(df_curr["시세반영"].sum())


def eval_at(days):
    s = snapshot(df, curr_dt - pd.Timedelta(days=days), usd_krw)
    return None if s is None else s["평가_원"].sum()


eval_m6, eval_y1 = eval_at(182), eval_at(365)


def change_card(label, prev):
    if not prev:
        return {"label": label, "value": "-", "sub": "비교 데이터 없음"}
    diff = eval_curr - prev
    pct = diff / prev * 100
    cls = "up" if diff > 0 else ("down" if diff < 0 else "")
    arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "")
    return {
        "label": label,
        "value": f'<span class="{cls}">{pct:+.1f}%</span>',
        "sub": f'<span class="{cls}">{arrow} {fmt_won(abs(diff))}</span> · {fmt_won(prev)}에서',
    }


# 제목: CSV 소유주명 기준
sub = f"{analysis_date.month}월 {analysis_date.day}일 · " + (
    f"실시간 시세 {live_cnt}개 종목 반영" if use_live else "CSV 기록 기준"
)
render_head(head_box, owners_title(df, df_curr), sub)

with dash:
    gain_cls = "up" if gain_curr > 0 else ("down" if gain_curr < 0 else "")
    gain_arrow = "▲" if gain_curr > 0 else ("▼" if gain_curr < 0 else "")
    kpi_cards([
        {
            "label": "총 평가액",
            "value": f"{fmt_won(eval_curr)}원",
            "sub": f'<span class="{gain_cls}">{gain_arrow} {fmt_won(abs(gain_curr))}원 ({ret_curr:+.2f}%)</span>'
                   f" · 원금 {fmt_won(buy_curr)}원",
            "wide": True,
        },
        change_card("6개월 전 대비", eval_m6),
        change_card("1년 전 대비", eval_y1),
    ])

    # ① 총자산 추이 (기간 선택: 6개월·1년 = 월말, 전체 = 분기말)
    with st.container(key="glass_trend"):
        st.markdown("#### 총자산 추이 (만원)")
        period = st.segmented_control(
            "기간", ["6개월", "1년", "전체"], default="6개월",
            key="trend_period", label_visibility="collapsed",
        ) or "6개월"
        first_dt = df["날짜_dt"].min()
        today_cut = curr_dt.normalize()
        if period == "전체":
            ends = [q for q in pd.date_range(start=first_dt, end=curr_dt, freq=pd.offsets.QuarterEnd()) if q < today_cut]
            basis = "분기말"
        else:
            n = 6 if period == "6개월" else 12
            ends = [
                m for m in pd.date_range(end=curr_dt, periods=n + 1, freq=pd.offsets.MonthEnd())
                if first_dt <= m < today_cut
            ][-n:]
            basis = "월말"
        with st.spinner(f"📈 {basis} 시세 조회 중..."):
            trend = build_month_end_trend(df, ends, usd_krw)

        now_lbl = "현재" if use_live else analysis_date.strftime("%y.%m.%d")
        now_part = df_curr.assign(시점=curr_dt, 상태=df_curr["시세반영"].map({True: "실시간", False: "기록"}))
        trend = pd.concat([t for t in (trend, now_part) if t is not None], ignore_index=True)
        trend["라벨"] = [now_lbl if t == curr_dt else t.strftime("%y.%m") for t in trend["시점"]]
        x_order = [m.strftime("%y.%m") for m in ends] + [now_lbl]
        x_order = [x for x in x_order if x in set(trend["라벨"])]

        st.plotly_chart(trend_figure(trend, x_order, 380), config=PLOTLY_CONFIG, theme=None)
        past = trend[trend["시점"] != curr_dt]
        n_est = int((past["상태"] == "추정").sum())
        n_carry = int((past["상태"] == "이월").sum())
        st.caption(
            f"{basis} 기준 · 진한 막대 = 그 달 기록 · 중간 = {basis} 시세로 추정 · 연한 막대 = 직전 기록 사용"
            f" (추정 {n_est}건 · 직전값 {n_carry}건)"
        )

    # ② 소유주별 자산 (기준일 + 소유주별 마지막 기록일)
    with st.container(key="glass_owner"):
        basis_txt = f"{analysis_date.month}월 {analysis_date.day}일 기준" + (" · 실시간 시세" if use_live and live_cnt else "")
        st.markdown(f"#### 소유주별 자산 (만원)\n<span style='font-size:0.78rem;color:var(--ink-2)'>{basis_txt}</span>",
                    unsafe_allow_html=True)
        owner_grp = df_curr.groupby(["소유주명", "계좌유형"])["평가_원"].sum().reset_index()
        owner_grp["평가_만원"] = owner_grp["평가_원"] / 1e4
        owners = owner_grp.groupby("소유주명")["평가_만원"].sum().sort_values(ascending=False).index.tolist()
        last_rec = df_curr.groupby("소유주명")["날짜_dt"].max()
        tick_text = [f"{o}<br><span style='font-size:9px'>{last_rec[o]:%y.%m.%d} 기록</span>" for o in owners]
        fig2 = stacked_by_account(owner_grp, "소유주명", owners, 340)
        fig2.update_xaxes(tickmode="array", tickvals=owners, ticktext=tick_text)
        st.plotly_chart(fig2, config=PLOTLY_CONFIG, theme=None)

    # ③ 주요 종목
    with st.container(key="glass_items"):
        st.markdown("#### 주요 종목")
        df_curr["통합종목명"] = df_curr["종목"].map(map_underlying_asset)
        item_grp = df_curr.groupby("통합종목명")[["평가_원", "매수_원"]].sum().reset_index()
        share = item_grp["평가_원"] / eval_curr * 100 if eval_curr else 0
        main_items = item_grp[share > 1.0]
        small = item_grp[share <= 1.0]
        if not main_items.empty:
            st.markdown(items_html(main_items, eval_curr), unsafe_allow_html=True)
        if not small.empty:
            st.caption(f"비중 1% 이하 {len(small)}개 종목 생략 (합계 {fmt_won(small['평가_원'].sum())}원)")
