#!/usr/bin/env sh
set -eu

RUNNER_UID=$(id -u)
export DOCKER_HOST="unix:///run/user/$RUNNER_UID/docker.sock"
MAX_AGE_SECONDS=${HERMES_RUNNER_MAX_AGE_SECONDS:-3600}
now=$(date +%s)
removed=0

containers=$(docker ps -aq --filter label=hermes-task-id)
for container_id in $containers; do
  case "$container_id" in
    *[!0-9a-f]*|'')
      echo "runner-reaper=failed check=invalid-container-id" >&2
      exit 1
      ;;
  esac
  created=$(docker inspect --format '{{.Created}}' "$container_id")
  created_epoch=$(date --date "$created" +%s) || continue
  age=$((now - created_epoch))
  if [ "$age" -ge "$MAX_AGE_SECONDS" ]; then
    docker rm -f "$container_id" >/dev/null
    removed=$((removed + 1))
  fi
done

printf 'runner-reaper=passed removed=%s\n' "$removed"
