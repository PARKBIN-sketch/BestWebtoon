"""
스카우팅 데스크 - 베스트도전 일일 스냅샷 수집기
(승격 검증 + 연재주기/공지 감지 + 즉시확인/육성관찰, 결과를 메인 스냅샷에 통합)

사용법:
    python scouting_desk_crawler.py

동작 (하루 1회 실행 기준):
    1. 장르별 베스트도전 목록을 순회하며 조회수/별점/급상승 여부를 수집
    2. 어제 스냅샷과 비교해서 다음 세 트랙을 모두 확인:
       - 승격/삭제 검증: 연재중이었는데 사라진 작품을 titleId로 직접 재조회
       - 트랙 A(즉시확인): 화수는 적은데 이미 장르 내 별점 최상위인 작품
       - 트랙 B(육성관찰): 화당 조회수가 높은데 아직 최상위는 아닌 작품
       - (참고) 성장 신호: 전일 대비 조회수가 크게 늘어난 작품
    3. 위 트랙에서 후보로 뽑힌 작품은 회차 목록까지 추가로 조회해서
       화수 / 최신 회차 부제 / "연재공지·휴재·완결" 키워드 / 연재 주기를 확인
    4. ⭐ 이 딥체크 결과를 후보 작품 자체에 그대로 "붙여서" 오늘 스냅샷에 저장
       (예전 버전은 트랙별로 결과를 로그 파일에만 남기고 끝나서, 사이트에서는
       그 정보를 다시 볼 방법이 없었음 — 이제는 data/YYYY-MM-DD.json 안의
       해당 작품 항목에 signals/episodeCount/keywords 등이 그대로 들어있어서
       스카우팅 데스크 화면에서 바로 배지로 보여줄 수 있음)
    5. 승격/삭제 검증 결과는 별도로 promotion_log.jsonl 에도 누적 기록
    6. ⭐ 순환 스캔(round robin): 위 세 트랙에 안 걸린 나머지 작품들도 버리지 않고,
       "한 번도 확인 안 된 작품" → "가장 오래전에 확인한 작품" 순으로 하루 최대
       ROUND_ROBIN_DAILY_QUOTA개씩 야금야금 딥체크합니다. 서버에 부담 주지
       않으려고 하루 커버리지를 낮게 잡은 대신, 며칠~몇 주에 걸쳐 결국 전체
       작품을 한 바퀴 다 훑는 걸 목표로 합니다. 확인 이력은
       data/deep_check_state.json 에 titleId별로 저장해서 다음 실행 때
       이어서 진행합니다.
    7. ⭐ 연재 주기가 비정상적으로 길면(HIATUS_CADENCE_DAYS 이상) 키워드에
       안 걸려도 자동으로 "hiatus_suspect"(장기휴재 의심) 신호를 붙입니다.
       (실제로 "감사 인사 + 특별편" 같은 제목은 키워드 목록에 없어서 못 잡았는데,
       연재주기 116일이라는 수치로는 잡을 수 있었던 사례가 있었습니다.)
    8. ⭐ 트랙 C(업데이트순 활용, API 호출 0회): 목록 자체가 order=UPDATE라서
       각 작품이 그 장르 안에서 몇 번째로 나왔는지(updateRank)를 기록해두면,
       회차 API를 따로 안 불러도 "최근에 업데이트했고 반응도 괜찮은 작품"을
       공짜로 찾을 수 있습니다. (updateRank 상위 + 장르 내 별점 상위 조합)

⚠️ 중요한 교훈 (실제로 겪은 실패 사례들):
    - "베스트도전 목록에서 사라짐 = 정식연재 승격"이라고 가정했다가 틀렸습니다.
      완결된 지 오래된 작품이 order=UPDATE 정렬에서 자연스럽게 밀려나 사라지는
      경우, 작가가 삭제한 경우가 있었습니다. → finish(연재중)만 후보로 삼고,
      반드시 titleId로 직접 재조회해서 검증합니다.
    - 절대 별점(9.5+) 기준은 함정이었습니다. 베스트도전 별점 자체가 전반적으로
      9점대에 몰려있어서(소수의 애정 독자 위주 투표) 장르당 수백 개가 걸렸습니다.
      → 장르 내 상대 순위로 바꿨습니다.
    - 즉시확인/육성관찰 후보에서 "연재공지"가 뜬 걸 사람이 직접 보고서야
      알아챈 사례가 있었습니다. 원인은 트랙마다 다른 API를 따로 호출해서
      즉시확인/육성관찰은 화수만 확인하고 회차 부제(키워드)는 아예 안 봤기
      때문입니다. → 이번 버전은 fetch_deep_info() 하나로 통합해서, 어느
      트랙에서 후보가 되든 키워드 감지가 항상 같이 이뤄지도록 했습니다.
    - 세 트랙(즉시확인/육성관찰/성장신호) 모두 "1차 필터를 통과한 소수"만
      딥체크했기 때문에, 애초에 필터에 안 걸리는 작품(예: 이미 유명하지만
      더 이상 안 오르는 작품)은 영원히 확인이 안 되는 사각지대가 있었습니다.
      → 순환 스캔으로 결국 모든 작품이 언젠가는 한 번씩 확인되도록 보완했습니다.

✅ 확인된 API:
    - 목록: https://comic.naver.com/api/bestChallenge/list?genre={genre}&order=UPDATE&page={page}
    - 작품 정보(승격/완결 여부 등): https://comic.naver.com/api/article/list/info?titleId={titleId}
    - 회차 목록(부제/날짜/별점): https://comic.naver.com/api/article/list?titleId={titleId}&page={page}&sort=ASC
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path

import requests

# ── 기본 설정 ──────────────────────────────────────────
LIST_URL_TEMPLATE = (
    "https://comic.naver.com/api/bestChallenge/list"
    "?genre={genre}&order=UPDATE&page={page}"
)
INFO_URL_TEMPLATE = "https://comic.naver.com/api/article/list/info?titleId={title_id}"
EPISODE_LIST_URL_TEMPLATE = (
    "https://comic.naver.com/api/article/list?titleId={title_id}&page={page}&sort=ASC"
)
PAGE_SIZE = 30

GENRES = [
    "PURE", "FANTASY", "ACTION", "DAILY", "THRILL",
    "COMIC", "HISTORICAL", "DRAMA", "SENSIBILITY", "SPORTS",
]
INCLUDE_ALL_TAB = True
ALL_TAB_URL_TEMPLATE = "https://comic.naver.com/api/bestChallenge/list?order=UPDATE&page={page}"

MAX_PAGES_PER_GENRE = 5
REQUEST_DELAY_SEC = 1.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    ),
    "Referer": "https://comic.naver.com/webtoon/bestChallenge",
    "Accept": "application/json",
}

OUTPUT_DIR = Path("data")
PROMOTION_LOG_PATH = OUTPUT_DIR / "promotion_log.jsonl"

# 성장 신호(참고용) 기준
RISING_MIN_VIEW = 5000
RISING_MIN_GROWTH_PCT = 5.0
MAX_RISING_CHECKS_PER_DAY = 20

# 트랙 A: 즉시확인(초반 고품질) — 절대 별점 대신 장르 내 상대 순위 사용
IMMEDIATE_TOP_PERCENTILE = 0.02
IMMEDIATE_MAX_EPISODES = 15

# 트랙 B: 육성관찰(화당 조회수) — 화당 조회수 "정상 범위" 기준선은 아직
# 실측 데이터가 없어 잠정치. 몇 주 로그가 쌓이면 장르별 중앙값으로 재조정 필요.
NURTURE_MIN_VIEW = 5000
NURTURE_PERCENTILE_LOW = 0.05
NURTURE_PERCENTILE_HIGH = 0.40
NURTURE_MIN_EPISODES = 10
NURTURE_MAX_EPISODES = 100
NURTURE_MAX_PER_GENRE = 3

# ── 순환 스캔 설정: 결국 전체 작품을 다 훑기 위한 저속 배치 ──────────
# 하루에 많이 보려 하지 않고, 대신 "한 번도 안 본 작품"부터 우선순위를 둬서
# 매일 조금씩 커버리지를 넓혀갑니다. 진행 상황은 파일로 저장해 이어서 진행.
ROUND_ROBIN_DAILY_QUOTA = 100
DEEP_CHECK_STATE_PATH = Path("data") / "deep_check_state.json"

# 연재 주기가 이 값(일) 이상이면, 키워드가 안 걸려도 장기휴재 의심으로 표시
HIATUS_CADENCE_DAYS = 60

# ── 트랙 C: 업데이트순 기반 "최근 활동 + 양질" 감지 (API 호출 0회) ──────
# 목록 자체가 order=UPDATE라서, updateRank가 낮을수록 그 장르에서 최근에
# 올라온 작품이라는 뜻. 여기에 별점 조건만 더하면 회차 API를 전혀 안 불러도
# "최근에 활동했고 반응도 괜찮은 작품"을 매일 공짜로 잡아낼 수 있음.
# 다만 "updateRank가 낮다"가 "오늘 업데이트했다"를 100% 보장하진 않음
# (그 장르에 그날 올라온 글이 적으면 며칠 전 것도 상위에 남아있을 수 있음).
FRESH_RANK_THRESHOLD = 10        # 장르 내 업데이트순 상위 10위 이내
FRESH_STAR_PERCENTILE = 0.20     # 장르 내 별점 상위 20% 이내

SPECIAL_KEYWORDS = ["연재공지", "연재 공지", "휴재", "완결", "수상", "후기", "작가의 말", "이벤트"]


# ── 1) 기본 목록 수집 ────────────────────────────────────
def fetch_genre_page(genre: str | None, page: int) -> list[dict]:
    """특정 장르(또는 genre=None이면 '전체' 탭)의 특정 페이지를 가져옵니다."""
    url = (
        ALL_TAB_URL_TEMPLATE.format(page=page)
        if genre is None
        else LIST_URL_TEMPLATE.format(genre=genre, page=page)
    )
    response = requests.get(url, headers=HEADERS, timeout=10)
    response.raise_for_status()
    return response.json().get("list", [])


def collect_snapshot() -> list[dict]:
    """모든 장르(+전체 탭)를 순회하며 오늘 자 스냅샷을 수집합니다.

    목록 자체가 order=UPDATE(최근 업데이트순)라서, 그 안에서 몇 번째로
    나왔는지(updateRank)를 같이 기록해두면 별도 API 호출 없이도
    "최근에 업데이트한 작품"을 알 수 있습니다.
    """
    snapshot: list[dict] = []
    seen_title_ids: set[int] = set()
    rank_counters: dict[str, int] = {}

    genres_to_crawl: list[str | None] = list(GENRES)
    if INCLUDE_ALL_TAB:
        genres_to_crawl.append(None)

    for genre in genres_to_crawl:
        genre_label = genre or "ALL"
        for page in range(1, MAX_PAGES_PER_GENRE + 1):
            try:
                items = fetch_genre_page(genre, page)
            except requests.RequestException as exc:
                print(f"[경고] {genre_label} page={page} 요청 실패: {exc}")
                break

            if not items:
                break

            for item in items:
                title_id = item.get("titleId")
                if title_id in seen_title_ids:
                    continue
                seen_title_ids.add(title_id)
                rank_counters[genre_label] = rank_counters.get(genre_label, 0) + 1
                snapshot.append(
                    {
                        "titleId": title_id,
                        "titleName": item.get("titleName"),
                        "author": item.get("author"),
                        "genre": genre_label,
                        "viewCount": item.get("viewCount"),
                        "starScore": item.get("starScore"),
                        "up": item.get("up"),
                        "bestChallengeLevelUp": item.get("bestChallengeLevelUp"),
                        "webtoonLevelCode": item.get("webtoonLevelCode"),
                        "finish": item.get("finish"),
                        "updateRank": rank_counters[genre_label],  # 이 장르 안에서 최근 업데이트순 몇 위인지
                        # 아래 필드들은 딥체크 대상이 됐을 때만 채워짐 (기본은 비어있음)
                        "signals": [],       # 어떤 트랙이 이 작품을 후보로 뽑았는지
                        "episodeCount": None,
                        "cadenceDays": None,
                        "latestSubtitle": None,
                        "latestDate": None,
                        "keywords": [],
                    }
                )

            print(f"수집: {genre_label} page={page} → {len(items)}건")
            time.sleep(REQUEST_DELAY_SEC)

    return snapshot


def save_snapshot(snapshot: list[dict]) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / f"{date.today().isoformat()}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    return out_path


def load_previous_snapshot() -> tuple[str | None, dict[int, dict] | None]:
    """data/ 폴더에서 오늘 이전 가장 최근 스냅샷 파일을 찾아 불러옵니다."""
    if not OUTPUT_DIR.exists():
        return None, None
    today_str = date.today().isoformat()
    candidates = sorted(
        p for p in OUTPUT_DIR.glob("????-??-??.json") if p.stem < today_str
    )
    if not candidates:
        return None, None
    latest = candidates[-1]
    with latest.open(encoding="utf-8") as f:
        data = json.load(f)
    return latest.stem, {item["titleId"]: item for item in data}


# ── 2) 개별 작품 딥체크 (화수/부제/키워드/연재주기 통합 조회) ────────
def fetch_deep_info(title_id: int) -> dict:
    """작품 하나에 대해 화수·최신 회차 부제·연재 주기·특이 키워드를 한 번에 확인합니다.

    예전에는 트랙마다 다른 API를 따로 불러서(화수만 보는 함수 / 부제까지 보는 함수가
    분리돼 있었음) 즉시확인·육성관찰 후보는 "연재공지" 같은 키워드를 아예 못 봤습니다.
    이제는 어느 트랙에서 오든 이 함수 하나만 거치면 전부 다 채워집니다.
    """
    empty = {
        "episodeCount": None, "cadenceDays": None,
        "latestSubtitle": None, "latestDate": None, "keywords": [],
    }

    first_url = EPISODE_LIST_URL_TEMPLATE.format(title_id=title_id, page=1)
    try:
        res = requests.get(first_url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        first_page = res.json()
    except (requests.RequestException, ValueError):
        return empty

    page_info = first_page.get("pageInfo", {})
    episode_count = page_info.get("totalRows")
    total_pages = page_info.get("totalPages", 1)
    episodes = first_page.get("articleList", [])

    if total_pages and total_pages > 1:
        time.sleep(0.5)
        last_url = EPISODE_LIST_URL_TEMPLATE.format(title_id=title_id, page=total_pages)
        try:
            res = requests.get(last_url, headers=HEADERS, timeout=10)
            res.raise_for_status()
            episodes = res.json().get("articleList", episodes)
        except (requests.RequestException, ValueError):
            pass  # 마지막 페이지 조회 실패 시 1페이지 것으로라도 대체

    if not episodes:
        return {**empty, "episodeCount": episode_count}

    latest = episodes[-1]
    return {
        "episodeCount": episode_count,
        "cadenceDays": compute_cadence_days(episodes),
        "latestSubtitle": latest.get("subtitle"),
        "latestDate": latest.get("serviceDateDescription"),
        "keywords": detect_keywords(latest.get("subtitle")),
    }


def parse_service_date(desc: str | None):
    """'26.09.07' 형식 문자열을 date로 변환합니다."""
    if not desc:
        return None
    try:
        yy, mm, dd = desc.split(".")
        return date(2000 + int(yy), int(mm), int(dd))
    except (ValueError, AttributeError):
        return None


def compute_cadence_days(episodes: list[dict]) -> float | None:
    """최근 회차들의 연재 간격(평균 며칠에 한 번 올라오는지)을 계산합니다."""
    dates = sorted(d for d in (parse_service_date(e.get("serviceDateDescription")) for e in episodes) if d)
    if len(dates) < 2:
        return None
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    return round(sum(gaps) / len(gaps), 1)


def detect_keywords(subtitle: str | None) -> list[str]:
    if not subtitle:
        return []
    normalized = subtitle.replace(" ", "")
    return [kw for kw in SPECIAL_KEYWORDS if kw.replace(" ", "") in normalized]


class DeepInfoCache:
    """같은 작품이 여러 트랙에서 동시에 후보로 뽑혔을 때 중복 조회를 막습니다."""

    def __init__(self) -> None:
        self._cache: dict[int, dict] = {}

    def get(self, title_id: int) -> dict:
        if title_id not in self._cache:
            self._cache[title_id] = fetch_deep_info(title_id)
            time.sleep(REQUEST_DELAY_SEC)
        return self._cache[title_id]

    def checked_ids(self) -> set[int]:
        """오늘 이 캐시를 통해 실제로 딥체크가 이뤄진 titleId 목록."""
        return set(self._cache.keys())


def attach_signal(item: dict, signal: str, extra: dict) -> None:
    """딥체크 결과를 작품 항목 자체에 붙여서, 메인 스냅샷 저장 시 같이 남도록 합니다."""
    if signal not in item["signals"]:
        item["signals"].append(signal)

    common_fields = ("episodeCount", "cadenceDays", "latestSubtitle", "latestDate", "keywords")
    for key in common_fields:
        if extra.get(key) is not None:
            item[key] = extra[key]

    # growthPct1Day, viewsPerEpisode, immediateReason, nurtureReason 등
    # 트랙별 고유 필드는 공통 필드가 아니므로 그대로 추가
    for key, value in extra.items():
        if key not in common_fields:
            item[key] = value

    maybe_flag_hiatus(item)


def maybe_flag_hiatus(item: dict) -> None:
    """연재 간격이 비정상적으로 길면, 키워드에 안 걸려도 장기휴재 의심으로 표시합니다.

    실제로 "감사 인사 + 특별편"처럼 키워드 목록에 없는 제목으로 사실상
    연재를 멈춘 사례가 있었음 — 하지만 그 작품의 연재 주기는 116일로
    비정상적으로 길었음. 텍스트 키워드보다 이 수치 기반 판정이 더 안전함.
    """
    cadence = item.get("cadenceDays")
    if cadence is not None and cadence >= HIATUS_CADENCE_DAYS:
        if "hiatus_suspect" not in item["signals"]:
            item["signals"].append("hiatus_suspect")


# ── 3) 승격/삭제 검증 ────────────────────────────────────
def fetch_title_info(title_id: int) -> dict:
    """titleId로 직접 조회해서 지금 이 순간의 정확한 상태(승격/삭제 등)를 확인합니다."""
    url = INFO_URL_TEMPLATE.format(title_id=title_id)
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
    except requests.RequestException as exc:
        return {"status": "error", "error": str(exc)}

    if res.status_code != 200:
        return {"status": "error", "http_status": res.status_code}

    try:
        data = res.json()
    except ValueError:
        return {"status": "error", "error": "JSON 파싱 실패"}

    return {
        "status": "ok",
        "webtoonLevelCode": data.get("webtoonLevelCode"),
        "finished": data.get("finished"),
    }


def check_promotions(prev_map: dict[int, dict] | None, prev_date: str | None, today_map: dict[int, dict]) -> None:
    """어제 연재중이었는데 오늘 목록에서 사라진 작품만 골라 실제 상태를 검증합니다."""
    if not prev_map:
        print("[승격체크] 비교할 이전 데이터가 없어 스킵합니다.")
        return

    disappeared = [
        tid for tid, item in prev_map.items()
        if tid not in today_map and item.get("finish") is False
    ]
    print(f"[승격체크] {prev_date} 기준 연재중이다가 사라진 작품: {len(disappeared)}개")
    if not disappeared:
        return

    results = []
    for tid in disappeared:
        info = fetch_title_info(tid)
        if info.get("status") == "ok":
            verdict = "PROMOTED" if info.get("webtoonLevelCode") == "WEBTOON" else "STILL_EXISTS_OUT_OF_RANK"
        else:
            verdict = "LIKELY_DELETED_OR_ERROR"

        result = {
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "titleId": tid,
            "titleName": prev_map[tid]["titleName"],
            "last_seen_date": prev_date,
            "verdict": verdict,
            **info,
        }
        results.append(result)
        print(f"  - {prev_map[tid]['titleName']}: {verdict}")
        time.sleep(REQUEST_DELAY_SEC)

    with PROMOTION_LOG_PATH.open("a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[승격체크] 결과 {len(results)}건을 {PROMOTION_LOG_PATH} 에 기록했습니다.")


# ── 4) 성장 신호(참고용) ──────────────────────────────────
def check_rising_signal(today_snapshot: list[dict], prev_map: dict[int, dict] | None, cache: DeepInfoCache) -> None:
    if not prev_map:
        print("[성장신호] 비교할 이전 데이터가 없어 스킵합니다.")
        return

    candidates = []
    for item in today_snapshot:
        prev = prev_map.get(item["titleId"])
        if not prev or not prev.get("viewCount"):
            continue
        growth_pct = (item["viewCount"] - prev["viewCount"]) / prev["viewCount"] * 100
        if item["viewCount"] >= RISING_MIN_VIEW and growth_pct >= RISING_MIN_GROWTH_PCT:
            candidates.append((item, round(growth_pct, 1)))

    candidates.sort(key=lambda x: x[1], reverse=True)
    candidates = candidates[:MAX_RISING_CHECKS_PER_DAY]
    print(f"[성장신호] 전일 대비 조회수 급증 후보: {len(candidates)}개")

    for item, growth_pct in candidates:
        info = cache.get(item["titleId"])
        attach_signal(item, "rising", {**info, "growthPct1Day": growth_pct})
        tag = f" [{'/'.join(info['keywords'])}]" if info["keywords"] else ""
        print(f"  📈 {item['titleName']}: +{growth_pct}%, 연재주기 {info['cadenceDays']}일{tag}")


# ── 5) 트랙 A: 즉시확인(초반 고품질) ──────────────────────────
def check_immediate_candidates(today_snapshot: list[dict], cache: DeepInfoCache) -> None:
    """장르 내 별점 상대 순위로 1차 후보를 뽑고, 화수가 적은 것만 '즉시확인'으로 확정합니다."""
    by_genre: dict[str, list[dict]] = {}
    for item in today_snapshot:
        if item.get("finish") is False and item.get("genre") != "ALL":
            by_genre.setdefault(item["genre"], []).append(item)

    first_pass: list[dict] = []
    for genre, items in by_genre.items():
        items_sorted = sorted(items, key=lambda x: x.get("starScore") or 0, reverse=True)
        cutoff = max(1, int(len(items_sorted) * IMMEDIATE_TOP_PERCENTILE))
        first_pass.extend(items_sorted[:cutoff])

    print(f"[즉시확인] 장르 내 별점 상위 {IMMEDIATE_TOP_PERCENTILE*100:.0f}% 1차 후보: {len(first_pass)}개")

    confirmed = 0
    for item in first_pass:
        info = cache.get(item["titleId"])
        episode_count = info.get("episodeCount")
        if episode_count is None or episode_count > IMMEDIATE_MAX_EPISODES:
            continue
        confirmed += 1
        reason = f"{episode_count}화 만에 장르 내 별점 상위 {IMMEDIATE_TOP_PERCENTILE*100:.0f}% 진입"
        attach_signal(item, "immediate", {**info, "immediateReason": reason})
        tag = f" [{'/'.join(info['keywords'])}]" if info["keywords"] else ""
        print(f"  🔥 즉시확인: {item['titleName']} ({episode_count}화, 별점 {item['starScore']:.2f}){tag}")

    print(f"[즉시확인] 최종 확정: {confirmed}건")


# ── 6) 트랙 B: 육성관찰(화당 조회수) ──────────────────────────
def check_nurture_candidates(today_snapshot: list[dict], cache: DeepInfoCache) -> None:
    """장르 내 별점 상위 5~40% 구간에서, 화수가 10~100인 작품을 화당 조회수로 비교합니다."""
    by_genre: dict[str, list[dict]] = {}
    for item in today_snapshot:
        if (
            item.get("finish") is False
            and item.get("genre") != "ALL"
            and (item.get("viewCount") or 0) >= NURTURE_MIN_VIEW
        ):
            by_genre.setdefault(item["genre"], []).append(item)

    first_pass: list[dict] = []
    for genre, items in by_genre.items():
        items_sorted = sorted(items, key=lambda x: x.get("starScore") or 0, reverse=True)
        n = len(items_sorted)
        lo = int(n * NURTURE_PERCENTILE_LOW)
        hi = max(lo + 1, int(n * NURTURE_PERCENTILE_HIGH))
        band_by_view = sorted(items_sorted[lo:hi], key=lambda x: x.get("viewCount") or 0, reverse=True)
        first_pass.extend(band_by_view[:NURTURE_MAX_PER_GENRE])

    print(f"[육성관찰] 1차 후보(장르별 별점 상위 5~40% 구간, 조회수순 상위 {NURTURE_MAX_PER_GENRE}개씩): {len(first_pass)}개")

    confirmed = []
    for item in first_pass:
        info = cache.get(item["titleId"])
        episode_count = info.get("episodeCount")
        if not episode_count or not (NURTURE_MIN_EPISODES <= episode_count <= NURTURE_MAX_EPISODES):
            continue
        views_per_episode = round(item["viewCount"] / episode_count, 1)
        reason = (
            f"{episode_count}화 · 화당 평균 {views_per_episode:,.0f}회 · "
            "스토리 반응은 있으나 아직 최상위는 아님 — 장기 관찰 권장"
        )
        attach_signal(item, "nurture", {**info, "viewsPerEpisode": views_per_episode, "nurtureReason": reason})
        confirmed.append((item, views_per_episode, info["keywords"]))

    confirmed.sort(key=lambda x: x[1], reverse=True)
    for item, vpe, keywords in confirmed:
        tag = f" [{'/'.join(keywords)}]" if keywords else ""
        print(f"  👁 육성관찰: {item['titleName']} ({item['episodeCount']}화, 화당 {vpe:,.0f}회){tag}")

    print(f"[육성관찰] 최종 확정: {len(confirmed)}건"
          + ("" if not confirmed else " (⚠ 화당 조회수 기준선은 아직 잠정치입니다)"))


# ── 7) 순환 스캔: 결국 전체 작품을 다 훑기 ──────────────────
def load_check_state() -> dict[int, str]:
    """titleId별 '마지막으로 딥체크한 날짜'를 불러옵니다."""
    if not DEEP_CHECK_STATE_PATH.exists():
        return {}
    with DEEP_CHECK_STATE_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)
    return {int(k): v for k, v in raw.items()}


def save_check_state(state: dict[int, str]) -> None:
    DEEP_CHECK_STATE_PATH.parent.mkdir(exist_ok=True)
    with DEEP_CHECK_STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in state.items()}, f, ensure_ascii=False)


def check_round_robin(today_snapshot: list[dict], cache: DeepInfoCache, state: dict[int, str]) -> None:
    """다른 트랙에서 안 걸린 작품들도, 느리더라도 결국 한 번씩은 다 훑습니다.

    '한 번도 확인 안 된 작품'(state에 기록 없음)이 최우선이고, 그다음은
    '가장 오래전에 확인한 작품' 순서입니다. 하루 확인량을 낮게 잡은 대신
    (ROUND_ROBIN_DAILY_QUOTA), 매일 실행되니 며칠~몇 주면 전체를 한 바퀴 돕니다.
    """
    ongoing = [
        item for item in today_snapshot
        if item.get("finish") is False and item.get("genre") != "ALL"
    ]
    already_today = cache.checked_ids()
    remaining = [item for item in ongoing if item["titleId"] not in already_today]

    # 한 번도 확인 안 된 작품(state에 없음)이 먼저 오도록: 빈 문자열이 제일 작음
    remaining.sort(key=lambda item: state.get(item["titleId"], ""))
    batch = remaining[:ROUND_ROBIN_DAILY_QUOTA]

    print(f"[순환스캔] 연재중 {len(ongoing)}개 중 오늘 다른 트랙에서 이미 확인: {len(already_today & {i['titleId'] for i in ongoing})}개")
    print(f"[순환스캔] 이번에 새로 확인: {len(batch)}개 (누적 미확인 {len(remaining)}개 중)")

    hiatus_found = 0
    for item in batch:
        info = cache.get(item["titleId"])
        if not item["signals"]:
            # 다른 트랙이 이미 신호를 붙인 작품이면 값을 덮어쓰지 않음
            for key in ("episodeCount", "cadenceDays", "latestSubtitle", "latestDate", "keywords"):
                if info.get(key) is not None:
                    item[key] = info[key]
        maybe_flag_hiatus(item)
        if "hiatus_suspect" in item["signals"]:
            hiatus_found += 1

    today_str = date.today().isoformat()
    for title_id in cache.checked_ids():
        state[title_id] = today_str

    covered = len(state)
    print(f"[순환스캔] 이번 실행에서 새로 발견한 장기휴재 의심: {hiatus_found}건")
    print(f"[순환스캔] 누적 확인 이력: {covered} / {len(ongoing)}개 작품 "
          f"({covered/len(ongoing)*100:.1f}% 커버리지, 전체 한 바퀴 도는 데 대략 "
          f"{max(1, (len(ongoing)-covered)//max(ROUND_ROBIN_DAILY_QUOTA,1))}일 더 소요 예상)")


# ── 8) 트랙 C: 업데이트순 기반 무료 신호 (API 호출 없음) ──────────────
def check_fresh_updates(today_snapshot: list[dict]) -> None:
    """목록이 이미 order=UPDATE라는 걸 활용해서, 회차 API 없이도
    '최근에 업데이트했고 반응도 괜찮은 작품'을 찾습니다.
    """
    by_genre: dict[str, list[dict]] = {}
    for item in today_snapshot:
        if item.get("finish") is False and item.get("genre") != "ALL":
            by_genre.setdefault(item["genre"], []).append(item)

    found = 0
    for genre, items in by_genre.items():
        star_sorted = sorted(items, key=lambda x: x.get("starScore") or 0, reverse=True)
        cutoff_idx = max(1, int(len(star_sorted) * FRESH_STAR_PERCENTILE))
        star_cutoff = star_sorted[cutoff_idx - 1].get("starScore") or 0

        for item in items:
            if item.get("updateRank", 999) <= FRESH_RANK_THRESHOLD and (item.get("starScore") or 0) >= star_cutoff:
                reason = f"업데이트순 {item['updateRank']}위 · 장르 내 별점 상위 {FRESH_STAR_PERCENTILE*100:.0f}% 이내"
                attach_signal(item, "fresh_update", {"freshReason": reason})
                found += 1

    print(f"[최근업데이트] API 호출 없이 감지한 '최근 활동+양질' 작품: {found}건")


def main() -> None:
    print(f"=== {date.today().isoformat()} 스냅샷 수집 시작 ===")
    snapshot = collect_snapshot()
    today_map = {item["titleId"]: item for item in snapshot}
    prev_date, prev_map = load_previous_snapshot()

    check_promotions(prev_map, prev_date, today_map)
    check_fresh_updates(snapshot)  # API 호출 없음 — 제일 먼저 해도 무방

    cache = DeepInfoCache()  # 같은 작품이 여러 트랙에 겹쳐도 딥체크는 한 번만
    check_rising_signal(snapshot, prev_map, cache)
    check_immediate_candidates(snapshot, cache)
    check_nurture_candidates(snapshot, cache)

    state = load_check_state()
    check_round_robin(snapshot, cache, state)
    save_check_state(state)

    # 딥체크로 보강된 뒤에 최종 저장 — 사이트에서 signals/키워드를 바로 쓸 수 있음
    out_path = save_snapshot(snapshot)
    flagged = sum(1 for item in snapshot if item["signals"])
    print(f"완료: 총 {len(snapshot)}개 작품 (신호 부착 {flagged}개) → {out_path}")


if __name__ == "__main__":
    main()