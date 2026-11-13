# Tables and message block

Each flag replaces the two lines; values, gate and exit code stay:

- `--table`: one markdown table, `| 🎯 Fix | 💥 Break | 💸 Tokens |
  ⏱️ Velocity | 🛡️ Security | 🏆 Score | Gate |`.
- `--commit-table <repo>`: that table led by `🌿 Branch | 📊 Diff stat`
  from git, 📁 worktree path below, alone in a code block. Every commit
  block is this table; after the commit, `--commit <sha>` shows that commit's diff stat
  and a `🔖 Commit` column.
- `--message-block`: one value per line, `🎯 Fix: <f> %` through
  `🏆 Score: <n>` and `🚦 Gate: <verdict>`. Every commit message carries it
  as its own paragraph right before the `Co-Authored-By` line, passed as one
  `-m` argument, so the approval prompt and git history show the values.

On a skill change add `--value <n:n|?>`, the quotient of the 💰 line (`?`
while it has no value): a `💰 Value` column after `💸 Tokens`, or line
after `🛡️ Security`. It changes neither score nor gate; alone it is a usage
error.
