"""
스카우팅 데스크 - 베스트도전 일일 스냅샷 수집기 + 승격 검증 + 연재주기/공지 감지

사용법:
    python scouting_desk_crawler.py

동작 (하루 1회 실행 기준):
    1. 장르별 베스트도전 목록을 순회하며 조회수/별점/급상승 여부를 수집
    2. 오늘 스냅샷을 data/YYYY-MM-DD.json 으로 저장
    3. 어제 스냅샷과 비교해서, "연재중이었는데 오늘 목록에서 사라진 작품"을
       titleId로 직접 재조회해서 정식연재 승격/삭제/기타 여부를 검증하고
       data/promotion_log.jsonl 에 누적 기록
    4. 오늘 조회수가 유의미하게 늘어난 후보들만 추려서, 최근 회차 부제/날짜를
       가져와 "연재공지/휴재/완결" 같은 키워드와 연재 주기(며칠 간격인지)를
       확인하고 data/deep_checks/YYYY-MM-DD.json 에 저장
    5. (트랙 A) 성장률과 무관하게, "화수는 적은데 이미 장르 내 별점이 최상위권"인
       초반 고품질 작품을 별도로 찾아 data/immediate_candidates/YYYY-MM-DD.json 에 저장
       — 이런 작품은 타사가 먼저 컨택할 수 있어 성장 추이를 기다릴 여유가 없음
    6. (트랙 B) "화수는 어느 정도 쌓였고 반응도 나쁘지 않은데 아직 최상위는 아닌"
       작품을 화당 평균 조회수 기준으로 찾아 data/nurture_candidates/YYYY-MM-DD.json 에 저장
       — 오래 연재해서 조회수만 큰 작품과 구분하기 위해 화수 구간(10~100화)으로 제한

⚠️ 중요한 교훈 (실제로 겪은 실패 사례):
    "베스트도전 목록에서 사라짐 = 정식연재 승격"이라고 가정했다가 틀렸습니다.
    실제로는 완결된 지 오래된 작품이 order=UPDATE 정렬에서 자연스럽게 밀려나
    사라지는 경우가 있었고, 작가가 작품을 삭제한 경우도 있었습니다.
    그래서 이번 버전은:
      - finish(연재중) 작품만 승격 후보로 취급
      - "사라짐"을 발견하면 반드시 titleId로 직접 재조회해서
        webtoonLevelCode가 실제로 WEBTOON이 됐는지 확인 (검증 없이 단정하지 않음)

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

# ── 설정 ──────────────────────────────────────────────
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

# 딥체크(회차 부제/연재주기 확인)는 API 호출이 많아지므로 하루 최대 이 개수까지만
MAX_DEEP_CHECKS_PER_DAY = 20
# 딥체크 대상 최소 기준: 이 조회수 이상 + 전일 대비 이 %이상 늘어난 작품만
DEEP_CHECK_MIN_VIEW = 5000
DEEP_CHECK_MIN_GROWTH_PCT = 5.0

# ── 트랙 A 설정: 즉시 확인(초반 고품질) 감지 ──────────────────
# 절대 별점 기준은 함정이 있음 — 베스트도전 별점 자체가 전반적으로 9점대에
# 몰려있어서(투표자가 이미 애정하는 소수 독자 위주), 9.5+ 조건만으로는
# 장르당 수백 개가 걸려버림. 그래서 "장르 내 상대 순위(상위 몇 %)"로 좁힘.
IMMEDIATE_TOP_PERCENTILE = 0.02  # 장르별 별점 상위 2%만 1차 후보로
IMMEDIATE_MAX_EPISODES = 15      # 이 화수 이하일 때만 "초반"으로 인정
IMMEDIATE_OUTPUT_DIR = Path("data") / "immediate_candidates"

# ── 트랙 B 설정: 화당 조회수 기반 육성 관찰 대상 ──────────────
# "스토리는 좋은데 아직 그림/연출이 안 따라온" 작품을 정량 데이터만으로
# 완벽히 구분할 수는 없음 (스토리/그림을 나눠 평가하는 필드가 없음).
# 대신 이렇게 근사함:
#   - 이미 최상위(트랙 A)는 제외
#   - 너무 초반(트랙 A가 담당)도, 너무 오래돼서 덩치만 큰 것도 제외
#   - "화당 조회수"(viewCount / episodeCount)로 순수 화제성만 비교
#
# ⚠️ 화당 조회수의 "정상 범위"를 판단할 과거 데이터가 아직 없음
# (episodeCount를 지금까지 수집한 적이 없어서). 그래서 지금은
# episodeCount 구간(10~100화)으로만 1차 필터링하고, 결과를 로그로
# 몇 주 쌓은 뒤 장르별 화당 조회수 중앙값을 실측해서 기준을 다시 잡아야 함.
NURTURE_MIN_VIEW = 5000          # 최소 조회수(소표본 함정 방지, 트랙 A와 동일 기준 재사용)
NURTURE_PERCENTILE_LOW = 0.05    # 장르 내 별점 상위 5%~40% 구간만 대상
NURTURE_PERCENTILE_HIGH = 0.40   # (상위 5% 이내는 이미 트랙 A가 담당하므로 제외)
NURTURE_MIN_EPISODES = 10        # 이보다 적으면 아직 판단하기엔 이름 (트랙 A 영역)
NURTURE_MAX_EPISODES = 100       # 이보다 많으면 "오래돼서 덩치만 큼" 함정 가능성 높음
NURTURE_MAX_PER_GENRE = 3        # 장르당 화수 조회 API를 몇 개까지만 확인할지 (호출량 제한)
NURTURE_OUTPUT_DIR = Path("data") / "nurture_candidates"

SPECIAL_KEYWORDS = ["연재공지", "연재 공지", "휴재", "완결", "수상", "후기", "작가의 말", "이벤트"]

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
DEEP_CHECK_DIR = OUTPUT_DIR / "deep_checks"


# ── 1) 기본 목록 수집 (기존 로직) ──────────────────────────
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
    """모든 장르(+전체 탭)를 순회하며 오늘 자 스냅샷을 수집합니다."""
    snapshot: list[dict] = []
    seen_title_ids: set[int] = set()

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


# ── 2) 개별 작품 상태 재확인 (승격/삭제 검증) ──────────────────
def fetch_title_info(title_id: int) -> dict:
    """titleId로 직접 조회해서 지금 이 순간의 정확한 상태를 확인합니다.

    '목록에서 사라짐'만으로는 승격인지 삭제인지 완결작 순위하락인지
    구분할 수 없다는 게 실제로 확인됐기 때문에, 반드시 이 단계를 거칩니다.
    """
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


def check_promotions(today_map: dict[int, dict]) -> None:
    """어제 연재중이었는데 오늘 목록에서 사라진 작품만 골라 실제 상태를 검증합니다."""
    prev_date, prev_map = load_previous_snapshot()
    if not prev_map:
        print("[승격체크] 비교할 이전 데이터가 없어 스킵합니다.")
        return

    disappeared = [
        tid
        for tid, item in prev_map.items()
        if tid not in today_map and item.get("finish") is False
    ]
    print(f"[승격체크] {prev_date} 기준 연재중이다가 사라진 작품: {len(disappeared)}개")

    if not disappeared:
        return

    results = []
    for tid in disappeared:
        info = fetch_title_info(tid)
        if info.get("status") == "ok":
            verdict = (
                "PROMOTED"
                if info.get("webtoonLevelCode") == "WEBTOON"
                else "STILL_EXISTS_OUT_OF_RANK"  # 승격은 아니고 순위 밖으로 밀려남
            )
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


# ── 3) 연재 주기 / 공지·휴재 키워드 딥체크 ──────────────────
def parse_service_date(desc: str | None) -> date | None:
    """'26.09.07' 형식 문자열을 date로 변환합니다."""
    if not desc:
        return None
    try:
        yy, mm, dd = desc.split(".")
        return date(2000 + int(yy), int(mm), int(dd))
    except (ValueError, AttributeError):
        return None


def detect_keywords(subtitle: str | None) -> list[str]:
    if not subtitle:
        return []
    normalized = subtitle.replace(" ", "")
    return [kw for kw in SPECIAL_KEYWORDS if kw.replace(" ", "") in normalized]


def fetch_recent_episodes(title_id: int) -> list[dict]:
    """가장 최근 회차 목록(마지막 페이지)만 가져옵니다. 요청 2번으로 제한."""
    first_url = EPISODE_LIST_URL_TEMPLATE.format(title_id=title_id, page=1)
    try:
        res = requests.get(first_url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        first_page = res.json()
    except requests.RequestException:
        return []

    total_pages = first_page.get("pageInfo", {}).get("totalPages", 1)
    if total_pages <= 1:
        return first_page.get("articleList", [])

    time.sleep(0.5)
    last_url = EPISODE_LIST_URL_TEMPLATE.format(title_id=title_id, page=total_pages)
    try:
        res = requests.get(last_url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        return res.json().get("articleList", [])
    except requests.RequestException:
        return first_page.get("articleList", [])


def compute_cadence_days(episodes: list[dict]) -> float | None:
    """최근 회차들의 연재 간격(평균 며칠에 한 번 올라오는지)을 계산합니다."""
    dates = [parse_service_date(e.get("serviceDateDescription")) for e in episodes]
    dates = sorted(d for d in dates if d)
    if len(dates) < 2:
        return None
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    return round(sum(gaps) / len(gaps), 1)


def deep_check_title(title_id: int) -> dict:
    episodes = fetch_recent_episodes(title_id)
    if not episodes:
        return {"cadence_days": None, "latest_subtitle": None, "latest_date": None, "keywords": []}

    latest = episodes[-1]
    return {
        "cadence_days": compute_cadence_days(episodes),
        "latest_subtitle": latest.get("subtitle"),
        "latest_date": latest.get("serviceDateDescription"),
        "keywords": detect_keywords(latest.get("subtitle")),
    }


def check_rising_candidates(today_snapshot: list[dict]) -> None:
    """오늘 눈에 띄게 성장한 후보만 골라 회차 부제/연재주기까지 확인합니다."""
    prev_date, prev_map = load_previous_snapshot()
    if not prev_map:
        print("[딥체크] 비교할 이전 데이터가 없어 스킵합니다.")
        return

    candidates = []
    for item in today_snapshot:
        prev = prev_map.get(item["titleId"])
        if not prev or not prev.get("viewCount"):
            continue
        growth_pct = (item["viewCount"] - prev["viewCount"]) / prev["viewCount"] * 100
        if item["viewCount"] >= DEEP_CHECK_MIN_VIEW and growth_pct >= DEEP_CHECK_MIN_GROWTH_PCT:
            candidates.append({**item, "growth_pct_1day": round(growth_pct, 1)})

    candidates.sort(key=lambda x: x["growth_pct_1day"], reverse=True)
    candidates = candidates[:MAX_DEEP_CHECKS_PER_DAY]
    print(f"[딥체크] 정밀 확인 대상 {len(candidates)}개 (하루 최대 {MAX_DEEP_CHECKS_PER_DAY}개 제한)")

    if not candidates:
        return

    results = []
    for item in candidates:
        info = deep_check_title(item["titleId"])
        results.append({**item, **info})
        tag = f" [{'/'.join(info['keywords'])}]" if info["keywords"] else ""
        print(f"  - {item['titleName']}: +{item['growth_pct_1day']}%, 연재주기 {info['cadence_days']}일{tag}")
        time.sleep(REQUEST_DELAY_SEC)

    DEEP_CHECK_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DEEP_CHECK_DIR / f"{date.today().isoformat()}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"[딥체크] 결과를 {out_path} 에 저장했습니다.")


def get_episode_count(title_id: int) -> int | None:
    """작품의 전체 화수를 가볍게 확인합니다 (1회 호출, 1페이지 pageInfo만 사용)."""
    url = EPISODE_LIST_URL_TEMPLATE.format(title_id=title_id, page=1)
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        data = res.json()
    except (requests.RequestException, ValueError):
        return None
    return data.get("pageInfo", {}).get("totalRows")


def check_immediate_candidates(today_snapshot: list[dict]) -> None:
    """트랙 A: '연재 화수는 적은데 이미 반응이 매우 좋은' 작품을 즉시 확인 대상으로 뽑습니다.

    성장률(전일 대비 %) 기준이 아니라, 장르 내 별점 상대 순위로 1차 후보를 뽑는 이유:
    베스트도전 별점은 절대값 기준으로 보면 전반적으로 9점대에 쏠려있어서
    (아직 안 나갈 만큼 훌륭한 작품이 아니어도 소수의 애정 독자 위주로 투표하다 보니
    9.5+ 조건만으로는 장르당 수백 개가 걸려버림) 상대 순위가 훨씬 분별력 있음.
    """
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

    results = []
    for item in first_pass:
        episode_count = get_episode_count(item["titleId"])
        time.sleep(REQUEST_DELAY_SEC)
        if episode_count is None:
            continue
        if episode_count <= IMMEDIATE_MAX_EPISODES:
            result = {
                "checked_at": datetime.now().isoformat(timespec="seconds"),
                "titleId": item["titleId"],
                "titleName": item["titleName"],
                "genre": item["genre"],
                "starScore": item["starScore"],
                "viewCount": item["viewCount"],
                "episodeCount": episode_count,
                "reason": f"{episode_count}화 만에 장르 내 별점 상위 {IMMEDIATE_TOP_PERCENTILE*100:.0f}% 진입",
            }
            results.append(result)
            print(f"  🔥 즉시 확인: {item['titleName']} ({episode_count}화, 별점 {item['starScore']:.2f})")

    if results:
        IMMEDIATE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = IMMEDIATE_OUTPUT_DIR / f"{date.today().isoformat()}.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[즉시확인] {len(results)}건을 {out_path} 에 저장했습니다.")
    else:
        print("[즉시확인] 오늘은 조건에 맞는 초반 고품질 후보가 없었습니다.")


def check_nurture_candidates(today_snapshot: list[dict]) -> None:
    """트랙 B: '스토리 잠재력은 있어 보이는데 아직 안 터진' 작품을 장기 관찰 대상으로 뽑습니다.

    핵심은 "오래 연재해서 조회수만 큰" 함정을 피하는 것 — 그래서 화수 구간을
    10~100화로 제한하고, 최종적으로는 화당 조회수(총 조회수를 화수로 나눈 값)로
    순수 화제성만 비교합니다.
    """
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
        band = items_sorted[lo:hi]  # 상위 5%~40% 구간 (이미 최상위는 트랙 A가 담당)
        band_by_view = sorted(band, key=lambda x: x.get("viewCount") or 0, reverse=True)
        first_pass.extend(band_by_view[:NURTURE_MAX_PER_GENRE])

    print(f"[육성관찰] 1차 후보(장르별 별점 상위 5~40% 구간, 조회수순 상위 {NURTURE_MAX_PER_GENRE}개씩): {len(first_pass)}개")

    results = []
    for item in first_pass:
        episode_count = get_episode_count(item["titleId"])
        time.sleep(REQUEST_DELAY_SEC)
        if not episode_count or not (NURTURE_MIN_EPISODES <= episode_count <= NURTURE_MAX_EPISODES):
            continue  # 너무 초반이거나(트랙 A 영역) 너무 오래됨(덩치만 큰 함정)

        per_episode_views = round(item["viewCount"] / episode_count, 1)
        results.append(
            {
                "checked_at": datetime.now().isoformat(timespec="seconds"),
                "titleId": item["titleId"],
                "titleName": item["titleName"],
                "genre": item["genre"],
                "starScore": item["starScore"],
                "viewCount": item["viewCount"],
                "episodeCount": episode_count,
                "viewsPerEpisode": per_episode_views,
                "reason": (
                    f"{episode_count}화 · 화당 평균 {per_episode_views:,.0f}회 · "
                    "스토리 반응은 있으나 아직 최상위는 아님 — 장기 관찰 권장"
                ),
            }
        )

    # 화당 조회수 기준 정렬 (같은 조회수라도 화수가 적은데 효율 좋은 작품이 위로)
    results.sort(key=lambda x: x["viewsPerEpisode"], reverse=True)

    for r in results:
        print(f"  👁 육성 관찰: {r['titleName']} ({r['episodeCount']}화, 화당 {r['viewsPerEpisode']:,.0f}회)")

    if results:
        NURTURE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = NURTURE_OUTPUT_DIR / f"{date.today().isoformat()}.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[육성관찰] {len(results)}건을 {out_path} 에 저장했습니다.")
        print("[육성관찰] ⚠ 화당 조회수 기준선은 아직 실측 데이터가 없어 잠정치입니다. "
              "몇 주치 로그가 쌓이면 장르별 중앙값으로 기준을 다시 잡으세요.")
    else:
        print("[육성관찰] 오늘은 조건에 맞는 후보가 없었습니다.")


def main() -> None:
    print(f"=== {date.today().isoformat()} 스냅샷 수집 시작 ===")
    snapshot = collect_snapshot()
    out_path = save_snapshot(snapshot)
    print(f"완료: 총 {len(snapshot)}개 작품 → {out_path}")

    today_map = {item["titleId"]: item for item in snapshot}

    check_promotions(today_map)
    check_rising_candidates(snapshot)
    check_immediate_candidates(snapshot)
    check_nurture_candidates(snapshot)


if __name__ == "__main__":
    main()
    