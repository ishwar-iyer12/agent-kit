<#
.SYNOPSIS
  Overnight fan-out runner (agent-kit). For every enabled project in projects.json: read its agent.json,
  pull ready items from its tracker (Trello or Linear), start one Claude Code worker per item in its own
  git worktree (Orca orchestration when reachable, plain `claude -p` otherwise), wait, write a report,
  post it to Slack.

.USAGE
  pwsh runner/overnight.ps1                       # all enabled projects, defaults from projects.json
  pwsh runner/overnight.ps1 -Project agent-workflow-demo -MaxCards 1 -DryRun
  pwsh runner/overnight.ps1 -Mode claude          # skip Orca

.FILES
  projects.json  next to this script or $env:AGENT_PROJECTS_JSON (per machine, not committed; see schema/projects.json.example)
  <project>/agent.json  tracker + branch + test config (committed in each project)
  <project>/.env        TRELLO_KEY/TRELLO_TOKEN or LINEAR_API_KEY, SLACK_WEBHOOK_URL (not committed)

.LABELS
  cloud   skipped here (the cloud nightly task takes it)
  serial  run after all parallel workers of that project finish, one at a time
#>
[CmdletBinding()]
param(
  [string]$Project = '',
  [int]$MaxCards = 0,
  [ValidateSet('auto', 'orca', 'claude')] [string]$Mode = 'auto',
  [string]$Model = '',
  [int]$TimeoutMinutes = 90,
  [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$kitRoot = Split-Path $PSScriptRoot -Parent
$stamp = Get-Date -Format 'yyyy-MM-dd'

# ---------- machine config ----------
$projectsFile = if ($env:AGENT_PROJECTS_JSON) { $env:AGENT_PROJECTS_JSON } else { Join-Path $PSScriptRoot 'projects.json' }
if (-not (Test-Path $projectsFile)) { throw "No projects.json at $projectsFile (copy schema/projects.json.example)" }
$machine = Get-Content $projectsFile -Raw | ConvertFrom-Json
if ($MaxCards -le 0) { $MaxCards = if ($machine.maxCardsPerNight) { [int]$machine.maxCardsPerNight } else { 5 } }
if (-not $Model) { $Model = if ($machine.model) { $machine.model } else { 'opus' } }
$projects = @($machine.projects | Where-Object { $_.enabled -and (-not $Project -or $_.name -eq $Project) })
if ($projects.Count -eq 0) { Write-Host 'No enabled projects.'; exit 0 }

function Import-DotEnv($dir) {
  $f = Join-Path $dir '.env'
  if (-not (Test-Path $f)) { return }
  Get-Content $f | Where-Object { $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*=' -and $_ -notmatch '^\s*#' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim().Trim('"'))
  }
}

# ---------- mode ----------
$orcaOk = $false
if ($Mode -ne 'claude') {
  try { $null = orca status --json 2>$null; $orcaOk = ($LASTEXITCODE -eq 0) } catch { $orcaOk = $false }
  if ($Mode -eq 'orca' -and -not $orcaOk) { throw 'Orca runtime not reachable' }
}
$useOrca = $orcaOk -and $Mode -ne 'claude'
Write-Host "Mode: $(if ($useOrca) { 'orca orchestration' } else { 'claude -p in git worktrees' }); model $Model; max $MaxCards/project"

function Orca {
  $raw = & orca @args --json 2>$null | Out-String
  $env = $raw | ConvertFrom-Json
  if (-not $env.ok) { throw "orca $($args -join ' ') failed: $($env.error.message)" }
  $env.result
}

$answers = Get-Content (Join-Path $PSScriptRoot 'answers.json') -Raw
function WorkerPrompt($item) {
@"
/agent-kit:implement-card $($item.url)

Standing answers for questions you might have (do not stop to ask these):
$answers
"@
}

# ---------- run one worker, blocking (claude mode) or returning a dispatch (orca mode) ----------
function Start-Worker($proj, $cfg, $item) {
  if ($useOrca) {
    $task = Orca orchestration task-create --spec (WorkerPrompt $item) --task-title "[$($item.id)] $($item.title)"
    $taskId = if ($task.taskId) { $task.taskId } elseif ($task.task.id) { $task.task.id } else { $task.id }
    $w = Orca orchestration worker-start --task $taskId --worktree new-top-level --repo "path:$($proj.path)" --base-branch "origin/$($cfg.baseBranch)" --name "agent-$($item.id)" --agent claude --model $Model --setup run
    $dispatchId = if ($w.dispatchId) { $w.dispatchId } elseif ($w.dispatch.id) { $w.dispatch.id } else { $w.id }
    return @{ kind = 'orca'; dispatch = $dispatchId; task = $taskId }
  }
  $wt = Join-Path $proj.path ".worktrees/$($item.id)"
  if (Test-Path $wt) { git -C $proj.path worktree remove --force $wt | Out-Null }
  git -C $proj.path worktree add --detach $wt "origin/$($cfg.baseBranch)" | Out-Null
  $job = Start-Job -Name $item.id -ScriptBlock {
    param($wt, $prompt, $model)
    Set-Location $wt
    $out = & claude -p $prompt --model $model --permission-mode acceptEdits --output-format json 2>&1 | Out-String
    [pscustomobject]@{ out = $out; code = $LASTEXITCODE }
  } -ArgumentList $wt, (WorkerPrompt $item), $Model
  return @{ kind = 'job'; job = $job }
}

function Wait-Workers($handles, $results) {
  if ($useOrca) {
    $pending = @($handles.Keys)
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    while ($pending.Count -gt 0 -and (Get-Date) -lt $deadline) {
      $batch = try { Orca orchestration check --wait --types worker_done,escalation,question --timeout-ms 900000 } catch { $null }
      if (-not $batch) { continue }
      $deliveryId = if ($batch.deliveryId) { $batch.deliveryId } else { $batch.delivery.id }
      $messages = if ($batch.messages) { @($batch.messages) } elseif ($batch.message) { @($batch.message) } else { @($batch) }
      foreach ($msg in $messages) {
        $d = if ($msg.dispatchId) { $msg.dispatchId } else { $msg.payload.dispatchId }
        if (-not $handles[$d]) { continue }
        switch ($msg.type) {
          'worker_done' {
            $outcome = if ($msg.outcome) { $msg.outcome } else { $msg.payload.outcome }
            $handles[$d].status = $outcome; $handles[$d].summary = $msg.body; $pending = @($pending | Where-Object { $_ -ne $d })
            try { Orca orchestration worker-release --dispatch $d | Out-Null } catch { Write-Warning $_ }
          }
          'question' { try { Orca orchestration reply --id $msg.id --body 'See the standing answers in your prompt. If none applies, comment the question on the card, prefix the PR title with [blocked], and finish.' | Out-Null } catch { Write-Warning $_ } }
          'escalation' { $handles[$d].status = 'escalated'; $handles[$d].summary = $msg.body; $pending = @($pending | Where-Object { $_ -ne $d }) }
        }
      }
      if ($deliveryId) { try { Orca orchestration check --ack $deliveryId --peek | Out-Null } catch {} }
    }
    foreach ($d in $pending) { $handles[$d].status = 'timeout'; try { Orca orchestration worker-stop --dispatch $d | Out-Null } catch {} }
    foreach ($h in $handles.Values) { $results.Add($h) }
    return
  }
  $jobs = @($handles.Values | ForEach-Object { $_.job })
  $null = Wait-Job $jobs -Timeout ($TimeoutMinutes * 60)
  foreach ($h in $handles.Values) {
    $j = $h.job
    if ($j.State -ne 'Completed') { Stop-Job $j; $h.status = 'timeout' }
    else {
      $r = Receive-Job $j
      $h.summary = try { ($r.out | ConvertFrom-Json).result } catch { $r.out }
      $h.status = if ($r.code -eq 0) { 'succeeded' } else { 'failed' }
    }
    $results.Add($h)
  }
}

# ---------- main ----------
$results = [System.Collections.ArrayList]::new()
foreach ($proj in $projects) {
  Write-Host "`n== $($proj.name) ($($proj.path))"
  $cfgPath = Join-Path $proj.path 'agent.json'
  if (-not (Test-Path $cfgPath)) { Write-Warning "no agent.json in $($proj.path); skipping"; continue }
  $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
  Import-DotEnv $proj.path
  . (Join-Path $PSScriptRoot "trackers/$($cfg.tracker).ps1")

  $items = @(Get-TrackerReadyItems $cfg 50 | Where-Object { $_.labels -notcontains 'cloud' } | Select-Object -First $MaxCards)
  if ($items.Count -eq 0) { Write-Host '  nothing ready'; continue }
  $items | ForEach-Object { Write-Host "  - [$($_.id)] $($_.title)$(if ($_.labels -contains 'serial') { ' (serial)' })" }
  if ($DryRun) { continue }

  git -C $proj.path fetch -q origin --prune
  $reportFile = Join-Path $proj.path "overnight-report-$stamp.md"
  if (-not (Test-Path $reportFile)) { "# Overnight report $stamp - $($proj.name)", '' | Set-Content $reportFile -Encoding utf8 }

  $parallel = @($items | Where-Object { $_.labels -notcontains 'serial' })
  $serial   = @($items | Where-Object { $_.labels -contains 'serial' })

  $handles = @{}
  foreach ($it in $parallel) {
    Move-TrackerItem $cfg $it 'inProgress'
    $h = Start-Worker $proj $cfg $it; $h.item = $it; $h.project = $proj.name; $h.status = 'running'; $h.summary = ''
    $key = if ($h.kind -eq 'orca') { $h.dispatch } else { $it.id }
    $handles[$key] = $h
    Write-Host "  started $($it.id)"
  }
  if ($handles.Count) { Wait-Workers $handles $results }
  foreach ($it in $serial) {
    Move-TrackerItem $cfg $it 'inProgress'
    $h = Start-Worker $proj $cfg $it; $h.item = $it; $h.project = $proj.name; $h.status = 'running'; $h.summary = ''
    $key = if ($h.kind -eq 'orca') { $h.dispatch } else { $it.id }
    Write-Host "  started $($it.id) (serial)"
    Wait-Workers @{ $key = $h } $results
  }
}

if ($DryRun -or $results.Count -eq 0) { exit 0 }

# ---------- report ----------
$lines = @("*Overnight $stamp*")
foreach ($r in $results) {
  $it = $r.item
  $pr = ''
  try { $pr = gh pr list -R (git -C ($projects | Where-Object name -eq $r.project).path remote get-url origin) --search "head:agent/$($it.id.ToLower())" --json url --jq '.[0].url' 2>$null } catch {}
  if (-not $pr) { $pr = ([regex]::Match([string]$r.summary, 'https://github\.com/\S+/pull/\d+')).Value }
  $lines += "- $($r.project) [$($it.id)] $($it.title) - $($r.status)$(if ($pr) { " - $pr" })"
  $lines += "  $($it.url)"
}
$text = $lines -join "`n"
Write-Host "`n$text"
$projects | ForEach-Object { $f = Join-Path $_.path "overnight-report-$stamp.md"; if (Test-Path $f) { Add-Content $f ($lines -join "`n") -Encoding utf8 } }
if ($env:SLACK_WEBHOOK_URL) {
  Invoke-RestMethod -Method POST -Uri $env:SLACK_WEBHOOK_URL -ContentType 'application/json' -Body (@{ text = $text } | ConvertTo-Json -Compress) | Out-Null
  Write-Host 'Posted to Slack.'
}
