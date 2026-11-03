# Docker items

## Inventory

`docker system df -v`; containers with state and compose project label,
volumes with the containers using them (`docker ps -a --filter
volume=<name>`), dangling and unused images, build cache, unused networks.
For every stopped container (`exited`, `created`) record its volumes
(`{{.Mounts}}`); for every volume no running container uses, record size,
`CreatedAt` (`docker volume inspect`) and compose project label, anonymous
ones included.

## Volumes checklist

Stopped containers and volumes always get their own checklist
(`multiSelect: true`, header `⚠ Volumes`, in a further call when call 1 is
full). Every stopped container and every volume without a running container
appears there unless a peer claimed it; none is dropped as "not proposed",
`unknown` and anonymous ones included. The question text carries the warning:
`Deleting a volume is irreversible; its data does not come back unless the
description says how.` One option per stopped container together with its
volumes (removing the container alone frees nothing of them), one per
unattached volume, anonymous ones grouped. Each description gives size,
`CreatedAt`, owner or compose project, and what is lost.

## After removing images

Locally built images free little on their own: their layers stay behind as
build cache. Re-measure `docker system df`; the layers show up as reclaimable
build cache. Offer `docker builder prune --filter until=24h` as a follow-up
candidate, ask the peers that claimed build cache first, and run it outside
their running builds.
