import json, pathlib, sys

run = sys.argv[1] if len(sys.argv) > 1 else sorted(pathlib.Path("captures").glob("fixed_*"))[-1].as_posix()
p = pathlib.Path(run) / "log.jsonl"
rows = []
for line in p.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    rows.append(json.loads(line))


def sec(s):
    h, m, x = s.split(":")
    return int(h) * 3600 + int(m) * 60 + int(x)


t0 = sec(rows[0]["t"])
print(f"log: {p}")
print("== 分段 ==")
marks = []
for r in rows:
    n = r.get("note", "")
    if any(k in n for k in ("傳送", "開始採集", "拿珍珠", "輪", "收工")):
        marks.append((sec(r["t"]) - t0, n))
for t, n in marks:
    print(f"  t+{t:5.0f}s  {n}")

print("\n== 珍珠 ==")
for r in rows:
    if "珍珠" in r.get("note", ""):
        print(f"  t+{sec(r['t']) - t0:5.0f}s  {r['note']}")

print(f"\n總長 {sec(rows[-1]['t']) - t0}s")

# 區段耗時
print("\n== 各區耗時 ==")
zone_start = None
zone_name = None
for t, n in marks:
    if "傳送" in n:
        if zone_name and zone_start is not None:
            print(f"  {zone_name}: {t - zone_start}s")
        zone_name = n.split("傳送 ")[-1]
        zone_start = t
if zone_name and zone_start is not None:
    end = marks[-1][0]
    print(f"  {zone_name}: {end - zone_start}s（到收工）")
