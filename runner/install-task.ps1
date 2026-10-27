<#
.SYNOPSIS
  Registers (or removes) a Windows Task Scheduler job that runs overnight.ps1 on weeknights.
  Fallback for machines where Orca automations are not enabled. Safe to re-run.

.USAGE
  pwsh scripts/agent/install-task.ps1              # 23:00 Sun-Thu, claude -p mode
  pwsh scripts/agent/install-task.ps1 -At 22:30 -Mode orca
  pwsh scripts/agent/install-task.ps1 -Remove
#>
param(
  [string]$At = '23:00',
  [ValidateSet('auto', 'orca', 'claude')] [string]$Mode = 'claude',
  [switch]$Remove
)
$name = 'AgentWorkflow Overnight'
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue; Write-Host "removed $name"; exit 0 }

$script = Join-Path $PSScriptRoot 'overnight.ps1'
$pwsh = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $pwsh) { $pwsh = (Get-Command powershell).Source }
$action = New-ScheduledTaskAction -Execute $pwsh -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -Mode $Mode" -WorkingDirectory (Split-Path $PSScriptRoot -Parent | Split-Path -Parent)
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday, Monday, Tuesday, Wednesday, Thursday -At $At
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 4) -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "registered '$name' at $At Sun-Thu, mode=$Mode. Check: Get-ScheduledTask -TaskName '$name'"
