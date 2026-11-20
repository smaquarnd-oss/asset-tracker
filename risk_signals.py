# -*- coding: utf-8 -*-
"""종목별 위험·매도 점검 규칙 (Streamlit 앱용, 표준 라이브러리만 사용, 개인정보 없음).

각 보유 종목에 정상 / 주의 / 매도 검토 / 확인 불가 와 쉬운 이유를 붙인다.
비중은 사용자가 직접 정하며, 이 모듈은 추천만 한다(매매·저장 없음).

점검 (프리셋 '중간', 괄호 = 레버리지 ETF):
  * 추세 이탈   : 200일 평균선 아래 5거래일 연속에서 전환, 전환 후 20거래일 재전환 금지
                  (휩쏘 방지). 레버리지는 기초자산 기준.  -> 주의 (레버리지: 매도 검토)
  * 고점 대비   : 1년(252거래일) 최고가 대비 -15% 주의 / -25% 매도 검토 (-25% / -40%)
  * 손실 한도   : 평균단가 대비 -15% 주의 / -25% 매도 검토 (-25% / -40%)
  * 이익 지키기 : 수익 +30% 이상인데 고점 대비 -15% -> 주의
  * 쏠림(참고)  : 가족 자산의 40% 이상 -> 메모만

같은 규칙이 Asset manage/strategy/signals.py 에도 있다(테스트로 결과 일치를 확인).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

Series = Sequence[Tuple[str, Decimal]]   # [(YYYY-MM-DD, 종가)] 오래된 것부터
HIGH_WINDOW = 252
LOOKBACK_DAYS = 420                      # 200일선·1년 고점 계산에 필요한 달력 일수

NORMAL, CAUTION, SELL_REVIEW, UNKNOWN = "정상", "주의", "매도 검토", "확인 불가"
STATUS_ORDER = {SELL_REVIEW: 0, CAUTION: 1, UNKNOWN: 2, NORMAL: 3}

# 레버리지 ETF -> 추세를 볼 기초자산 (시장, 코드)
LEVERAGE_UNDERLYING = {
    "SOXL": ("US", "SOXX"),
    "TQQQ": ("US", "QQQ"),
    "122630": ("KR", "069500"),   # KODEX 레버리지 -> KODEX 200
    "0195S0": ("KR", "000660"),   # TIGER SK하이닉스 단일종목 레버리지 -> SK하이닉스
}


@dataclass(frozen=True)
class Preset:
    name: str
    ma_days: int
    confirm_days: int
    drawdown: Tuple[Decimal, Decimal]
    drawdown_leveraged: Tuple[Decimal, Decimal]
    loss: Tuple[Decimal, Decimal]
    loss_leveraged: Tuple[Decimal, Decimal]
    profit_gain: Decimal = Decimal(30)
    profit_drop: Decimal = Decimal(-15)
    concentration: Decimal = Decimal(40)
    cooldown_days: int = 20


PRESETS = {
    "보수적": Preset("보수적", 60, 3, (Decimal(-10), Decimal(-20)), (Decimal(-15), Decimal(-30)),
                  (Decimal(-10), Decimal(-20)), (Decimal(-15), Decimal(-30))),
    "중간": Preset("중간", 200, 5, (Decimal(-15), Decimal(-25)), (Decimal(-25), Decimal(-40)),
                 (Decimal(-15), Decimal(-25)), (Decimal(-25), Decimal(-40))),
    "느슨함": Preset("느슨함", 200, 10, (Decimal(-20), Decimal(-35)), (Decimal(-35), Decimal(-50)),
                  (Decimal(-25), Decimal(-40)), (Decimal(-35), Decimal(-50))),
}
MEDIUM = PRESETS["중간"]


def leverage_info(code: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """(레버리지 여부, 기초자산 시장, 기초자산 코드)"""
    hit = LEVERAGE_UNDERLYING.get(code)
    return (True, hit[0], hit[1]) if hit else (False, None, None)


def trend_states(series: Series, ma_days: int, confirm: int, cooldown: int) -> List[Tuple[str, Optional[str]]]:
    """[(날짜, 'ON'/'OFF'/None)] — 평균선이 계산되기 전에는 None."""
    out: List[Tuple[str, Optional[str]]] = []
    window: List[Decimal] = []
    running = Decimal(0)
    state, streak, since_switch = None, 0, cooldown
    for d, close in series:
        window.append(close)
        running += close
        if len(window) > ma_days:
            running -= window.pop(0)
        if len(window) < ma_days:
            out.append((d, None))
            continue
        side = "ON" if close >= running / ma_days else "OFF"
        if state is None:
            state, since_switch = side, cooldown
        elif side != state:
            streak += 1
            if streak >= confirm and since_switch >= cooldown:
                state, streak, since_switch = side, 0, 0
        else:
            streak = 0
        since_switch += 1
        out.append((d, state))
    return out


def days_below_ma(series: Series, ma_days: int) -> int:
    closes = [c for _, c in series]
    count = 0
    for i in range(len(closes) - 1, ma_days - 2, -1):
        window = closes[i - ma_days + 1:i + 1]
        if len(window) < ma_days or closes[i] >= sum(window) / ma_days:
            break
        count += 1
    return count


def _pct(a: Decimal, b: Decimal) -> Decimal:
    return (a / b - 1) * 100


def evaluate(series: Series, avg_cost: Optional[Decimal], leveraged: bool, preset: Preset = MEDIUM,
             trend_series: Optional[Series] = None):
    """종목 하나 점검 -> (상태, 이유 목록, 지표 dict)."""
    if not series:
        return UNKNOWN, ["시세 없음"], {}
    price_date, price = series[-1]
    level, reasons, metrics = 0, [], {"price": price, "price_date": price_date}

    t_series = trend_series if (leveraged and trend_series) else series
    states = trend_states(t_series, preset.ma_days, preset.confirm_days, preset.cooldown_days)
    state = states[-1][1] if states else None
    below = days_below_ma(t_series, preset.ma_days)
    metrics.update(trend_state=state, days_below_ma=below)
    if state == "OFF":
        what = "기초자산" if t_series is not series else "가격"
        level = max(level, 2 if leveraged else 1)
        reasons.append(f"추세 이탈: {what}이 {preset.ma_days}일선 아래 ({below}일째)")

    high = max(c for _, c in series[-HIGH_WINDOW:])
    dd = _pct(price, high)
    metrics["drawdown_pct"] = dd
    caution, sell = preset.drawdown_leveraged if leveraged else preset.drawdown
    if dd <= sell:
        level = 2
        reasons.append(f"고점 대비 {dd:.1f}% (기준 {sell}%)")
    elif dd <= caution:
        level = max(level, 1)
        reasons.append(f"고점 대비 {dd:.1f}% (주의 기준 {caution}%)")

    if avg_cost and avg_cost > 0:
        gain = _pct(price, avg_cost)
        metrics["gain_pct"] = gain
        caution, sell = preset.loss_leveraged if leveraged else preset.loss
        if gain <= sell:
            level = 2
            reasons.append(f"평균단가 대비 {gain:.1f}% (손실 기준 {sell}%)")
        elif gain <= caution:
            level = max(level, 1)
            reasons.append(f"평균단가 대비 {gain:.1f}% (주의 기준 {caution}%)")
        elif gain >= preset.profit_gain and dd <= preset.profit_drop:
            level = max(level, 1)
            reasons.append(f"이익 지키기: 수익 +{gain:.0f}%인데 고점 대비 {dd:.1f}%")

    return [NORMAL, CAUTION, SELL_REVIEW][level], reasons, metrics
