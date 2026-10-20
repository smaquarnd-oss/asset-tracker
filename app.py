# -*- coding: utf-8 -*-
"""
================================================================================
성민 & 보현 부부 실시간 자산 관제 시스템 (Plotly Mobile Native Version v10.0)
================================================================================
"""

import io
import datetime
import urllib.request
import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# 페이지 설정
st.set_page_config(
    page_title="성민 & 보현 자산 관제",
    page_icon="💰",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- API 및 유틸리티 함수 ---

@st.cache_data(ttl=600)
def get_usd_krw_rate():
    url = "https://query1.finance.yahoo.com/v8/finance/chart/KRW=X"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            rate = data['chart']['result'][0]['meta']['regularMarketPrice']
            return float(rate)
    except Exception:
        return 1335.0

def get_kr_stock_price(code):
    if pd.isna(code) or str(code).strip() == "" or str(code).lower() == "nan":
        return None
    code_str = str(code).split('.')[0].zfill(6)
    url = f"https://m.stock.naver.com/api/stock/{code_str}/basic"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            close_price_str = data['closePrice'].replace(',', '')
            return float(close_price_str)
    except Exception:
        return None

def get_us_stock_price(ticker_sym):
    if pd.isna(ticker_sym) or str(ticker_sym).strip() == "" or str(ticker_sym).lower() == "nan":
        return None
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_sym}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            price = data['chart']['result'][0]['meta']['regularMarketPrice']
            return float(price)
    except Exception:
        return None

def robust_column_mapping(df_in):
    col_map = {}
    for c in df_in.columns:
        c_clean = str(c).strip().replace('\ufeff', '')
        if '소유주' in c_clean or '소유자' in c_clean or '이름' in c_clean:
            col_map[c] = '소유주명'
        elif '계좌' in c_clean or '구분' in c_clean or '통장' in c_clean:
            if 'ID' in c_clean or '코드' in c_clean or '번호' in c_clean:
                col_map[c] = '계좌ID'
            else:
                col_map[c] = '계좌종류'
        elif '평가' in c_clean and '손익' not in c_clean:
            col_map[c] = '평가금액'
        elif '매수' in c_clean or '원금' in c_clean or '투자금' in c_clean:
            col_map[c] = '매수금액'
        elif '수량' in c_clean or '주수' in c_clean:
            col_map[c] = '수량'
        elif '종목' in c_clean and '코드' not in c_clean:
            col_map[c] = '종목'
        elif '코드' in c_clean or '티커' in c_clean or 'ticker' in c_clean.lower():
            col_map[c] = '종목코드'
        elif '날짜' in c_clean or '일자' in c_clean or '기준일' in c_clean:
            col_map[c] = '날짜'
    return df_in.rename(columns=col_map)

def smart_account_type(row):
    acc = str(row.get('계좌종류', '')).upper().strip()
    acc_id = str(row.get('계좌ID', '')).upper().strip()
    item = str(row.get('종목', '')).upper().strip()
    inst = str(row.get('금융기관', '')).upper().strip()
    combined = f"{acc} {acc_id} {item} {inst}"
    
    if 'ISA' in combined:
        return 'ISA'
    elif '연금' in combined or 'PSA' in combined or 'PENSION' in combined:
        return 'PSA'
    elif 'IRP' in combined or '퇴직' in combined:
        return 'IRP'
    elif 'CMA' in combined or '현금' in combined or '공동' in combined or '네이버' in combined:
        return '공통/CMA'
    else:
        return 'CA'

