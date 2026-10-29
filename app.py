# -*- coding: utf-8 -*-
"""
================================================================================
성민 & 보현 부부 실시간 자산 관제 시스템 (v11.0 - CSV 업로드 / 모바일 대응)
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
    page_title="성민 & 보현 자산 관제",
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
html, body, .stApp, .stMarkdown, .stCaption, p, h1, h2, h3, h4, label, input, button, textarea {
    font-family: 'Noto Sans KR', 'Malgun Gothic', 'Apple SD Gothic Neo', 'Nanum Gothic', sans-serif;
}
/* 아이콘 폰트 보호 */
[data-testid="stIconMaterial"], .material-symbols-rounded {
    font-family: 'Material Symbols Rounded' !important;
}
/* 업로드 영역의 장식 아이콘은 숨김 (폰트 실패 시 'upload' 글자 노출 방지) */
[data-testid="stFileUploaderDropzone"] [data-testid="stIconMaterial"] { display: none; }

/* 모바일 여백/글자 크기 */
.block-container { padding-top: 2.2rem; padding-bottom: 3rem; }
@media (max-width: 640px) {
    .block-container { padding-left: 0.9rem; padding-right: 0.9rem; }
    h1 { font-size: 1.45rem !important; }
    h3 { font-size: 1.1rem !important; }
}

/* 요약 카드 (st.metric 대신: 화살표 아이콘 없이 ▲▼ 문자만 사용) */
.kpi-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin: 6px 0 4px; }
.kpi { border: 1px solid rgba(128,128,128,0.25); border-radius: 12px; padding: 12px 14px; min-width: 0; }
.kpi.wide { grid-column: 1 / -1; }
.kpi .lbl { font-size: 0.8rem; opacity: 0.7; margin-bottom: 2px; }
.kpi .val { font-size: 1.25rem; font-weight: 700; line-height: 1.3; word-break: keep-all; overflow-wrap: anywhere; }
.kpi.wide .val { font-size: 1.6rem; }
.kpi .sub { font-size: 0.82rem; margin-top: 2px; opacity: 0.85; }
.up { color: #d6336c; }     /* 국내 관례: 상승 = 빨강 */
.down { color: #1c7ed6; }   /* 하락 = 파랑 */
@media (max-width: 380px) {
    .kpi .val { font-size: 1.05rem; }
    .kpi.wide .val { font-size: 1.35rem; }
}
</style>
"""
)

# 계좌 유형별 색 (검증된 범주형 팔레트 1~5번, 고정 순서)
ACC_ORDER = ["ISA", "PSA", "IRP", "CA", "CMA"]
ACC_COLORS = {"ISA": "#2a78d6", "PSA": "#eb6834", "IRP": "#1baf7a", "CA": "#eda100", "CMA": "#e87ba4"}
ACC_LABELS = {"ISA": "ISA", "PSA": "연금저축(PSA)", "IRP": "IRP", "CA": "일반(CA)", "CMA": "현금(CMA)"}

STD_COLS = ["날짜", "소유주명", "계좌ID", "평가금액", "매수금액", "평가손익", "수량", "평균단가", "종목", "종목코드", "통화"]
NUM_COLS = ["평가금액", "매수금액", "평가손익", "수량", "평균단가"]

PLOTLY_CONFIG = {"displayModeBar": False, "scrollZoom": False, "responsive": True}


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
        html += f'<div class="{cls}"><div class="lbl">{c["label"]}</div><div class="val">{c["value"]}</div>{sub}</div>'
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def style_fig(fig, height):
    fig.update_layout(
        font=dict(family=FONT_STACK, size=12),
        height=height,
        margin=dict(l=8, r=8, t=60, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0, title_text=""),
        dragmode=False,
        hoverlabel=dict(font_family=FONT_STACK),
        bargap=0.25,
    )
    fig.update_xaxes(fixedrange=True, showgrid=False)
    fig.update_yaxes(fixedrange=True, gridcolor="rgba(128,128,128,0.18)")
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
            marker=dict(color=ACC_COLORS[acc], line=dict(width=1, color="rgba(255,255,255,0.9)")),
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
    fig.update_layout(barmode="stack", yaxis_title="평가금액 (만원)")
    fig.update_yaxes(range=[0, max(totals.max(), 1) * 1.15], tickformat=",.0f")
    return style_fig(fig, height)


