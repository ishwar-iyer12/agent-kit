<#
.SYNOPSIS
  Provision the shared staging EC2 (one small Ubuntu box, docker compose per project). Idempotent on
  the security group and key pair; refuses to launch a second instance with the same Name tag.

.USAGE
  aws login                                   # once, interactive
  pwsh infra/staging/provision-staging.ps1 -Repos ishwar-iyer12/agent-workflow-demo
  pwsh infra/staging/provision-staging.ps1 -Repos ishwar-iyer12/agent-workflow-demo -InstanceType t3.small -Region eu-west-2 -Ports 80,443,8080
  pwsh infra/staging/provision-staging.ps1 -Status      # show the instance
  pwsh infra/staging/provision-staging.ps1 -Terminate   # tear down instance (keeps SG + key pair)

.OUTPUT
  Prints the public IP / DNS and the exact gh commands to set repo variables + secrets.
#>
[CmdletBinding()]
param(
  [string[]]$Repos = @('ishwar-iyer12/agent-workflow-demo'),
  [string]$BaseBranch = 'temp-prod',
  [string]$Region = 'eu-west-2',
  [string]$InstanceType = 't3.small',
  [int]$DiskGb = 30,
  [int[]]$Ports = @(22, 80, 443, 8080),
  [string]$Name = 'agent-staging',
  [string]$PublicKeyPath = "$env:USERPROFILE\.ssh\id_ed25519.pub",
  [switch]$Status,
  [switch]$Terminate
)
$ErrorActionPreference = 'Stop'
function Aws { $out = & aws @args --region $Region --output json 2>&1; if ($LASTEXITCODE) { throw "aws $($args -join ' '): $out" }; if ($out) { $out | ConvertFrom-Json } }

$existing = (Aws ec2 describe-instances --filters "Name=tag:Name,Values=$Name" "Name=instance-state-name,Values=pending,running,stopping,stopped").Reservations.Instances | Select-Object -First 1
if ($Status) { if ($existing) { $existing | Select-Object InstanceId, InstanceType, @{n='State';e={$_.State.Name}}, PublicIpAddress, PublicDnsName | Format-List } else { "no instance named $Name" }; exit 0 }
if ($Terminate) { if (-not $existing) { "nothing to terminate"; exit 0 }; Aws ec2 terminate-instances --instance-ids $existing.InstanceId | Out-Null; "terminating $($existing.InstanceId)"; exit 0 }
if ($existing) { throw "Instance $($existing.InstanceId) already exists (state $($existing.State.Name)). Use -Status or -Terminate." }
if (-not (Test-Path $PublicKeyPath)) { throw "No public key at $PublicKeyPath" }

# key pair (import local public key so the existing private key works)
$pub = (Get-Content $PublicKeyPath -Raw).Trim()
$kp = try { (Aws ec2 describe-key-pairs --key-names $Name).KeyPairs } catch { $null }
if (-not $kp) { Aws ec2 import-key-pair --key-name $Name --public-key-material "fileb://$PublicKeyPath" | Out-Null; "imported key pair $Name" }

# security group
$vpc = (Aws ec2 describe-vpcs --filters "Name=isDefault,Values=true").Vpcs[0].VpcId
$sg = try { (Aws ec2 describe-security-groups --filters "Name=group-name,Values=$Name" "Name=vpc-id,Values=$vpc").SecurityGroups[0] } catch { $null }
if (-not $sg) {
  $sgId = (Aws ec2 create-security-group --group-name $Name --description 'agent staging' --vpc-id $vpc).GroupId
  foreach ($p in $Ports) { Aws ec2 authorize-security-group-ingress --group-id $sgId --protocol tcp --port $p --cidr 0.0.0.0/0 | Out-Null }
  "created security group $sgId (tcp $($Ports -join ','))"
} else { $sgId = $sg.GroupId }

# latest Ubuntu 24.04 LTS AMI
$ami = (Aws ssm get-parameter --name '/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id').Parameter.Value

# user data
$ud = Get-Content (Join-Path $PSScriptRoot 'cloud-init.yaml') -Raw
$ud = $ud.Replace('__SSH_PUBKEY__', $pub).Replace('__REPOS__', ($Repos -join ' ')).Replace('__BASE_BRANCH__', $BaseBranch)
$udFile = Join-Path $env:TEMP "staging-user-data-$([guid]::NewGuid()).yaml"
[IO.File]::WriteAllText($udFile, $ud, (New-Object Text.UTF8Encoding $false))

$bdm = '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":' + $DiskGb + ',"VolumeType":"gp3","DeleteOnTermination":true}}]'
$tags = "ResourceType=instance,Tags=[{Key=Name,Value=$Name},{Key=purpose,Value=agent-staging}]"
$inst = (Aws ec2 run-instances --image-id $ami --instance-type $InstanceType --key-name $Name --security-group-ids $sgId --user-data "file://$udFile" --block-device-mappings $bdm --tag-specifications $tags --metadata-options 'HttpTokens=required' --count 1).Instances[0]
Remove-Item $udFile -Force
"launched $($inst.InstanceId) ($InstanceType, $ami); waiting for running..."
& aws ec2 wait instance-running --instance-ids $inst.InstanceId --region $Region
$inst = (Aws ec2 describe-instances --instance-ids $inst.InstanceId).Reservations[0].Instances[0]
$ip = $inst.PublicIpAddress; $dns = $inst.PublicDnsName

@"

Staging host: $ip  ($dns)
cloud-init takes ~3 min. Check:  ssh deploy@$ip 'ls -la ~/.cloud-init-done && docker --version'

Repo wiring (per project repo):
  gh variable set STAGING_ENABLED --body true   -R <owner/repo>
  gh variable set STAGING_HOST    --body $ip    -R <owner/repo>
  gh variable set STAGING_SCHEME  --body http   -R <owner/repo>        # https once a DNS name + Caddy TLS exist
  gh secret   set STAGING_USER    --body deploy -R <owner/repo>
  gh secret   set STAGING_SSH_KEY < $env:USERPROFILE\.ssh\id_ed25519 -R <owner/repo>   # or a dedicated deploy key
Then push to $BaseBranch or label a PR deploy-staging.
"@
