"""Read quiescent native storage separately from live source re-observation.

No repair, schema creation or network I/O. Every comparison remains exact; raw
source heads/observations are evidence for diagnosing a changed persisted row.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

FIELDS=("open","high","low","close","volume")
IDENTITY=("exchange","market_type","provider_id","venue","asset_class","symbol","interval",
    "series_variant","price_adjustment","session_variant","volume_semantics")


def inspect_storage(database,quality):
    database=Path(database).resolve()
    report={"database":str(database),"readOnly":True,"cells":[],"mismatches":[]}
    with sqlite3.connect(database.as_uri()+"?mode=ro",uri=True) as conn:
        conn.row_factory=sqlite3.Row
        conn.execute("PRAGMA query_only=ON");conn.execute("BEGIN")
        tables={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for cell in quality:
            session=cell["session"];exchange=session["exchange"]
            identity=(exchange,session["marketType"],session.get("providerId",exchange),session.get("venue",exchange),
                session.get("assetClass","crypto"),session["symbol"],session["interval"],session.get("seriesVariant","native"),
                session.get("priceAdjustment","raw"),session.get("sessionVariant","continuous"),session.get("volumeSemantics","base_asset"))
            where=" AND ".join(name+"=?" for name in IDENTITY)
            bounds=(cell["first"]*1000,cell["last"]*1000)
            rows=[dict(row) for row in conn.execute("SELECT * FROM klines WHERE "+where+" AND open_time BETWEEN ? AND ? ORDER BY open_time",(*identity,*bounds))]
            indexed={row["open_time"]//1000:row for row in rows}
            for expected in cell["rows"]:
                actual=indexed.get(expected["time"])
                for field in FIELDS:
                    if actual is None or actual[field]!=expected[field]:
                        report["mismatches"].append({"cellId":cell["cellId"],"time":expected["time"],"field":field,
                            "saved":expected[field],"disk":None if actual is None else actual[field]})
            evidence={"cellId":cell["cellId"],"identity":dict(zip(IDENTITY,identity)),"first":cell["first"],"last":cell["last"],"rows":rows}
            if "kline_source_heads" in tables and "kline_source_observations" in tables:
                # Custom Binance seconds also retain their actual 1s source
                # context, without treating a derived row as a native candle.
                source_interval="1s" if exchange=="binance" and session["interval"].endswith("s") else session["interval"]
                key=json.dumps([exchange,session["marketType"],session["symbol"],source_interval],separators=(",",":"))
                through=bounds[1]+(int(session["interval"][:-1])*1000-1 if session["interval"].endswith("s") else 0)
                evidence["sourceSeries"]=key
                evidence["sourceHeads"]=[dict(row) for row in conn.execute("SELECT * FROM kline_source_heads WHERE series=? AND open_time BETWEEN ? AND ? ORDER BY open_time",(key,bounds[0],through))]
                evidence["sourceObservations"]=[dict(row) for row in conn.execute("SELECT * FROM kline_source_observations WHERE series=? AND open_time BETWEEN ? AND ? ORDER BY id",(key,bounds[0],through))]
            report["cells"].append(evidence)
        conn.execute("ROLLBACK")
    report["matchesSaved"]=not report["mismatches"]
    report["canonicalSHA256"]=hashlib.sha256(json.dumps([cell["rows"] for cell in report["cells"]],sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--database",required=True);parser.add_argument("--quality",required=True);parser.add_argument("--output",required=True)
    args=parser.parse_args();output=Path(args.output)
    if output.exists():raise RuntimeError("Preserve an existing persistence checkpoint; use a new output path")
    report=inspect_storage(args.database,json.loads(Path(args.quality).read_text()))
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({key:report[key] for key in ("readOnly","matchesSaved","canonicalSHA256","mismatches")}))


if __name__=="__main__":main()
