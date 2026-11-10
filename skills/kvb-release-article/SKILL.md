---
name: kvb-release-article
description: >
  Write a release's long form from its brief: blog article, LinkedIn article,
  newsletter.
---

Long form tells one audience why the release matters. Input: `brief.yml` and
`listen.yml` from the `kvb-release` skill, the channel, and the project's
channel facts (voice, length bounds, links, template) when a project skill
passes them. No project facts live here.

## 1. Listen

Run the `kvb-think-listen` skill only for what `listen.yml` leaves open for
this channel, such as the newsletter's audience or its call to action.

## 2. Brainstorm

Run the `kvb-think-brainstorm` skill on this channel's angle and opening hook
for its audience; keep the strongest.

## 3. Write, per language

1. Title: lead with the headline benefit in the reader's words; a project
   skill may prefix the version.
2. Lead: what the reader can do now, in two or three sentences.
3. One section per benefit: the effect first, then the proof from its
   changelog lines. A benefit the brief cannot prove is left out, never
   filled with a placeholder.
4. Upgrade notes, when the brief has any, as plain steps.
5. Close with one call to action and the brief's links.

The audience shapes the words: customers read benefits, developers read the
mechanism and the upgrade path, investors read only what the brief proves.

## 4. Rules

- Every number, name and date comes from `brief.yml`.
- No em dashes, no superlative the brief does not prove.
- Stay inside the channel's length bounds. Without project bounds: a blog
  article 600 to 1200 words, a LinkedIn article 400 to 900, a newsletter
  250 to 500.
- Write `/tmp/release-<version>/<channel>/<language>.md`, or the format the
  project's template names, and report each file's word count.
