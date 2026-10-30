# Advocate: the checks

Apply each check to a target the `advocate` skill found in scope.

1. **Inbound code** - every file or block of foreign origin carries a licence
   that the project licence can absorb in the direction of distribution. GPL
   code cannot enter a project distributed under MIT without relicensing the
   whole; Apache-2.0 cannot enter GPL-2.0-only; code without a licence is all
   rights reserved.
2. **Dependency licences** - for each added or bumped dependency, read the
   licence of the resolved version (lockfile, registry metadata, or the
   package's own LICENSE), including the transitive dependencies the lockfile
   newly pulls. Watch copyleft reach (GPL, AGPL's network clause, LGPL static
   versus dynamic linking), source-available terms that are not open source
   (SSPL, BUSL, Commons Clause, "non-commercial"), and an upstream relicensing
   between the old and the new version.
3. **Project licence fit** - the project's declarations still hold against
   what checks 1 and 2 found: a dependency that forces copyleft forces either
   the project licence or the dependency's removal.
4. **Attribution** - retained copyright notices, the licence text shipped
   where required, an Apache-2.0 NOTICE propagated, modified-file notices
   (Apache-2.0 §4(b), GPL-3.0 §5(a)), SPDX headers where the project uses them,
   credit for CC BY material.
5. **Copied snippets** - Stack Overflow content is CC BY-SA (attribution plus
   share-alike); gists, blog posts, other repositories, and verbatim
   reproductions of well-known code need a traceable origin and licence.
   Trivial code without originality (one-liners, usage dictated by an API) is
   not a finding.
6. **Data protection (GDPR, TDDDG)** - new collection, storage, logging, or
   transfer of personal data; IP addresses sent to third parties through
   external fonts, CDNs, analytics, or embeds; storage on the user's device
   without consent (§ 25 TDDDG); transfers outside the EU. Name the data flow
   and the missing legal basis or consent mechanism.
7. **Trademarks and branding** - third-party logos, icons, and product names
   used beyond plain reference: implied endorsement, use in the project's own
   name, modified logos. Icon sets carry their own licence, and a free licence
   on an icon does not license the trademark it depicts.
