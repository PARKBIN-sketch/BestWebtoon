"""
lookup_awards.py — 선정작·수상작 제목을 네이버 웹툰에서 검색해서 작품 번호와 관심 수 등을 모아 둡니다.

왜 필요한가
  크롤러는 베스트도전 목록(1,300여 작품)만 봅니다. 포텐업·지상최대공모전 명단 중 그 목록에 없는 작품은
  제목으로 직접 찾아야 관심 수 같은 값을 알 수 있습니다.

입력  data/award_lookup_input.json   {"items": [{"path","when","sub","grade","title",...}]}
출력  data/award_lookup.json         {"version":1,"results":{"<경로>|<시기>|<등급>|<제목>": {...}}}

어떻게 쓰나
  python lookup_awards.py --probe "보이드맨"   # 검색 주소가 먼저 되는지 확인 (결과 모양을 data/award_lookup_probe.json에 저장)
  python lookup_awards.py --limit 10          # 10건만 시험
  python lookup_awards.py                     # 전부 (이어 하기 가능. 25건마다 저장)
  python lookup_awards.py --redo              # 이미 한 항목도 다시

판정 (decision)
  auto    제목이 정확히 같은 작품이 하나뿐이고, 첫 화 날짜가 선정 시기와 맞음
  review  후보가 여럿이거나, 제목이 비슷하기만 하거나, 날짜가 어긋남 → 사람이 확인
  none    후보 없음 (삭제됐거나 제목이 바뀌었거나 검색에 안 잡힘)
  error   검색 자체가 실패

주의: 같은 이름의 다른 작품이 있을 수 있어서 auto도 "추정"입니다. 최종 확정 전에 review 시트와 함께 훑어보세요.
"""
import argparse
import difflib
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scouting_desk_crawler as crawler   # 주소·헤더·요청 간격·작품 정보 조회를 그대로 가져옴

IN_PATH = Path("data") / "award_lookup_input.json"
OUT_PATH = Path("data") / "award_lookup.json"
PROBE_PATH = Path("data") / "award_lookup_probe.json"
SAVE_EVERY = 25
MAX_CANDIDATES = 4
SEARCH_URLS = [                                   # 앞에서부터 시도합니다. 하나라도 후보가 나오면 그것을 씁니다.
    "https://comic.naver.com/api/search/all?keyword={kw}",
    "https://comic.naver.com/api/search/bestChallenge?keyword={kw}&page=1",
]
LATE_MONTHS = 9                                   # 첫 화가 선정 시기보다 이만큼 넘게 늦으면 다른 작품으로 의심


def norm(s: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", unicodedata.normalize("NFKC", s or "").lower())


def variants(title: str) -> set:
    v = {norm(title)}
    base = re.sub(r"\s*[\(\[（][^)\]）]*[\)\]）]\s*", "", title)
    if base != title:
        v.add(norm(base))
    for inner in re.findall(r"[\[\(（]([^)\]）]+)[\)\]）]", title):
        if len(norm(inner)) >= 3:
            v.add(norm(inner))
    m = re.search(r"-([^-]{2,})-$", title)
    if m:
        v.add(norm(m[1]))
    return {x for x in v if x}


def month_index(when: str):
    m = re.match(r"^(\d{4})(?:-(\d{2}))?", when or "")
    if not m:
        return None
    return int(m[1]) * 12 + (int(m[2]) if m[2] else 12)


def first_date_index(desc):
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{2})$", desc or "")
    return (2000 + int(m[1])) * 12 + int(m[2]) if m else None


def collect_candidates(node, out, level_hint=""):
    """검색 응답 어디에 있든 titleId와 titleName을 가진 항목을 모읍니다 (응답 모양이 바뀌어도 견디도록)."""
    if isinstance(node, dict):
        if "titleId" in node and "titleName" in node:
            authors = node.get("author") or node.get("authors") or node.get("displayAuthor") or ""
            if isinstance(authors, list):
                authors = ", ".join(str(a.get("name", a)) if isinstance(a, dict) else str(a) for a in authors)
            out.setdefault(str(node["titleId"]), {
                "titleId": int(node["titleId"]), "titleName": node["titleName"],
                "author": str(authors), "hint": level_hint})
        for k, v in node.items():
            hint = level_hint
            lk = str(k).lower()
            if "bestchallenge" in lk:
                hint = "BEST_CHALLENGE"
            elif "challenge" in lk:
                hint = "CHALLENGE"
            elif "webtoon" in lk:
                hint = "WEBTOON"
            collect_candidates(v, out, hint)
    elif isinstance(node, list):
        for v in node:
            collect_candidates(v, out, level_hint)


def search(keyword: str):
    """(후보 dict, 원본 응답, 오류 메시지)"""
    last_err = None
    raw = None
    for tpl in SEARCH_URLS:
        url = tpl.format(kw=requests.utils.quote(keyword))
        try:
            res = requests.get(url, headers=crawler.HEADERS, timeout=15)
        except requests.RequestException as exc:
            last_err = str(exc)
            continue
        time.sleep(crawler.REQUEST_DELAY_SEC)
        if res.status_code != 200:
            last_err = f"HTTP {res.status_code} ({url})"
            continue
        try:
            raw = res.json()
        except ValueError:
            last_err = f"JSON 아님 ({url})"
            continue
        found = {}
        collect_candidates(raw, found)
        if found:
            return found, raw, None
        last_err = f"후보 없음 ({url})"
    return {}, raw, last_err


