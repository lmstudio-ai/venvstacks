# Update remote references
git fetch --prune
# Identify and delete tracking branches that no longer exist on remote
git branch -vv | Where-Object { $_ -match 'gone\]' } | ForEach-Object { $_.Trim().Split()[0] } | ForEach-Object { git branch -D $_ }
# List remaining branches (local-only and those that still exist remotely)
git branch -vv
