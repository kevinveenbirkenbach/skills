---
name: kvb-release-post
description: >
  Write a release's short posts from its brief: LinkedIn, Mastodon, WhatsApp,
  Instagram.
---

A post earns one click: one hook, one link. Input: `brief.yml`
and `listen.yml` from the `kvb-release` skill, the channel, and the project's
channel facts (voice, hashtags, links, length bounds) when a project skill
passes them. No project facts live here.

## 1. Listen

Run the `kvb-think-listen` skill only for what `listen.yml` leaves open for
this channel, such as the language of a personal message or a mention.

## 2. Brainstorm

Run the `kvb-think-brainstorm` skill on hooks for this channel and audience:
at least three first lines; keep the strongest.

## 3. Write, per language

A project skill's structure (several benefit lines, an "Also new" line)
replaces this one:

1. Hook: the first line carries the headline benefit and works on its own
   before "see more".
2. One benefit with its proof from the brief.
3. The brief's link, then the channel's hashtags or mentions.

## 4. Bounds without project facts

| Channel | Limit | Shown before "more" |
| --- | --- | --- |
| LinkedIn post | 3000 characters | about 210 characters |
| Mastodon | 500 characters, a link counts 23 | everything |
| WhatsApp | aim under 700 characters | the first line |
| Instagram caption | 2200 characters, at most 30 hashtags | about 125 characters |

## 5. Rules

- Every number, name and date comes from `brief.yml`.
- No em dashes, no placeholder, no claim the brief does not prove.
- Write into `/tmp/release-<version>/` under the file name the project skill
  sets, else `<channel>/<language>.txt`, and report each file's character
  count against its limit.