def map_underlying_asset(item_name, ticker_code):
    name = str(item_name).upper().strip()
    ticker_str = str(ticker_code).upper().strip()
    
    if any(k in name or k in ticker_str for k in ['나스닥100', 'NASDAQ100', 'QQQ', 'QQQM']):
        if '미국채' in name or '혼합' in name:
            return '나스닥100 미국채혼합'
        return '미국 나스닥100'
    elif any(k in name or k in ticker_str for k in ['S&P500', 'S&P 500', 'SPYM', 'VOO', 'SPLG', 'IVV']):
        return '미국 S&P500'
    elif any(k in name or k in ticker_str for k in ['미국반도체', 'SOXX', 'SMH']):
        return '미국 반도체'
    elif any(k in name or k in ticker_str for k in ['테크TOP10', '테크 TOP 10', 'TECH TOP 10', 'MAG7', 'M7']):
        return '미국 테크TOP10'
    elif 'SOXL' in name or 'SOXL' in ticker_str:
        return 'SOXL (반도체 3배)'
    elif 'TQQQ' in name or 'TQQQ' in ticker_str:
        return 'TQQQ (나스닥 3배)'
    elif 'KODEX 200' in name or 'KODEX200' in name:
        return 'KODEX 200'
    elif '레버리지' in name:
        return '국내 레버리지'
    elif 'TDF' in name:
        return 'TDF 2060'
    elif 'AI반도체' in name:
        return 'KODEX AI반도체'
    elif '네이버페이' in name or 'CMA' in name or '현금' in name:
        return '현금 / CMA'
    else:
        return item_name

def get_snapshot_for_date(df_raw, target_date_str, group_cols, usd_krw, is_current_period=False):
    target_dt = pd.to_datetime(target_date_str)
    df_filtered = df_raw[df_raw['날짜_dt'] <= target_dt].copy()
    
    if df_filtered.empty:
        return None, 0.0, 0.0
        
    df_sorted = df_filtered.sort_values('날짜_dt', ascending=True)
    df_latest = df_sorted.groupby(group_cols, as_index=False).last()
    
    eval_list = []
    for idx, row in df_latest.iterrows():
        ticker_code = str(row.get('종목코드', '')).strip()
        quantity = row.get('수량', 0)
        baseline_eval = row.get('평가금액', 0)
        
        try:
            qty_num = float(quantity)
        except Exception:
            qty_num = 0.0
            
        current_eval_krw = baseline_eval
        
        if is_current_period:
            if ticker_code in ['SOXL', 'QQQM', 'SPYM', 'TQQQ', 'VT', 'VOO', 'QQQ', 'SMH']:
                us_price = get_us_stock_price(ticker_code)
                if us_price is not None:
                    current_eval_krw = qty_num * us_price * usd_krw
            elif len(ticker_code) >= 5 and (ticker_code.isdigit() or ticker_code[:-1].isdigit()):
                kr_price = get_kr_stock_price(ticker_code)
                if kr_price is not None:
                    current_eval_krw = qty_num * kr_price
                    
        eval_list.append(current_eval_krw)
        
    df_latest['실시간평가금액'] = eval_list
    df_latest['실시간평가손익'] = df_latest['실시간평가금액'] - df_latest['매수금액']
    
    total_eval = df_latest['실시간평가금액'].sum()
    total_buy = df_latest['매수금액'].sum()
    
    return df_latest, total_eval, total_buy

# --- 📱 모바일 전용 메인 레이아웃 (Plotly 적용) ---

# --- 📱 모바일 전용 메인 레이아웃 (Plotly 적용) ---

st.title("💰 성민 & 보현 자산 관제")

# --- 🔐 보안 인증 (Streamlit Secrets 전용) ---
if "PASSWORD" in st.secrets:
    SECRET_PASSWORD = str(st.secrets["PASSWORD"])
else:
    st.error("🔒 시스템 설정 오류: Streamlit Secrets에 비밀번호가 설정되지 않았습니다.")
    st.stop()

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    st.markdown("### 🔒 보안 인증")
    entered_pw = st.text_input("접속 비밀번호 입력", type="default", key="clean_pw")
    if st.button("접속하기", use_container_width=True):
        if entered_pw == SECRET_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    st.stop()

top_c1, top_c2 = st.columns([3, 1])
with top_c1:
    st.caption("✅ 시스템 정상 접속됨")
