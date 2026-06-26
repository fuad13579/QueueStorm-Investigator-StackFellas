# Posts the canonical SUST sample cases to the live /analyze-ticket endpoint
# and saves the response body to data/_live_response.json.
# Usage: pwsh -File scripts/fetch_live_sample.ps1

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$inputPath = Join-Path $repoRoot "data/SUST_Preli_Sample_Cases.json"
$outputPath = Join-Path $repoRoot "data/_live_response.json"
$url = "https://queuestorm-investigator-stackfellas.onrender.com/analyze-ticket"

if (-not (Test-Path $inputPath)) {
    throw "Input file not found: $inputPath"
}

Write-Host "POSTing $inputPath to $url ..."

try {
    $response = Invoke-WebRequest `
        -Uri $url `
        -Method POST `
        -ContentType "application/json" `
        -InFile $inputPath `
        -TimeoutSec 60 `
        -UseBasicParsing `
        -ErrorAction Stop
    $status = [int]$response.StatusCode
    $body = $response.Content
} catch {
    if ($_.Exception.Response) {
        $status = [int]$_.Exception.Response.StatusCode
        $body = $_.Exception.Response.GetResponseStream() | ForEach-Object { $_ } | Out-String
    } else {
        throw
    }
}

$body | Out-File -FilePath $outputPath -Encoding utf8

Write-Host ("HTTP {0} | {1} bytes written to {2}" -f $status, $body.Length, $outputPath)