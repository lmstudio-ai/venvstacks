#!/bin/sh
# Update remote references
git fetch --prune
# Identify and delete tracking branches that no longer exist on remote
git branch -vv | grep 'gone]' | awk '{print $1}' | xargs git branch -D
# List remaining branches (local-only and those that still exist remotely)
git branch -vv
