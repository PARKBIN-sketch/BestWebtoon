"""
스카우팅 데스크 - 베스트도전 일일 스냅샷 수집기

사용법:
    python scouting_desk_crawler.py

동작:
    1. 장르별 베스트도전 목록을 순회하며 조회수/별점/급상승 여부를 수집
    2. 요청 사이 1초씩 대기 (서버 부담 최소화)
    3. 결과를 날짜별 JSON 파일로 저장 (data/2026-09-04.json 같은 형태)
    4. 매일 같은 시간에 cron/작업 스케줄러로 이 스크립트를 실행하면
       날짜별 파일이 쌓여서 시계열 분석이 가능해짐

✅ 확인된 API:
    https://comic.naver.com/api/bestChallenge/list?genre={genre}&order=UPDATE&page={page}
    - 페이지당 30개 항목 (pageSize=30)
    - order 파라미터는 UPDATE 외에도 다른 정렬값이 있을 수 있음 (미확인)

⚠️ 아직 확인 필요:
    - GENRES 목록에 있는 코드값 중 FANTASY 외에는 추정치입니다.
      베스트도전 페이지에서 각 장르 탭을 클릭했을 때 URL의 genre= 값을
      직접 확인해서 정확한 코드로 교체하세요.
    - 이 장르 하나에만 totalPages=49 (약 1,456개 작품)가 있었습니다.
      MAX_PAGES_PER_GENRE를 늘리면 전체를 수집할 수 있지만 그만큼
      요청 수가 늘어나니, 처음엔 낮게 설정해 테스트하는 걸 권장합니다.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import requests

# ── 설정 ──────────────────────────────────────────────
LIST_URL_TEMPLATE = (
    "https://comic.naver.com/api/bestChallenge/list"
    "?genre={genre}&order=UPDATE&page={page}"
)
PAGE_SIZE = 30  # 확인된 값

# 확인된 전체 장르 코드 (사용자가 브라우저에서 직접 확인함, 2026-09-04 기준)
GENRES = [
    "PURE",         # 로맨스
    "FANTASY",      # 판타지
    "ACTION",       # 액션
    "DAILY",        # 일상
    "THRILL",       # 스릴러
    "COMIC",        # 개그
    "HISTORICAL",   # 무협/사극
    "DRAMA",        # 드라마
    "SENSIBILITY",  # 감성
    "SPORTS",       # 스포츠
]

# 장르 필터 없이 "전체" 탭도 수집하려면 True로 설정
# (전체 탭은 URL에 genre 파라미터가 없어, 별도 처리 필요)
INCLUDE_ALL_TAB = True
ALL_TAB_URL_TEMPLATE = "https://comic.naver.com/api/bestChallenge/list?order=UPDATE&page={page}"

MAX_PAGES_PER_GENRE = 5  # 장르당 최대 몇 페이지까지 수집할지 (전체는 최대 49페이지)
REQUEST_DELAY_SEC = 1.0  # 요청 사이 대기 시간

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    ),
    "Referer": "https://comic.naver.com/webtoon/bestChallenge",
    "Accept": "application/json",
}

OUTPUT_DIR = Path("data")


# ── 수집 로직 ──────────────────────────────────────────
def fetch_genre_page(genre: str | None, page: int) -> list[dict]:
    """특정 장르(또는 genre=None이면 '전체' 탭)의 특정 페이지를 가져옵니다."""
    if genre is None:
        url = ALL_TAB_URL_TEMPLATE.format(page=page)
    else:
        url = LIST_URL_TEMPLATE.format(genre=genre, page=page)
    response = requests.get(url, headers=HEADERS, timeout=10)
    response.raise_for_status()
    data = response.json()
    return data.get("list", [])


def collect_snapshot() -> list[dict]:
    """모든 장르(+전체 탭)를 순회하며 오늘 자 스냅샷을 수집합니다."""
    snapshot: list[dict] = []
    seen_title_ids: set[int] = set()

    genres_to_crawl: list[str | None] = list(GENRES)
    if INCLUDE_ALL_TAB:
        genres_to_crawl.append(None)  # None = 전체 탭

    for genre in genres_to_crawl:
        genre_label = genre or "ALL"
        for page in range(1, MAX_PAGES_PER_GENRE + 1):
            try:
                items = fetch_genre_page(genre, page)
            except requests.RequestException as exc:
                print(f"[경고] {genre_label} page={page} 요청 실패: {exc}")
                break

            if not items:
                # 더 이상 데이터가 없으면 다음 장르로
                break

            for item in items:
                title_id = item.get("titleId")
                if title_id in seen_title_ids:
                    continue  # 여러 장르에 중복 등록된 작품 방지
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
                        # 도전만화 -> 베스트도전으로 막 승격된 신인 신호로 추정.
                        # 실제 의미는 화면에서 뱃지/표시를 눈으로 대조해 검증 필요.
                        "bestChallengeLevelUp": item.get("bestChallengeLevelUp"),
                        "webtoonLevelCode": item.get("webtoonLevelCode"),
                        "finish": item.get("finish"),
                    }
                )

            print(f"수집: {genre_label} page={page} → {len(items)}건")
            time.sleep(REQUEST_DELAY_SEC)

    return snapshot


def save_snapshot(snapshot: list[dict]) -> Path:
    """오늘 날짜 파일로 저장합니다."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / f"{date.today().isoformat()}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    return out_path


def main() -> None:
    print(f"=== {date.today().isoformat()} 스냅샷 수집 시작 ===")
    snapshot = collect_snapshot()
    out_path = save_snapshot(snapshot)
    print(f"완료: 총 {len(snapshot)}개 작품 → {out_path}")


if __name__ == "__main__":
    main()
