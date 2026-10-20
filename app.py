# -*- coding: utf-8 -*-
"""
================================================================================
성민 & 보현 부부 실시간 자산 관제 시스템 (Mobile Clean Version v9.2)
================================================================================
"""

import io
import datetime
import urllib.request
import json
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import seaborn as sns
from matplotlib.patches import Patch
import streamlit as st
st.write("Streamlit version:", st.__version__)

```python
# 페이지 설정 (모바일 최적화 및 사이드바 완전 숨김)
st.set_page_config(
    page_title="성민 & 보현 자산 관제",
    page_icon="💰",
    layout="centered",
    initial_sidebar_state="locked"
)

# --- 모바일 Streamlit UI 깨짐 방지 ---
# --- 모바일 Streamlit UI 및 Material Symbols 오류 방지 ---
st.markdown("""
<style>
/* 모바일 사이드바 완전 숨김 */
@media (max-width: 768px) {
    [data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="stSidebarNav"] {
        display: none !important;
    }
}

/* Streamlit Material Symbols가 아이콘 이름을 텍스트로 표시하는 현상 방지 */
[data-testid="stIconMaterial"] {
    font-family: "Material Symbols Rounded" !important;
    font-weight: normal !important;
    font-style: normal !important;
    font-size: 24px !important;
    line-height: 1 !important;
    letter-spacing: normal !important;
    text-transform: none !important;
    white-space: nowrap !important;
    word-wrap: normal !important;
    direction: ltr !important;
    -webkit-font-feature-settings: "liga" !important;
    font-feature-settings: "liga" !important;
    -webkit-font-smoothing: antialiased !important;
}

/* Material Symbols 폰트가 로드되지 않는 경우 아이콘 이름 자체를 노출하지 않음 */
[data-testid="stIconMaterial"] {
    overflow: hidden !important;
    max-width: 24px !important;
    max-height: 24px !important;
}

/* 비밀번호 입력창의 visibility 텍스트가 노출되는 경우 숨김 */
[data-testid="stTextInput"] button [data-testid="stIconMaterial"] {
    font-size: 0 !important;
}

[data-testid="stTextInput"] button [data-testid="stIconMaterial"]::before {
    content: "●" !important;
    font-family: sans-serif !important;
    font-size: 10px !important;
}
</style>
""", unsafe_allow_html=True)

# --- 폰트 및 한글 깨짐 방지 설정 ---
plt.rcParams['font.family'] = 'Noto Sans CJK KR'
plt.rcParams['axes.unicode_minus'] = False
sns.set_theme(style="white")
```

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

# --- 📱 모바일 전용 메인 레이아웃 (어수선함 완전 제거) ---

st.title("💰 성민 & 보현 자산 관제")

SECRET_PASSWORD = "221008" 

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

# 1. 로그인 인증 (텍스트 입력 형식 정돈)
if not st.session_state["authenticated"]:
    st.markdown("### 🔒 보안 인증")
    entered_pw = st.text_input(
    "접속 비밀번호 입력",
    type="password",
    key="clean_pw"
    )
    if st.button("접속하기", use_container_width=True):
        if entered_pw == SECRET_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다.")
    st.stop()

# 인증 완료 상태바
top_c1, top_c2 = st.columns([3, 1])
with top_c1:
    st.caption("✅ 시스템 정상 접속됨")
