# Tune: unnecessary recursion

Look for:

- a recursive function that recomputes the same subproblem: memoize it or
  turn it into a loop;
- recursion that only walks a list or a fixed depth: a loop;
- a tree walk that visits or reads the same node more than once;
- depth that grows with the input (stack limits, Python's 1000 frames);
- recursive tool calls: a make target calling make, a role or playbook
  including itself, a script re-invoking itself per item.

Count the calls first (a profiler's call graph, cProfile's `ncalls`, log
lines); recursion that is bounded, rare and cheap stays.
