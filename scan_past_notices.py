"""
scan_past_notices.py — 지난 회차 제목 전체를 훑어서 "공지처럼 보이는 회차"를 찾아 둡니다.

왜 필요한가
  크롤러는 작품의 "최신 회차 제목" 하나만 봅니다. 그래서 공지가 올라온 뒤 새 회차가 올라와 공지가 묻힌 작품
  (예: 여우별잡이)은 최신 회차에 공지가 없다는 이유로 확인 대상에서 빠집니다.
  이 스크립트는 작품마다 모든 회차의 제목을 읽고, 공지 키워드가 들어간 회차를 data/past_notices.json에 기록합니다.
  사이트(스카우팅 데스크)는 이 기록을 읽어서 "지난 회차에서 공지 후보를 발견한 작품"을 따로 모아 보여줍니다.

어떻게 쓰나
  python scan_past_notices.py              # 아직 분류하지 않은 작품 중 아직 안 훑은 작품만 (이어 하기 가능)
  python scan_past_notices.py --limit 20   # 20개만 시험해 보기
  python scan_past_notices.py --all        # 이미 분류한 작품도 포함
  python scan_past_notices.py --rescan     # 이미 훑은 작품도 다시 훑기

  중간에 멈춰도(Ctrl+C, 오류 등) 25개마다 저장하므로 다시 실행하면 이어서 합니다.
  요청 사이에 1초씩 쉬어서 (작품당 회차 30개 = 1요청) 전체에 40분 안팎 걸립니다.

저장하는 것 (data/past_notices.json)
  {"version": 1, "scanned": {"<작품 번호>": {"at": "날짜", "total": 회차 수,
      "hits": [{"no": 회차 번호, "t": 제목, "d": 업로드 날짜, "w": [걸린 키워드]}]}}}
  hits가 비어 있으면 "모든 회차를 훑었지만 공지 키워드가 하나도 없었다"는 뜻입니다.
"""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scouting_desk_crawler as crawler   # 같은 폴더의 크롤러에서 주소·헤더·공지 키워드를 그대로 가져옴

HISTORY_PATH = Path("data") / "history.json"
LABELS_PATH = Path("data") / "labels.json"
OUT_PATH = Path("data") / "past_notices.json"
SAVE_EVERY = 25
MAX_HITS_PER_TITLE = 40          # 한 작품에서 기록할 공지 후보 회차 상한 (제목이 전부 "공지"인 작품 방지)
MAX_CONSECUTIVE_FAILS = 6        # 연속으로 이만큼 실패하면 차단·점검으로 보고 멈춤 (이미 훑은 것은 저장됨)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def labeled_ids() -> set[str]:
    payload = load_json(LABELS_PATH, {})
    labels = payload.get("labels", payload) if isinstance(payload, dict) else {}
    return {str(k) for k, v in labels.items() if isinstance(v, dict) and v.get("status")}


def fetch_page(title_id: str, page: int):
    """회차 목록 한 페이지. 실패하면 3번까지 다시 시도하고, 그래도 안 되면 None."""
    url = crawler.EPISODE_LIST_URL_TEMPLATE.format(title_id=title_id, page=page)
    for attempt in range(3):
        try:
            res = requests.get(url, headers=crawler.HEADERS, timeout=15)
            res.raise_for_status()
            return res.json()
        except (requests.RequestException, ValueError):
            time.sleep(2 * (attempt + 1))
    return None


def scan_title(title_id: str):
    """작품 하나의 모든 회차 제목을 훑음. 실패하면 None, 성공하면 기록 한 건."""
    first = fetch_page(title_id, 1)
    time.sleep(crawler.REQUEST_DELAY_SEC)
    if first is None:
        return None
    info = first.get("pageInfo", {}) or {}
    total_rows = info.get("totalRows") or 0
    total_pages = info.get("totalPages") or 1
    episodes = list(first.get("articleList") or [])
    for page in range(2, total_pages + 1):
        data = fetch_page(title_id, page)
        time.sleep(crawler.REQUEST_DELAY_SEC)
        if data is None:
            return None               # 중간에 실패하면 불완전한 기록을 남기지 않음 (다음에 다시 시도)
        episodes.extend(data.get("articleList") or [])

    hits = []
    for ep in episodes:
        subtitle = ep.get("subtitle") or ""
        compact = subtitle.replace(" ", "")
        words = [w for w in crawler.NOTICE_KEYWORDS if w in compact]
        if words:
            hits.append({"no": ep.get("no"), "t": subtitle, "d": ep.get("serviceDateDescription"), "w": words})
    return {"at": date.today().isoformat(), "total": total_rows or len(episodes), "hits": hits[:MAX_HITS_PER_TITLE],
            "hitCount": len(hits)}


def save(store: dict) -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(store, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="지난 회차 제목에서 공지 후보를 찾아 data/past_notices.json에 저장")
    parser.add_argument("--limit", type=int, default=0, help="이번에 훑을 작품 수 상한 (시험용)")
    parser.add_argument("--all", action="store_true", help="이미 분류한 작품도 포함")
    parser.add_argument("--rescan", action="store_true", help="이미 훑은 작품도 다시 훑기")
    args = parser.parse_args()

    history = load_json(HISTORY_PATH, {})
    if not history:
        print(f"[훑기] {HISTORY_PATH}가 없습니다 — 크롤러가 먼저 실행돼야 합니다.")
        return
    store = load_json(OUT_PATH, {})
    if not isinstance(store, dict) or "scanned" not in store:
        store = {"version": 1, "keywords": list(crawler.NOTICE_KEYWORDS), "scanned": {}}
    store["keywords"] = list(crawler.NOTICE_KEYWORDS)

    skip = set() if args.all else labeled_ids()
    todo = [k for k in history if k not in skip and (args.rescan or k not in store["scanned"])]
    if args.limit:
        todo = todo[: args.limit]
    print(f"[훑기] 대상 {len(todo)}개 (전체 {len(history)}개 중 분류함 {len(skip & set(history))}개, 이미 훑음 {len(store['scanned'])}개)")

    done = fails = 0
    try:
        for i, title_id in enumerate(todo, 1):
            rec = scan_title(title_id)
            if rec is None:
                fails += 1
                print(f"  [{i}/{len(todo)}] {title_id} 실패 (연속 {fails})")
                if fails >= MAX_CONSECUTIVE_FAILS:
                    print("[훑기] 연속 실패가 많아 중단합니다. 잠시 뒤 다시 실행하면 이어서 합니다.")
                    break
                continue
            fails = 0
            store["scanned"][title_id] = rec
            done += 1
            if done % SAVE_EVERY == 0:
                save(store)
                print(f"  [{i}/{len(todo)}] 저장 — 훑음 {len(store['scanned'])}개")
    except KeyboardInterrupt:
        print("\n[훑기] 사용자가 멈췄습니다.")
    finally:
        save(store)

    with_hits = sum(1 for r in store["scanned"].values() if r.get("hits"))
    print(f"[훑기] 이번에 {done}개 완료 · 누적 {len(store['scanned'])}개 중 공지 후보가 있는 작품 {with_hits}개 → {OUT_PATH}")


if __name__ == "__main__":
    main()
