# 下载 yukkcat/image-prompts 社区源 + 大型远程 JSON 到画布离线 bundled 目录
# 用法：.\scripts\setup_prompt_library.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root "vendor\shiguang-canvas\public\prompts\bundled"
New-Item -ItemType Directory -Force -Path $out | Out-Null

$registry = @(
  "banana-prompt-quicker",
  "davidwu-gpt-image2-prompts",
  "freestylefly-gpt-image-2",
  "awesome-gpt-image",
  "awesome-gpt4o-image-prompts",
  "youmind-gpt-image-2",
  "youmind-nano-banana-pro"
)

$remotes = @(
  @{
    file = "stimqq-gpt-image-2.json"
    url  = "https://raw.githubusercontent.com/stimQQ/gpt-image-2-prompts/master/prompts.json"
  },
  @{
    file = "nexra-ai-image-prompts.json"
    url  = "https://raw.githubusercontent.com/NeXra-AI/awesome-ai-image-prompts/main/data/prompts.json"
  }
)

$base = "https://raw.githubusercontent.com/yukkcat/image-prompts/main/dist/sources"
$ok = 0
$fail = 0

foreach ($id in $registry) {
  $dest = Join-Path $out "$id.json"
  $url = "$base/$id.json"
  try {
    Write-Host "Fetching $id ..."
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    $ok++
  } catch {
    Write-Warning "Failed $id : $_"
    $fail++
  }
}

foreach ($r in $remotes) {
  $dest = Join-Path $out $r.file
  try {
    Write-Host "Fetching $($r.file) ..."
    Invoke-WebRequest -Uri $r.url -OutFile $dest -UseBasicParsing
    $ok++
  } catch {
    Write-Warning "Failed $($r.file) : $_"
    $fail++
  }
}

Write-Host "Done: $ok ok, $fail fail -> $out"
Write-Host "Rebuild canvas: cd vendor/shiguang-canvas; npm run build"