TEMPLATE_CSV = (
    "날짜,소유주명,계좌ID,평가금액,매수금액,평가손익,수량,평균단가,종목,종목코드,통화\n"
    "2026-10-29,성민,ISA_01,15213842,11940481,3273361,496,24075,ACE 미국나스닥100,367380,KRW\n"
    "2026-10-29,성민,CA_01,878.56,1196.51,-317.49,9.11989,131.19,SOXL,SOXL,USD\n"
    "2026-10-29,공동,CMA_01,6300000,6300000,0,,,네이버페이,,KRW\n"
)

# =============================================================================
# 화면
# =============================================================================
st.title("💰 성민 & 보현 자산 관제")

# --- 보안 인증 (Streamlit Secrets) ---
if "PASSWORD" not in st.secrets:
    st.error("🔒 시스템 설정 오류: Streamlit Secrets에 비밀번호(PASSWORD)가 설정되지 않았습니다.")
    st.stop()
SECRET_PASSWORD = str(st.secrets["PASSWORD"])

if not st.session_state.get("authenticated", False):
    st.markdown("### 🔒 보안 인증")
    with st.form("login"):
        entered_pw = st.text_input("접속 비밀번호", type="password")
        ok = st.form_submit_button("접속하기", width="stretch")
    if ok:
        if entered_pw == SECRET_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    st.stop()

top_c1, top_c2 = st.columns([3, 1], vertical_alignment="center")
top_c1.caption("✅ 시스템 정상 접속됨")
if top_c2.button("잠금", width="stretch"):
    st.session_state["authenticated"] = False
    st.rerun()

st.divider()

