# After the merge

A merged sidetree leaves nothing behind, so the next round starts from a clean
machine. Work through the list in this order, verifying each step instead of
assuming it:

1. **Stop its jobs**: background runs, watchers, scheduled loops and agents
   that belong to the sidetree.
2. **Tear down its stacks**: compose projects and swarm or test clusters
   together with their volumes and networks, and the containers and images
   built only for it. Leave anything another worktree still uses.
3. **Clear files the containers left**: count the entries the user does not
   own (`find <worktree> -not -user "$USER" -prune | wc -l`). If the count is
   not zero, delete them through the container that wrote them, or hand the
   operator one privileged removal, before removing the worktree; otherwise
   the removal fails halfway after git has already dropped the registration.
4. **Remove the worktree** and its registration. Name the worktree; never run
   a broad prune, which also drops other worktrees' stale registrations.
5. **Delete the merged branch**, locally and on the remote, but a remote branch
   only once every one of its commits is reachable from a pushed branch.
6. **Release what it held**: slots, port or subnet reservations, locks, its
   `kvb-org-organize` claims and every claim announced to other agents. The
   freed slot and the released claims go to the chair and the peers as one
   `${CLAUDE_SKILL_DIR}/../kvb-org-organize/scripts/news.py post "<text>"`,
   not as messages. Drop each removed item from the `kvb-org-rasci` register
   with `--drop-artifact` and set the subagent's task `done` or `stopped`.
7. **Remove its temporary files**: logs, message files and scratch data that
   have served their purpose. Keep only the evidence the report cites, until
   the report is delivered.

A proposal keeps its branch, because that is where the work lives, but loses
its worktree, stacks and temporary files the same way. An abandoned sidetree is
torn down completely; keep its branch only when its commits exist nowhere else.