with top_c2:
    if st.button("잠금", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

st.markdown("---")

st.subheader("📂 자산 데이터 입력")
raw_csv_text = st.text_area(
    "CSV 데이터 입력", 
    height=140, 
    placeholder="날짜,소유주,계좌종류,종목,종목코드,수량,평가금액,매수금액..."
)

with st.expander("⚙️ 분석 기준일 및 환율 설정"):
    default_date = datetime.date.today()
    analysis_date = st.date_input("분석 기준일", value=default_date)
    analysis_date_str = analysis_date.strftime('%Y-%m-%d')
    auto_rate = get_usd_krw_rate()
    custom_rate = st.number_input("원/달러 환율 (KRW/USD)", value=auto_rate, format="%.2f")

st.markdown("---")

df_loaded = None
if raw_csv_text.strip():
    try:
        df_loaded = pd.read_csv(io.StringIO(raw_csv_text))
    except Exception as e:
        st.error(f"CSV 파싱 오류: {e}")

if df_loaded is not None:
    try:
        df = robust_column_mapping(df_loaded)
        
        if '소유주명' not in df.columns: df['소유주명'] = '공동'
        if '계좌종류' not in df.columns: df['계좌종류'] = '일반'
        if '금융기관' not in df.columns: df['금융기관'] = '증권사'
        
        df['표준계좌종류'] = df.apply(smart_account_type, axis=1)
        
        if '날짜' in df.columns:
            df['날짜_dt'] = pd.to_datetime(df['날짜'].astype(str).str.replace('.', '-'), errors='coerce')
        else:
            df['날짜_dt'] = pd.to_datetime(default_date)

        if '계좌ID' in df.columns:
            group_cols = ['계좌ID', '종목']
        else:
            group_cols = ['소유주명', '표준계좌종류', '금융기관', '종목']
        group_cols = [c for c in group_cols if c in df.columns]

        curr_dt = pd.to_datetime(analysis_date_str)
        m6_dt = curr_dt - pd.Timedelta(days=180)
        y1_dt = curr_dt - pd.Timedelta(days=365)
        
        dt_y1_str = y1_dt.strftime('%Y-%m-%d')
        dt_m6_str = m6_dt.strftime('%Y-%m-%d')
        dt_curr_str = curr_dt.strftime('%Y-%m-%d')
        
        with st.spinner("⚡ 실시간 시세 반영 및 자산 연산 중..."):
            df_y1, eval_y1, buy_y1 = get_snapshot_for_date(df, dt_y1_str, group_cols, custom_rate, is_current_period=False)
            df_m6, eval_m6, buy_m6 = get_snapshot_for_date(df, dt_m6_str, group_cols, custom_rate, is_current_period=False)
            df_curr, eval_curr, buy_curr = get_snapshot_for_date(df, dt_curr_str, group_cols, custom_rate, is_current_period=True)

        if df_curr is not None and not df_curr.empty:
            total_gain_curr = eval_curr - buy_curr
            total_return_curr = (total_gain_curr / buy_curr * 100) if buy_curr > 0 else 0.0

            st.subheader(f"📊 자산 현황 요약 ({dt_curr_str})")
            st.metric("현재 총 평가액", f"{eval_curr:,.0f} 원", f"{eval_curr/1e8:.3f} 억")
            
            m_col1, m_col2 = st.columns(2)
            m_col1.metric("총 매수 원금", f"{buy_curr/1e4:,.0f} 만원")
            m_col2.metric("총 평가 손익", f"{total_gain_curr/1e4:+,.0f} 만원", f"{total_return_curr:+.2f} %")

            st.markdown("---")
            
            acc_colors = {
                'ISA': '#2ecc71', 'PSA': '#3498db', 'IRP': '#9b59b6', 
                'CA': '#e74c3c', '공통/CMA': '#f39c12'
            }
            account_cats = list(acc_colors.keys())

            # =============================================================
            # [Plotly 차트 1] 총자산 추이
            # =============================================================
            st.markdown("### ① 총자산 추이 및 계좌별 현황")
            periods = ['1년 전', '6개월 전', '현재']
            period_dfs = [df_y1, df_m6, df_curr]
            period_evals = [eval_y1, eval_m6, eval_curr]
            
            chart1_data = []
            for p_name, p_df, p_eval in zip(periods, period_dfs, period_evals):
                if p_df is None or p_df.empty or p_eval == 0:
                    continue
                acc_summary = p_df.groupby('표준계좌종류')[['실시간평가금액', '매수금액']].sum()
                for acc in account_cats:
                    if acc in acc_summary.index:
                        a_eval = acc_summary.loc[acc, '실시간평가금액']
                        chart1_data.append({
                            '시점': p_name,
                            '계좌종류': acc,
                            '평가금액(만원)': a_eval / 1e4
                        })
            
            if chart1_data:
                df_c1 = pd.DataFrame(chart1_data)
                fig1 = px.bar(
                    df_c1, x='시점', y='평가금액(만원)', color='계좌종류',
                    color_discrete_map=acc_colors, text_auto='.0f'
                )
                fig1.update_layout(
                    xaxis_title="", yaxis_title="평가금액 (만원)",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    margin=dict(l=10, r=10, t=30, b=10), height=380
                )
                st.plotly_chart(fig1, use_container_width=True)

            # =============================================================
            # [Plotly 차트 2] 인물별 자산 현황
            # =============================================================
            st.markdown("### ② 인물별 자산 현황")
            owner_acc_grp = df_curr.groupby(['소유주명', '표준계좌종류'])[['실시간평가금액', '매수금액']].sum().reset_index()
            
            chart2_data = []
            for _, row in owner_acc_grp.iterrows():
                chart2_data.append({
                    '소유주': row['소유주명'],
                    '계좌종류': row['표준계좌종류'],
                    '평가금액(만원)': row['실시간평가금액'] / 1e4
                })
            
            if chart2_data:
                df_c2 = pd.DataFrame(chart2_data)
                fig2 = px.bar(
                    df_c2, x='소유주', y='평가금액(만원)', color='계좌종류',
                    color_discrete_map=acc_colors, text_auto='.0f'
                )
                fig2.update_layout(
                    xaxis_title="", yaxis_title="평가금액 (만원)",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    margin=dict(l=10, r=10, t=30, b=10), height=380
                )
                st.plotly_chart(fig2, use_container_width=True)

            # =============================================================
            # [Plotly 차트 3] 주요 종목별 자산 현황
            # =============================================================
            st.markdown("### ③ 주요 종목별 자산 현황")
            df_curr['통합종목명'] = df_curr.apply(lambda r: map_underlying_asset(r['종목'], r['종목코드']), axis=1)
            item_grp = df_curr.groupby('통합종목명')[['실시간평가금액', '매수금액']].sum().reset_index()
            item_grp['비중(%)'] = (item_grp['실시간평가금액'] / eval_curr * 100).round(2)
            item_grp['수익률(%)'] = ((item_grp['실시간평가금액'] - item_grp['매수금액']) / item_grp['매수금액'] * 100).fillna(0).round(2)
            
            main_items = item_grp[item_grp['비중(%)'] > 1.0].copy().sort_values('실시간평가금액', ascending=True)
            
            if not main_items.empty:
                fig3 = px.bar(
                    main_items, x=main_items['실시간평가금액'] / 1e4, y='통합종목명',
                    orientation='h', text=main_items['실시간평가금액'] / 1e4
                )
                fig3.update_traces(texttemplate='%{text:,.0f}만', textposition='outside')
                fig3.update_layout(
                    xaxis_title="평가금액 (만원)", yaxis_title="",
                    margin=dict(l=10, r=20, t=20, b=10), height=max(350, len(main_items) * 35)
                )
                st.plotly_chart(fig3, use_container_width=True)

    except Exception as e:
        st.error(f"데이터 분석 중 오류가 발생했습니다: {e}")
else:
    st.info("👆 위 입력 칸에 최신 자산 대장 CSV 내용을 복사해서 붙여넣어 주세요.")