def evaluate(item, found):
    qv = variants(item["title"])
    sel = month_index(item.get("when"))
    cands = []
    for cid, c in found.items():
        nt = norm(c["titleName"])
        exact = bool(variants(c["titleName"]) & qv) or nt in qv
        ratio = max((difflib.SequenceMatcher(None, nt, q).ratio() for q in qv), default=0)
        if not exact and ratio < 0.8:
            continue
        cands.append({**c, "exact": exact, "ratio": round(ratio, 2)})
    cands.sort(key=lambda c: (not c["exact"], -c["ratio"]))
    cands = cands[:MAX_CANDIDATES]
    for c in cands:                                   # 후보마다 현재 상태·관심 수·첫 화 날짜를 확인
        info = crawler.fetch_title_info(c["titleId"])
        time.sleep(crawler.REQUEST_DELAY_SEC)
        c["level"] = info.get("webtoonLevelCode") or c.get("hint")
        c["favoriteCount"] = info.get("favoriteCount")
        c["finished"] = info.get("finished")
        deep = crawler.fetch_deep_info(c["titleId"])
        time.sleep(crawler.REQUEST_DELAY_SEC)
        c["firstEpisodeDate"] = deep.get("firstEpisodeDate")
        c["latestDate"] = deep.get("latestDate")
        c["episodeCount"] = deep.get("episodeCount")
        flags = []
        fi = first_date_index(c["firstEpisodeDate"])
        if sel and fi and fi - sel > LATE_MONTHS:
            flags.append(f"첫 화({c['firstEpisodeDate']})가 선정 시기({item.get('when')})보다 {fi - sel}개월 늦음")
        if info.get("status") != "ok":
            flags.append("작품 정보 조회 실패")
        c["flags"] = flags
    exact_ok = [c for c in cands if c["exact"] and not c["flags"]]
    if len(exact_ok) == 1:                            # 제목이 같고 날짜도 맞는 작품이 딱 하나 (날짜가 어긋난 동명 작품은 제외됨)
        decision = "auto"
    elif cands:
        decision = "review"
    else:
        decision = "none"
    return decision, cands


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save(results):
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({"version": 1, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", metavar="제목", help="검색 한 번만 해서 응답 모양을 저장하고 끝냅니다")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--redo", action="store_true")
    args = ap.parse_args()

    if args.probe:
        found, raw, err = search(args.probe)
        PROBE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROBE_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"후보 {len(found)}개, 오류: {err}")
        for c in found.values():
            print(" ", c["titleId"], c["titleName"], c["author"], c["hint"])
        print(f"원본 응답 저장: {PROBE_PATH}")
        return

    items = load_json(IN_PATH, {}).get("items", [])
    results = load_json(OUT_PATH, {}).get("results", {})
    cache = {}                                         # 같은 제목은 한 번만 검색 (포텐업은 같은 제목이 여러 달에 나옴)
    todo = [it for it in items if args.redo or f"{it['path']}|{it['when']}|{it.get('grade','')}|{it['title']}" not in results]
    if args.limit:
        todo = todo[: args.limit]
    print(f"[조회] 입력 {len(items)}건 중 이번에 할 것 {len(todo)}건")

    failures_in_a_row = 0
    for n, it in enumerate(todo, 1):
        key = f"{it['path']}|{it['when']}|{it.get('grade','')}|{it['title']}"
        if it["title"] in cache:
            found, err = cache[it["title"]]
        else:
            found, raw, err = search(it["title"])
            cache[it["title"]] = (found, err)
            if raw is not None and n <= 3 and not found:
                PROBE_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        if err and not found and err.startswith(("HTTP", "JSON")):
            failures_in_a_row += 1
            results[key] = {**it, "decision": "error", "error": err, "candidates": []}
            if failures_in_a_row >= 5:
                save(results)
                sys.exit(f"검색이 5번 연속 실패했습니다. 마지막 오류: {err}\n"
                         f"먼저 python lookup_awards.py --probe \"제목\" 으로 검색 주소와 응답 모양을 확인하세요.")
            continue
        failures_in_a_row = 0
        decision, cands = evaluate(it, found) if found else ("none", [])
        results[key] = {**it, "decision": decision, "candidates": cands}
        print(f"[{n}/{len(todo)}] {decision:6} {it['path']} {it['when']} {it['title']} → "
              f"{', '.join(str(c['titleId']) for c in cands) or '-'}")
        if n % SAVE_EVERY == 0:
            save(results)
    save(results)
    from collections import Counter
    print("[조회] 완료:", dict(Counter(r["decision"] for r in results.values())), "→", OUT_PATH)


if __name__ == "__main__":
    main()
