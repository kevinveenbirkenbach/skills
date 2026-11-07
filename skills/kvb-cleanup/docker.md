# Docker items

## Inventory

`docker system df -v`: containers with state and compose project, volumes
with their users (`docker ps -a --filter volume=<name>`), dangling and unused
images, build cache, unused networks. An untagged image with `RepoDigests`
is a digest-pinned pull: medium. Per stopped container its volumes
(`{{.Mounts}}`); per volume without a running user its size, `CreatedAt` and
compose project, anonymous ones included.

## Volumes checklist

Stopped containers and volumes get their own checklist (`multiSelect: true`,
header `⚠ Volumes`, a further call when call 1 is full), each one unless a
peer claimed it, `unknown` and anonymous ones included. Question text:
`Deleting a volume is irreversible; its data does not come back unless the
description says how.` One option per stopped container with its volumes,
one per unattached volume, anonymous ones grouped; each names size,
`CreatedAt`, owner or project, and what is lost.

## After removing images

Built images leave their layers as build cache: re-measure `docker system
df`, then offer `docker builder prune --filter until=24h`, after asking the
peers that claimed build cache, outside their builds.
