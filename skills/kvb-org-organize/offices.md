# Offices

- **President of a piece of work** (`work/<slug>`): the first agent that
  starts it. It does the whole piece.
- **Representative of an organisational line** (`<dimension>/<line>`): the
  first agent that works in the line. Lines come in as many dimensions as are
  useful: functional domain (security, GUI, identity, i18n), repository,
  branch line, host, cloud account. An agent belongs to one line per
  dimension.
- **Organiser of a work cluster** (`cluster/<slug>`): the first agent that
  starts a cluster cutting across lines (a failure cluster from
  `kvb-ci-triage`, a cost cluster from `kvb-code-tune`, a feature touching
  several domains). It works the strand end to end and informs the
  representative of every line the strand touches before it changes that
  line's files.
- **Chair** (`chair`): the earliest-elected president still running. It
  chairs the council of all representatives and organisers and allocates the
  resources of the whole system everyone runs on (`capacity.md`). There is
  exactly one allocator at any time.