# --- 데이터 입력 ---
st.subheader("📂 자산 데이터 업로드")
uploaded = st.file_uploader(
    "자산 대장 CSV 파일을 선택하세요",
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
if show_settings:
    analysis_date = st.date_input("분석 기준일", value=analysis_date)
    usd_krw = st.number_input("원/달러 환율 (KRW/USD)", value=float(usd_krw), format="%.2f", step=1.0)
    use_live = analysis_date >= datetime.date.today()
    st.caption("기준일이 오늘이면 실시간 시세를 반영하고, 과거 날짜면 CSV에 적힌 평가금액을 그대로 씁니다.")
else:
    use_live = True

st.divider()

if uploaded is None:
    st.info("👆 최신 자산 대장 CSV 파일을 업로드해 주세요.")
    st.stop()

# --- 파일 읽기 ---
try:
    text, used_enc = decode_bytes(uploaded.getvalue())
    df_loaded = pd.read_csv(io.StringIO(text), dtype=str, skip_blank_lines=True)
except Exception as e:
    st.error(f"CSV 파일을 읽지 못했습니다: {e}")
    st.stop()

try:
    df, notes = prepare_data(df_loaded)
except Exception as e:
    st.error(f"데이터 정리 중 오류가 발생했습니다: {e}")
    st.stop()

if df.empty:
    st.warning("분석할 데이터가 없습니다. CSV 내용을 확인해 주세요.")
    st.stop()

st.caption(f"📄 {uploaded.name} · {len(df):,}행 · 인코딩 {used_enc} · 환율 {usd_krw:,.2f}원")
for n in notes:
    st.caption(f"ℹ️ {n}")

curr_dt = pd.Timestamp(analysis_date)

# --- 현재 스냅샷 (실시간 시세) ---
with st.spinner("⚡ 실시간 시세 반영 중..."):
    base = snapshot(df, curr_dt, usd_krw)
    live = {}
    if base is not None and use_live:
        held = base[(base["수량"] > 0) & (base["시장"] != "")]
        kr = tuple(sorted(set(held.loc[held["시장"] == "KR", "종목코드"])))
        us = tuple(sorted(set(held.loc[held["시장"] == "US", "종목코드"])))
        live = get_live_prices(kr, us)
    df_curr = snapshot(df, curr_dt, usd_krw, live_prices=live)

if df_curr is None or df_curr.empty:
    st.warning(f"{analysis_date} 이전 데이터가 없습니다.")
    st.stop()

eval_curr = df_curr["평가_원"].sum()
buy_curr = df_curr["매수_원"].sum()
gain_curr = eval_curr - buy_curr
ret_curr = gain_curr / buy_curr * 100 if buy_curr > 0 else 0.0


def eval_at(days):
    s = snapshot(df, curr_dt - pd.Timedelta(days=days), usd_krw)
    return None if s is None else s["평가_원"].sum()


eval_m6, eval_y1 = eval_at(182), eval_at(365)


def change_sub(prev):
    if not prev:
        return "비교 데이터 없음"
    return signed(eval_curr - prev, (eval_curr - prev) / prev * 100)


st.subheader(f"📊 자산 현황 요약 ({analysis_date:%Y-%m-%d})")
live_cnt = int(df_curr["시세반영"].sum())
kpi_cards([
    {"label": "현재 총 평가액", "value": f"{fmt_won(eval_curr)}원", "sub": f"{eval_curr:,.0f} 원", "wide": True},
    {"label": "총 매수 원금", "value": f"{fmt_won(buy_curr)}원"},
    {"label": "총 평가 손익", "value": signed(gain_curr), "sub": f"수익률 {ret_curr:+.2f}%"},
    {"label": "6개월 전 대비", "value": f"{fmt_won(eval_m6)}원" if eval_m6 else "-", "sub": change_sub(eval_m6)},
    {"label": "1년 전 대비", "value": f"{fmt_won(eval_y1)}원" if eval_y1 else "-", "sub": change_sub(eval_y1)},
])
st.caption(f"실시간 시세 반영 {live_cnt}개 종목 / 전체 {len(df_curr)}개 (나머지는 CSV 평가금액 사용)")

st.divider()

# ① 총자산 추이 (기록된 모든 날짜 + 현재)
st.markdown("### ① 총자산 추이")
dates = sorted(df.loc[df["날짜_dt"] <= curr_dt, "날짜_dt"].unique())
trend_rows = []
labels = []
for d in dates:
    s = snapshot(df, pd.Timestamp(d), usd_krw)
    # 연도가 바뀌는 첫 시점에는 연도 표시 (예: 26/01/06), 나머지는 월/일만
    ts = pd.Timestamp(d)
    lbl = ts.strftime("%y/%m/%d") if (not labels or ts.year != prev_year) else ts.strftime("%m/%d")
    prev_year = ts.year
    labels.append(lbl)
    for acc, v in s.groupby("계좌유형")["평가_원"].sum().items():
        trend_rows.append({"시점": lbl, "계좌유형": acc, "평가_만원": v / 1e4})
now_lbl = "현재" if use_live else analysis_date.strftime("%m/%d")
if now_lbl not in labels:
    labels.append(now_lbl)
    for acc, v in df_curr.groupby("계좌유형")["평가_원"].sum().items():
        trend_rows.append({"시점": now_lbl, "계좌유형": acc, "평가_만원": v / 1e4})

if trend_rows:
    recent = labels[-12:]  # 모바일 가독성을 위해 최근 12개 시점만
    df_t = pd.DataFrame(trend_rows)
    fig1 = stacked_by_account(df_t[df_t["시점"].isin(recent)], "시점", recent, 420, label_last_only=True)
    fig1.update_xaxes(tickangle=-45, type="category", automargin=True)
    st.plotly_chart(fig1, config=PLOTLY_CONFIG)
    if len(labels) > 12:
        st.caption(f"최근 12개 시점만 표시 (전체 {len(labels)}개)")

# ② 인물별 자산 현황
st.markdown("### ② 인물별 자산 현황")
owner_grp = df_curr.groupby(["소유주명", "계좌유형"])["평가_원"].sum().reset_index()
owner_grp["평가_만원"] = owner_grp["평가_원"] / 1e4
owners = owner_grp.groupby("소유주명")["평가_만원"].sum().sort_values(ascending=False).index.tolist()
fig2 = stacked_by_account(owner_grp, "소유주명", owners, 360)
st.plotly_chart(fig2, config=PLOTLY_CONFIG)

# ③ 주요 종목별 자산 현황
st.markdown("### ③ 주요 종목별 자산 현황")
df_curr["통합종목명"] = df_curr["종목"].map(map_underlying_asset)
item_grp = df_curr.groupby("통합종목명")[["평가_원", "매수_원"]].sum().reset_index()
item_grp["비중"] = item_grp["평가_원"] / eval_curr * 100 if eval_curr else 0
main_items = item_grp[item_grp["비중"] > 1.0].sort_values("평가_원")
if not main_items.empty:
    vals = main_items["평가_원"] / 1e4
    fig3 = go.Figure(go.Bar(
        x=vals, y=main_items["통합종목명"], orientation="h",
        marker=dict(color=ACC_COLORS["ISA"]),
        text=[f"{v:,.0f}만·{p:.0f}%" for v, p in zip(vals, main_items["비중"])],
        textposition="outside", cliponaxis=False,
        hovertemplate="%{y}<br>%{x:,.0f}만원<extra></extra>",
    ))
    style_fig(fig3, max(320, len(main_items) * 38 + 40))
    fig3.update_layout(showlegend=False, xaxis_title="평가금액 (만원)", margin=dict(l=8, r=8, t=10, b=8))
    fig3.update_xaxes(range=[0, vals.max() * 1.6], showgrid=True, gridcolor="rgba(128,128,128,0.18)")
    fig3.update_yaxes(showgrid=False, automargin=True)
    st.plotly_chart(fig3, config=PLOTLY_CONFIG)
    small = item_grp[item_grp["비중"] <= 1.0]
    if not small.empty:
        st.caption(f"비중 1% 이하 {len(small)}개 종목은 생략 (합계 {fmt_won(small['평가_원'].sum())}원)")

# ④ 계좌별 상세
st.markdown("### ④ 계좌별 상세")
acc_tbl = (
    df_curr.groupby(["계좌ID", "소유주명"])
    .agg(기준일=("날짜_dt", "max"), 평가=("평가_원", "sum"), 원금=("매수_원", "sum"), 실시간=("시세반영", "any"))
    .reset_index()
    .sort_values("평가", ascending=False)
)
acc_tbl["수익률"] = ((acc_tbl["평가"] - acc_tbl["원금"]) / acc_tbl["원금"].where(acc_tbl["원금"] > 0) * 100).round(1)
acc_tbl["평가(만원)"] = (acc_tbl["평가"] / 1e4).round(0)
acc_tbl["기준일"] = acc_tbl["기준일"].dt.strftime("%y.%m.%d")
acc_tbl["실시간"] = acc_tbl["실시간"].map({True: "O", False: "-"})
st.dataframe(
    acc_tbl[["계좌ID", "평가(만원)", "수익률", "기준일", "실시간", "소유주명"]],
    hide_index=True,
    width="stretch",
    column_config={
        "평가(만원)": st.column_config.NumberColumn(format="localized"),
        "수익률": st.column_config.NumberColumn("수익률(%)", format="%.1f"),
    },
)
st.caption("기준일 = 그 계좌를 CSV에 마지막으로 기록한 날짜. 오래된 계좌는 새로 기록해 주세요.")
