"""
make_reference_cases.py — 조사 목록(텍스트)에서 분석 기준 데이터(data/reference_cases.json)를 만드는 일회성 스크립트

사용법 (저장소 루트에서, 한 번만):
    python make_reference_cases.py 조사목록.txt

조사 목록의 각 줄은 "작품명, 링크, 장르, 뱃지, 공지 제목, 공지 사유, 화수 날짜 조회수…, 관심 수" 형식입니다.
여기서는 작품 번호(링크의 titleId), 뱃지 칸, 맨 끝의 관심 수만 뽑습니다.
뱃지 칸 값으로 작품을 이렇게 나눕니다 (분석에서는 정식연재와 없음만 비교에 사용):
    official : 정식연재 / 정식 연재
    none     : 없음
    award    : 수상작 / 수상
    ended    : 완결
    blank    : 뱃지 칸이 비어 있음
    other    : 그 밖 (뱃지 칸 형식이 밀려 있어 뱃지로 분류하지 못한 작품)
같은 작품 번호가 두 번 나오면 먼저 나온 줄만 씁니다.
"""
import json
import re
import sys
from pathlib import Path

OUT_PATH = Path("data") / "reference_cases.json"
GROUPS = {
    "정식연재": "official", "정식 연재": "official",
    "없음": "none",
    "수상작": "award", "수상": "award",
    "완결": "ended",
    "": "blank",
}


def parse_line(line: str):
    m = re.search(r"titleId=(\d+)", line)
    if not m:
        return None
    parts = [p.strip() for p in line.split(",")]
    url_idx = next((k for k, p in enumerate(parts) if "titleId=" in p), None)
    if url_idx is None:
        return None
    badge = parts[url_idx + 2] if len(parts) > url_idx + 2 else ""
    favorite = None
    last = parts[-1].replace(" ", "")
    if re.fullmatch(r"\d+", last):
        favorite = int(last)
    return {
        "titleId": int(m.group(1)),
        "titleName": ", ".join(parts[:url_idx]).strip(),
        "badge": badge,
        "group": GROUPS.get(badge, "other"),
        "favorite": favorite,
    }


def main() -> None:
    if len(sys.argv) < 2:
        print("사용법: python make_reference_cases.py 조사목록.txt")
        return
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    cases, seen = [], set()
    for line in text.splitlines():
        row = parse_line(line)
        if row is None or row["titleId"] in seen:
            continue
        seen.add(row["titleId"])
        cases.append(row)
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps({"source": Path(sys.argv[1]).name, "cases": cases}, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = {}
    for c in cases:
        counts[c["group"]] = counts.get(c["group"], 0) + 1
    print(f"기준 데이터 {len(cases)}개 저장 → {OUT_PATH}  {counts}")


if __name__ == "__main__":
    main()