with top_c2:
    if st.button("잠금", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

st.markdown("---")

# 2. 데이터 입력 (Network Error 원천 차단을 위해 텍스트 복사/붙여넣기 전용 적용)
st.subheader("📂 자산 데이터 입력")
st.caption("모바일 네트워크 오류를 방지하기 위해 CSV 내용을 아래 칸에 복사·붙여넣기 해주세요.")

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
        st.error(f"CSV 파싱 오류 (데이터 형식을 확인해주세요): {e}")

# 3. 데이터 분석 및 리포트 출력
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

            # 메트릭 요약
            st.subheader(f"📊 자산 현황 요약 ({dt_curr_str})")
            st.metric("현재 총 평가액", f"{eval_curr:,.0f} 원", f"{eval_curr/1e8:.3f} 억")
            
            m_col1, m_col2 = st.columns(2)
            m_col1.metric("총 매수 원금", f"{buy_curr/1e4:,.0f} 만원")
            m_col2.metric("총 평가 손익", f"{total_gain_curr/1e4:+,.0f} 만원", f"{total_return_curr:+.2f} %")

            st.markdown("---")
            
            account_cats = ['ISA', 'PSA', 'IRP', 'CA', '공통/CMA']
            acc_colors = {
                'ISA': '#2ecc71', 'PSA': '#3498db', 'IRP': '#9b59b6', 
                'CA': '#e74c3c', '공통/CMA': '#f39c12'
            }
            legend_elements = [
                Patch(facecolor='#2ecc71', edgecolor='w', label='ISA'),
                Patch(facecolor='#3498db', edgecolor='w', label='PSA'),
                Patch(facecolor='#9b59b6', edgecolor='w', label='IRP'),
                Patch(facecolor='#e74c3c', edgecolor='w', label='CA'),
                Patch(facecolor='#f39c12', edgecolor='w', label='CMA')
            ]

            # [차트 1] 총자산 추이
            st.markdown("### ① 총자산 추이 및 계좌별 현황")
            fig1, ax1 = plt.subplots(figsize=(7, 5))
            periods = ['1년 전', '6개월 전', '현재']
            period_dfs = [df_y1, df_m6, df_curr]
            period_evals = [eval_y1, eval_m6, eval_curr]
            bar_width = 0.45
            x_indices = range(len(periods))

            for idx, (p_df, p_eval) in enumerate(zip(period_dfs, period_evals)):
                if p_df is None or p_df.empty or p_eval == 0:
                    continue
                bottom_val = 0
                acc_summary = p_df.groupby('표준계좌종류')[['실시간평가금액', '매수금액']].sum()
                for acc in account_cats:
                    if acc in acc_summary.index:
                        a_eval = acc_summary.loc[acc, '실시간평가금액']
                        a_pct = (a_eval / p_eval * 100) if p_eval > 0 else 0
                        
                        ax1.bar(idx, a_eval/1e4, bottom=bottom_val/1e4, width=bar_width, 
                                color=acc_colors[acc], edgecolor='white', linewidth=1)
                        y_pos = (bottom_val + a_eval / 2) / 1e4
                        if a_pct >= 4.0:
                            ax1.text(idx, y_pos, f"{a_eval/1e4:,.0f}만\n({a_pct:.1f}%)", 
                                     ha='center', va='center', fontsize=7.5, color='white', weight='bold')
                        bottom_val += a_eval

                p_buy = p_df['매수금액'].sum()
                p_ret = ((p_eval - p_buy) / p_buy * 100) if p_buy > 0 else 0
                ax1.text(idx, p_eval/1e4 * 1.02, f"{p_eval/1e8:.2f}억\n({p_ret:+.1f}%)", 
                         ha='center', va='bottom', fontsize=8.5, weight='bold', color='#2c3e50')

            ax1.legend(handles=legend_elements, loc='upper left', ncol=3, frameon=False, fontsize=7)
            max_period_eval = max([v for v in period_evals if v > 0] or [100000])
            ax1.set_ylim(0, max_period_eval/1e4 * 1.35)
            ax1.set_xticks(x_indices)
            ax1.set_xticklabels(periods, fontsize=8.5, weight='bold')
            ax1.set_ylabel("평가금액 (만원)", fontsize=8.5, weight='bold')
            sns.despine(top=True, right=True)
            st.pyplot(fig1, use_container_width=True)

            # [차트 2] 인물별 자산 현황
            st.markdown("### ② 인물별 자산 현황")
            fig2, ax2 = plt.subplots(figsize=(7, 5))
            owner_acc_grp = df_curr.groupby(['소유주명', '표준계좌종류'])[['실시간평가금액', '매수금액']].sum().reset_index()
            owners = df_curr.groupby('소유주명')['실시간평가금액'].sum().sort_values(ascending=False).index
            x_owner_idx = range(len(owners))
            max_owner_eval = df_curr.groupby('소유주명')['실시간평가금액'].sum().max()

            for idx, owner in enumerate(owners):
                owner_df = owner_acc_grp[owner_acc_grp['소유주명'] == owner]
                owner_total_eval = owner_df['실시간평가금액'].sum()
                owner_total_buy = owner_df['매수금액'].sum()
                owner_pct = (owner_total_eval / eval_curr * 100) if eval_curr > 0 else 0
                owner_ret = ((owner_total_eval - owner_total_buy) / owner_total_buy * 100) if owner_total_buy > 0 else 0
                
                bottom_val = 0
                for acc in account_cats:
                    acc_match = owner_df[owner_df['표준계좌종류'] == acc]
                    if acc_match.empty: continue
                    a_eval = acc_match['실시간평가금액'].values[0]
                    a_pct = (a_eval / owner_total_eval * 100) if owner_total_eval > 0 else 0
                    
                    ax2.bar(idx, a_eval/1e4, bottom=bottom_val/1e4, width=bar_width, 
                            color=acc_colors[acc], edgecolor='white', linewidth=1)
                    y_pos = (bottom_val + a_eval / 2) / 1e4
                    if a_pct >= 4.0:
                        ax2.text(idx, y_pos, f"{a_eval/1e4:,.0f}만\n({a_pct:.1f}%)", 
                                 ha='center', va='center', fontsize=7.5, color='white', weight='bold')
                    bottom_val += a_eval

                ax2.text(idx, owner_total_eval/1e4 * 1.02,
                         f"{owner}\n{owner_total_eval/1e8:.2f}억 ({owner_pct:.1f}%)\n[{owner_ret:+.1f}%]",
                         ha='center', va='bottom', fontsize=8.5, weight='bold', color='#2c3e50')

            ax2.set_ylim(0, max_owner_eval/1e4 * 1.35)
            ax2.set_xticks(x_owner_idx)
            ax2.set_xticklabels(owners, fontsize=8.5, weight='bold')
            ax2.set_ylabel("평가금액 (만원)", fontsize=8.5, weight='bold')
            sns.despine(top=True, right=True)
            st.pyplot(fig2, use_container_width=True)

            # [차트 3] 주요 종목별 자산 현황
            st.markdown("### ③ 주요 종목별 자산 현황")
            df_curr['통합종목명'] = df_curr.apply(lambda r: map_underlying_asset(r['종목'], r['종목코드']), axis=1)
            item_grp = df_curr.groupby('통합종목명')[['실시간평가금액', '매수금액']].sum().reset_index()
            item_grp['비중(%)'] = (item_grp['실시간평가금액'] / eval_curr * 100).round(2)
            item_grp['수익률(%)'] = ((item_grp['실시간평가금액'] - item_grp['매수금액']) / item_grp['매수금액'] * 100).fillna(0).round(2)
            
            main_items = item_grp[item_grp['비중(%)'] > 1.0].copy().sort_values('실시간평가금액', ascending=False)
            small_items = item_grp[item_grp['비중(%)'] <= 1.0]
            
            if not small_items.empty:
                small_eval = small_items['실시간평가금액'].sum()
                small_buy = small_items['매수금액'].sum()
                etc_row = pd.DataFrame([{
                    '통합종목명': '기타 소액 종목',
                    '실시간평가금액': small_eval,
                    '매수금액': small_buy,
                    '비중(%)': (small_eval / eval_curr * 100),
                    '수익률(%)': ((small_eval - small_buy) / small_buy * 100) if small_buy > 0 else 0
                }])
                chart3_df = pd.concat([main_items, etc_row], ignore_index=True)
            else:
                chart3_df = main_items.copy()

            fig3, ax3 = plt.subplots(figsize=(7, max(4, len(chart3_df) * 0.45)))
            y_names = chart3_df['통합종목명']
            x_evals_10k = chart3_df['실시간평가금액'] / 1e4
            pct_vals = chart3_df['비중(%)']
            ret_vals = chart3_df['수익률(%)']
            
            palette_colors = ['#34495e' if name == '기타 소액 종목' else sns.color_palette('Blues_r', len(chart3_df))[i] 
                              for i, name in enumerate(y_names)]
                              
            sns.barplot(x=x_evals_10k, y=y_names, hue=y_names, ax=ax3, palette=palette_colors, legend=False)
            
            for p, pct, ret in zip(ax3.patches, pct_vals, ret_vals):
                val = p.get_width()
                label_text = f" {val:,.0f}만 ({pct:.1f}% | {ret:+.1f}%)"
                ax3.annotate(label_text, 
                             (val, p.get_y() + p.get_height() / 2.),
                             ha='left', va='center', fontsize=7.5, weight='bold')

            max_item_eval = max(x_evals_10k) if len(x_evals_10k) > 0 else 1000
            ax3.set_xlim(0, max_item_eval * 1.35)
            ax3.set_xlabel("평가금액 (만원)", fontsize=8.5, weight='bold')
            ax3.set_ylabel("", fontsize=8.5)
            sns.despine(top=True, right=True)
            st.pyplot(fig3, use_container_width=True)

    except Exception as e:
        st.error(f"데이터 분석 중 오류가 발생했습니다: {e}")
else:
    st.info("👆 위 입력 칸에 최신 자산 대장 CSV 내용을 복사해서 붙여넣어 주세요.")
