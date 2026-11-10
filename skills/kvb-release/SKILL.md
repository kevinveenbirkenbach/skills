---
name: kvb-release
description: >
  Announce a release: write one brief since the last tag, hand each channel
  its slice.
---

One brief per release, read once: every channel writes from the brief, never
from the changelog, so each fact lives in one place. This method holds no
project facts; voice, channels, length bounds, links and templates come from
the project's own `<prefix>-release-<channel>` skills.

## 1. Listen once

Run the `kvb-think-listen` skill once for what only the operator knows: the
tag, the languages (default English), the audiences, the highlights, what to
leave out and the channels wanted. Write the answers to
`/tmp/release-<version>/listen.yml` (`tag`, `languages`, `audience`,
`highlights`, `leave_out`, `channels`) and hand that file to every channel,
so the operator answers each question once.

## 2. Collect

- The range runs from the newest `vX.Y.Z` tag before the release to the
  release commit: `git describe --tags --abbrev=0 --match
  'v[0-9]*.[0-9]*.[0-9]*' <release tag>^` once the release is tagged, else
  the same without `<release tag>^` from HEAD.
- Read the release's changelog entry once; without one, write it first with
  the project's changelog skill, else the `kvb-release-changelog` skill.

## 3. Brief

Run the `kvb-think-brainstorm` skill on the headline benefit, then write
`/tmp/release-<version>/brief.yml`: version, date, languages, headline
benefit, three to five benefits each with the changelog lines that prove it,
upgrade notes and links. `languages` is the only answer the brief copies from
`listen.yml`: an answer steers what a channel stresses, it never backs a
number. Every number comes from the changelog or the repository.

## 4. Hand each channel its slice

Per channel in `listen.yml`, or every channel the project's release skills
cover when `listen.yml` names none: the project's
`<prefix>-release-<channel>` skill when its skills directory has one, else
the general method:

| Form | Channels | Method |
| --- | --- | --- |
| long | blog, LinkedIn article, newsletter per audience | `kvb-release-article` |
| short | LinkedIn post, Mastodon, WhatsApp, Instagram | `kvb-release-post` |
| entry | changelog | `kvb-release-changelog` |

Each gets `brief.yml`, `listen.yml` and its channel, runs its own listen and
brainstorm, and writes into `/tmp/release-<version>/` under the file name
the project skill sets, else `<channel>/<language>.<ext>`.

## 5. Check

Fix in every file under `/tmp/release-<version>/`, subfolders included,
before the hand-over: a leftover placeholder (`TODO`, `XXX`, `<...>`), an
em dash, a length outside the channel's bounds, a number absent from
`brief.yml`.

## 6. Hand over

List every file with its channel, language and length. Never publish, post,
send, tag or release: the operator does.
