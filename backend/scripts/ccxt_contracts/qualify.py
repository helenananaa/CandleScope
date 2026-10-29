"""Cross-language parity runner. Supply a generated pinned CCXT checkout.

Runs additive contracts in real JS, Python sync/async, PHP sync/async, C#, Go,
Java runtimes. Output compares structured envelopes including full raw JSON.
Generated harnesses/build outputs live under --output, never in source files.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--ccxt", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
p.add_argument("--java-classpath")
p.add_argument(
    "--language", required=True, choices=["js", "python", "php", "cs", "go", "java"]
)
a = p.parse_args()
root = a.ccxt.resolve()
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=True)
fixture = {
    "row": [
        "1772323200000",
        "100.000000000000001",
        "103",
        "99",
        "102",
        "100",
        "1",
        "101",
        "1",
    ],
    "market": dict(
        id="BTC-USDT-SWAP",
        symbol="BTC/USDT:USDT",
        base="BTC",
        quote="USDT",
        settle="USDT",
        type="swap",
        swap=True,
        spot=False,
        contract=True,
        linear=True,
        inverse=False,
    ),
    "binanceRow": [
        1772323200000,
        "100.000000000000001",
        "103",
        "99",
        "102",
        "10",
        1772323259999,
        "1010",
        4,
        "6",
        "606",
        "0",
    ],
    "binanceMarket": dict(
        id="BTCUSDT",
        symbol="BTC/USDT",
        base="BTC",
        quote="USDT",
        type="spot",
        spot=True,
        swap=False,
        contract=False,
    ),
}
(out / "fixture.json").write_text(json.dumps(fixture))
common = """function emit(o,b,f) { return [o.parseCandlescopeKline(f.row,f.market,'1m'),b.parseCandlescopeKline(f.binanceRow,f.binanceMarket,'1m')]; }"""
if a.language == "js":
    target = out / "contract.mjs"
    target.write_text(
        f"import ccxt from '{root}/js/ccxt.js';\nimport fs from 'node:fs';\n"
        + common
        + "\nconsole.log(JSON.stringify(emit(new ccxt.okx(),new ccxt.binance(),JSON.parse(fs.readFileSync(process.argv[2],'utf8')))));"
    )
    command = ["node", str(target), str(out / "fixture.json")]
elif a.language == "python":
    target = out / "contract.py"
    target.write_text(
        f"import sys,json\nsys.path.insert(0,{str(root / 'python')!r})\nimport ccxt\nimport ccxt.async_support as async_ccxt\nf=json.load(open(sys.argv[1]))\nfor module in (ccxt,async_ccxt):\n print(json.dumps([module.okx().parse_candlescope_kline(f['row'],f['market'],'1m'),module.binance().parse_candlescope_kline(f['binanceRow'],f['binanceMarket'],'1m')]))\n"
    )
    command = [sys.executable, str(target), str(out / "fixture.json")]
elif a.language == "php":
    target = out / "contract.php"
    target.write_text(
        "<?php\nrequire '"
        + str(root / "vendor/autoload.php")
        + "';\n$f=json_decode(file_get_contents($argv[1]),true);\nforeach (['ccxt\\\\','ccxt\\\\async\\\\'] as $ns) { $oc=$ns.'okx';$bc=$ns.'binance';$o=new $oc();$b=new $bc();echo json_encode([$o->parse_candlescope_kline($f['row'],$f['market'],'1m'),$b->parse_candlescope_kline($f['binanceRow'],$f['binanceMarket'],'1m')]).PHP_EOL; }\n"
    )
    command = [
        "/opt/homebrew/opt/php@8.4/bin/php",
        str(target),
        str(out / "fixture.json"),
    ]
elif a.language == "cs":
    target = out / "Contract.csproj"
    target.write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net9.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings></PropertyGroup><ItemGroup><Reference Include="ccxt"><HintPath>'
        + str(root / "cs/ccxt/bin/Release/netstandard2.1/ccxt.dll")
        + "</HintPath></Reference><Reference Include=\"" + str(root / "cs/tests/bin/Release/net9.0/*.dll") + "\" /></ItemGroup></Project>"
    )
    (out / "Program.cs").write_text(
        'var o=new ccxt.okx(); var b=new ccxt.binance(); var f=(Dictionary<string,object>)o.parseJson(File.ReadAllText(args[0])); Console.WriteLine(o.json(new List<object>{o.parseCandlescopeKline(f["row"],f["market"],"1m"),b.parseCandlescopeKline(f["binanceRow"],f["binanceMarket"],"1m")}));'
    )
    command = [
        "/opt/homebrew/opt/dotnet@9/bin/dotnet",
        "run",
        "--project",
        str(target),
        "--",
        str(out / "fixture.json"),
    ]
elif a.language == "go":
    (out / "go.mod").write_text(
        "module contract\ngo 1.24.0\nrequire github.com/ccxt/ccxt/go/v4 v4.0.0\nreplace github.com/ccxt/ccxt/go/v4 => "
        + str(root / "go/v4")
        + "\n"
    )
    (out / "main.go").write_text(
        'package main\nimport("os";"fmt";ccxt "github.com/ccxt/ccxt/go/v4")\nfunc main(){ o:=ccxt.NewOkxCore();o.Init(map[string]any{});b:=ccxt.NewBinanceCore();b.Init(map[string]any{});data,_:=os.ReadFile(os.Args[1]);f:=o.ParseJson(string(data)).(map[string]any);fmt.Println(o.Json([]any{o.ParseCandlescopeKline(f["row"],f["market"],"1m"),b.ParseCandlescopeKline(f["binanceRow"],f["binanceMarket"],"1m")})) }'
    )
    command = ["go", "run", "-mod=mod", ".", str(out / "fixture.json")]
else:
    if not a.java_classpath:
        p.error("--java-classpath required")
    target = out / "Contract.java"
    target.write_text(
        'import io.github.ccxt.exchanges.*; import java.nio.file.*; import java.util.*; public class Contract { public static void main(String[] args) throws Exception { var o=new OkxCore();var b=new BinanceCore();var f=(Map<String,Object>)o.parseJson(Files.readString(Path.of(args[0])));System.out.println(o.json(Arrays.asList(o.parseCandlescopeKline(f.get("row"),f.get("market"),"1m"),b.parseCandlescopeKline(f.get("binanceRow"),f.get("binanceMarket"),"1m")))); }}'
    )
    command = [
        "/opt/homebrew/opt/openjdk@21/bin/java",
        "--class-path",
        a.java_classpath,
        str(target),
        str(out / "fixture.json"),
    ]
run = subprocess.run(command, cwd=out, text=True, capture_output=True, timeout=600)
(out / "stdout.log").write_text(run.stdout)
(out / "stderr.log").write_text(run.stderr)
if run.returncode:
    print(run.stderr[-5000:])
    sys.exit(run.returncode)
values = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("[{")]
assert values, "missing JSON contract output"
for value in values:
    okx, binance = value
    assert (
        okx["open"] == fixture["row"][1]
        and okx["volume"] == "1"
        and okx["sourceVolume"] == "100"
        and okx["sourceVolumeUnit"] == "contracts"
    )
    assert (
        okx.get("trades") is None
        and okx.get("eventTime") is None
        and okx.get("takerBuyBaseVolume") is None
    )
    assert okx["closed"] is True and json.loads(okx["raw"]) == fixture["row"]
    assert (
        binance["schema"] == "candlescope.binance.spot.kline.v1"
        and binance["trades"] == 4
    )
    assert (
        binance["open"] == fixture["binanceRow"][1]
        and json.loads(binance["raw"]) == fixture["binanceRow"]
    )
(out / "result.json").write_text(
    json.dumps(
        {
            "language": a.language,
            "status": "passed",
            "variants": len(values),
            "envelopes": values,
        },
        indent=2,
    )
    + "\n"
)
print(a.language, "contract passed", len(values), "variants")
