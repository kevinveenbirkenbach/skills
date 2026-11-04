# Proposal

When the bar is out of reach (the deciding evidence, such as a live deploy, a
production-like dataset or an upstream answer, is not available, or the change
is inherently riskier), the agent stops trying and submits a proposal:

- what the change does and why it is worth having;
- the `kvb-check-score` block it reached, with residuals: which part of the
  bar it misses (fix confidence ≥ 90 %, break risk ≤ 5 %, efficiency and
  speed ≤ 100 %), and the cause of any efficiency or speed over 100 %, which
  the operator weighs before the commit;
- exactly which evidence would close the gap, and what obtaining it costs;
- where the work lives (branch and commit), so nothing has to be redone;
- a recommendation: apply after that evidence, apply now with a named risk, or
  drop.

The operator decides. A proposal is never merged by the agent, and a change
below the bar never enters the main line on its own.
