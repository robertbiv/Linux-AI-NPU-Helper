## 2025-02-27 - [Security Enhancement: Prevent DoS via `math` evaluation in AST]
**Vulnerability:** Extremely large numbers passed to `math.factorial`, `math.comb`, `math.perm`, or `math.pow` during `ast.parse` in `CalculatorTool` lead to CPU starvation or memory exhaustion (Denial of Service). Additionally, `ast.Attribute` resolution directly fetched attributes from the `math` module via `getattr(math, attr)`, which completely bypassed `_MATH_NAMES` safety wrappers.
**Learning:** `eval_ast` functions must strictly sanitize function resolution paths. Allowing untrusted AST attributes to use `getattr` on real modules bypasses custom safety limits entirely. Functions that perform exponential or combinatorial scaling must have fixed bounds limits in any public/AI facing sandbox to prevent DoS.
**Prevention:**
1. Wrap all computationally expensive standard library functions (like `math.factorial`) in custom functions that check bounds before evaluating.
2. Resolve `ast.Attribute` evaluations strictly against a pre-populated allow-list mapping dictionary (`_MATH_NAMES`) rather than delegating dynamically back to module scope (`getattr(module, attr)`).
