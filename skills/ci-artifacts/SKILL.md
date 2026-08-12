---
name: ci-artifacts
description: >
  Get the real evidence out of a CI run: per-job logs even while the run is
  still in progress, and the artifacts that hold the cause rather than the
  symptom. Trigger whenever a CI failure has to be explained, and from the
  triage skill's artifact step. Portable across projects.
---

A job log tells you what broke. An artifact tells you why. Investigating a CI
failure without downloading its artifacts is guessing with extra steps.

## Getting the log

`gh run view --log` refuses to serve anything while a run is unfinished:

    run <id> is still in progress; logs will be available when it is complete

That is not a dead end — individual *jobs* that have already finished are
served by the API:

    gh api /repos/<owner>/<repo>/actions/jobs/<JOB_ID>/logs

Enumerate the failing jobs and their ids first:

    gh run view <RUN_ID> --repo <owner>/<repo> --json jobs \
      --jq '.jobs[] | select(.conclusion=="failure") | "\(.databaseId)\t\(.name)"'

Save every log to a file (`/tmp/ci-logs-<run>/<job>.log`) and grep the file
repeatedly. Re-fetching a log to find the line you just lost costs minutes;
grepping the saved copy costs milliseconds.

## Getting the artifacts

    gh api /repos/<owner>/<repo>/actions/runs/<RUN_ID>/artifacts --paginate \
      --jq '.artifacts[] | "\(.name)\t\(.size_in_bytes)"'
    gh run download <RUN_ID> --repo <owner>/<repo> -n <NAME> -D <DIR>

Choose by content, not by name length:

- **Rescue / diagnostics bundles** carry the reverse-proxy access and error log,
  the per-service and per-container logs, the journal, and the event stream.
  This is where causes live. Prefer them.
- **Test-report bundles** (Playwright and friends) are mostly video and traces
  and can run to hundreds of megabytes for one assertion string. Pull one only
  when you need the assertion text or the error-context file.
- **Inventory / runtime dumps** settle "what was actually deployed" questions.

Inside a rescue bundle, read in this order: the reverse-proxy log (it shows
status code, upstream, and time-to-response for the exact failing request), the
application container log, then the journal and event stream for restarts and
OOM kills.

An access-log line is a timing witness. A `499` means the *client* gave up; the
server was still working. A `504` or an `upstream timed out ... while reading
upstream` means your backend never answered. `ReqTime` versus `UpstreamTime`
tells you whether the proxy or the upstream burned the seconds.

## Grep hygiene

Two failure modes turn a search into a false conclusion:

- **Clustered flags silently change the pattern.** Write them separately —
  `grep -r -a -i -l -F "needle" dir/`, not `-ariel`. A cluster where one letter
  takes an argument consumes your pattern and searches for something else, and
  the run still exits successfully.
- **Substring matches lie.** A protocol token like `h2c` matches inside
  `veth2cb3f8c`; a short id matches inside a hash. Before concluding anything
  from a hit, print its context (`grep -o ".\{30\}needle.\{30\}"`) and look at
  it. Before concluding anything from a *miss*, prove the command was
  well-formed by searching for a string you know is present.

Binary-ish logs need `-a`, or grep reports "binary file matches" and you see
nothing.

## Rules

- Download before theorising. Do it even when the job log looks conclusive: a
  log that explains the symptom rarely explains the cause.
- Quote literally, with the file path and line number. Never paraphrase a log
  line you did not read, and never reconstruct one from memory.
- A negative result is a finding only when the search was verified sound.
- "The artifact does not settle this" is a legitimate answer. Say it instead of
  filling the gap with a plausible mechanism.
