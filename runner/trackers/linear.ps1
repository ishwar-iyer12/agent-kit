# Linear adapter for overnight.ps1. Dot-source; needs LINEAR_API_KEY in env.
# Exposes: Get-TrackerReadyItems, Move-TrackerItem. Items normalised like the Trello adapter:
#   @{ tracker='linear'; id=<identifier e.g. TL-123>; url=<url>; title=<title>; labels=@(...); position=<sortOrder>; raw=<issue> }

function Invoke-Linear($query, $variables = @{}) {
  if (-not $env:LINEAR_API_KEY) { throw 'LINEAR_API_KEY missing' }
  $body = @{ query = $query; variables = $variables } | ConvertTo-Json -Depth 8 -Compress
  $res = Invoke-RestMethod -Method POST -Uri 'https://api.linear.app/graphql' -Headers @{ Authorization = $env:LINEAR_API_KEY } -ContentType 'application/json' -Body $body
  if ($res.errors) { throw ("Linear: " + (($res.errors | ForEach-Object message) -join '; ')) }
  $res.data
}

function Get-TrackerReadyItems($cfg, $max) {
  $q = @'
query($team: String!, $state: String!, $label: String!, $first: Int!) {
  issues(first: $first, orderBy: updatedAt,
    filter: { team: { key: { eq: $team } }, state: { name: { eq: $state } }, labels: { name: { eq: $label } }, assignee: { isMe: { eq: true } } }) {
    nodes { id identifier title url sortOrder priority labels { nodes { name } } }
  }
}
'@
  $d = Invoke-Linear $q @{ team = $cfg.linear.teamKey; state = $cfg.linear.states.ready; label = $cfg.linear.readyLabel; first = 50 }
  $d.issues.nodes | Sort-Object priority, sortOrder | Select-Object -First $max | ForEach-Object {
    @{ tracker = 'linear'; id = $_.identifier; url = $_.url; title = $_.title; labels = @($_.labels.nodes | ForEach-Object name); position = $_.sortOrder; raw = $_ }
  }
}

function Move-TrackerItem($cfg, $item, $stateKey) {
  $stateName = $cfg.linear.states.$stateKey
  $q = 'query($team: String!) { teams(filter: { key: { eq: $team } }) { nodes { states { nodes { id name } } } } }'
  $states = (Invoke-Linear $q @{ team = $cfg.linear.teamKey }).teams.nodes[0].states.nodes
  $target = $states | Where-Object name -eq $stateName | Select-Object -First 1
  if (-not $target) { throw "Linear team $($cfg.linear.teamKey) has no state '$stateName'" }
  $m = 'mutation($id: String!, $stateId: String!) { issueUpdate(id: $id, input: { stateId: $stateId }) { success } }'
  Invoke-Linear $m @{ id = $item.raw.id; stateId = $target.id } | Out-Null
}
