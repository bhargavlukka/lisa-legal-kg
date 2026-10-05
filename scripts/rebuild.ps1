# Windows equivalent of scripts/rebuild.sh. Usage: .\scripts\rebuild.ps1 [-Live]
param([switch]$Live)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = if ($env:PYTHON) { $env:PYTHON } else { ".venv\Scripts\python" }
$offline = if ($Live) { @() } else { @("--offline") }
& $py -m lisa.graph.verify_data; if ($LASTEXITCODE) { exit 1 }
foreach ($ds in "all", "immigration", "litigation", "gold_eval") {
  & $py scripts/build_graph.py --dataset $ds --no-load; if ($LASTEXITCODE) { exit 1 }
}
& $py scripts/extract_llm.py --dataset gold_eval @offline; if ($LASTEXITCODE) { exit 1 }
& $py scripts/eval_extraction.py; if ($LASTEXITCODE) { exit 1 }
& $py scripts/enrich_llm.py @offline; if ($LASTEXITCODE) { exit 1 }
& $py scripts/load_neo4j.py
if ($LASTEXITCODE) { Write-Host "neo4j not reachable - graph JSON is still served by the memory backend" }
Write-Host "rebuild complete: out/graph_*.json, out/eval/extraction_report.md"
