# Trello adapter for overnight.ps1. Dot-source; needs TRELLO_KEY / TRELLO_TOKEN in env.
# Exposes: Get-TrackerReadyItems, Move-TrackerItem. Items are normalised to:
#   @{ tracker='trello'; id=<shortLink>; url=<shortUrl>; title=<name>; labels=@(...); position=<pos>; raw=<card> }

function Invoke-Trello($method, $path, $query = @{}) {
  $query['key'] = $env:TRELLO_KEY; $query['token'] = $env:TRELLO_TOKEN
  $qs = ($query.GetEnumerator() | ForEach-Object { "$($_.Key)=$([Uri]::EscapeDataString([string]$_.Value))" }) -join '&'
  Invoke-RestMethod -Method $method -Uri "https://api.trello.com/1/$path`?$qs"
}

function Get-TrackerReadyItems($cfg, $max) {
  if (-not $env:TRELLO_KEY -or -not $env:TRELLO_TOKEN) { throw 'TRELLO_KEY / TRELLO_TOKEN missing' }
  $boardId = $cfg.trello.boardId
  $lists = Invoke-Trello GET "boards/$boardId/lists" @{ fields = 'name' }
  $ready = $lists | Where-Object name -eq $cfg.trello.lists.ready | Select-Object -First 1
  if (-not $ready) { throw "Board $boardId has no list '$($cfg.trello.lists.ready)'" }
  Invoke-Trello GET "lists/$($ready.id)/cards" @{ fields = 'name,shortLink,shortUrl,labels,pos'; limit = 50 } |
    Sort-Object pos | Select-Object -First $max | ForEach-Object {
      @{ tracker = 'trello'; id = $_.shortLink; url = $_.shortUrl; title = $_.name; labels = @($_.labels | ForEach-Object name); position = $_.pos; raw = $_ }
    }
}

function Move-TrackerItem($cfg, $item, $stateKey) {
  $listName = $cfg.trello.lists.$stateKey
  $lists = Invoke-Trello GET "boards/$($cfg.trello.boardId)/lists" @{ fields = 'name' }
  $target = $lists | Where-Object name -eq $listName | Select-Object -First 1
  if (-not $target) { throw "No list '$listName'" }
  Invoke-Trello PUT "cards/$($item.raw.id)" @{ idList = $target.id } | Out-Null
}
