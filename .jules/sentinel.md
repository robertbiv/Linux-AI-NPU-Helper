## 2025-02-27 - [Security Enhancement: Prevent DoS via `math` evaluation in AST]
**Vulnerability:** Extremely large numbers passed to `math.factorial`, `math.comb`, `math.perm`, or `math.pow` during `ast.parse` in `CalculatorTool` lead to CPU starvation or memory exhaustion (Denial of Service). Additionally, `ast.Attribute` resolution directly fetched attributes from the `math` module via `getattr(math, attr)`, which completely bypassed `_MATH_NAMES` safety wrappers.
**Learning:** `eval_ast` functions must strictly sanitize function resolution paths. Allowing untrusted AST attributes to use `getattr` on real modules bypasses custom safety limits entirely. Functions that perform exponential or combinatorial scaling must have fixed bounds limits in any public/AI facing sandbox to prevent DoS.
**Prevention:**
1. Wrap all computationally expensive standard library functions (like `math.factorial`) in custom functions that check bounds before evaluating.
2. Resolve `ast.Attribute` evaluations strictly against a pre-populated allow-list mapping dictionary (`_MATH_NAMES`) rather than delegating dynamically back to module scope (`getattr(module, attr)`).

## 2026-04-22 - [Security Enhancement: Prevent XSS in PyQt5 Status Widget]
**Vulnerability:** The `_kernel_line` function in `src/gui/status_widget.py` rendered user-supplied text directly into a Qt `QLabel` parsing `Qt.RichText`, allowing malicious inputs to inject arbitrary HTML tags and execute JavaScript context logic.
**Learning:** When displaying dynamic command names or tool status in rich text UI frameworks, failing to escape inputs can introduce Cross-Site Scripting (XSS) type vulnerabilities within desktop application environments.
**Prevention:** Always use `html.escape()` around untrusted string variables before substituting them into formatted HTML strings destined for Rich Text labels.

## 2025-02-27 - [Security Enhancement: Prevent SSRF Bypass via DNS Resolution]
**Vulnerability:** The `_is_private_ip` check in `web_fetch.py` only checked if a host string matched `"localhost"` or `"::1"` or parsed directly as a local IP address using `ipaddress.ip_address`. This could be bypassed using public hostnames configured to resolve to loopback IPs (e.g. `localtest.me` resolving to `127.0.0.1`).
**Learning:** Checking hostnames directly against IP-based rules is insufficient for SSRF protection because attackers can control DNS records.
**Prevention:** Resolve the hostname into an IP address first (e.g., via `socket.gethostbyname`) before verifying if it falls within loopback/private ranges.

## 2025-02-27 - [Security Enhancement: Ensure Full SSRF Protection Across All Network Guards]
**Vulnerability:** While `web_fetch.py` was updated previously to resolve DNS for SSRF protection, the centralized URL guard `is_local_url` in `src/security.py` still lacked DNS resolution. This meant the `ai_assistant.py` (which uses `assert_local_url` / `is_local_url` for backend API routing) could still be bypassed by using public hostnames configured to resolve to loopback IPs (e.g. `localtest.me` resolving to `127.0.0.1`).
**Learning:** Security fixes for a specific vulnerability class (e.g. SSRF bypass) must be audited across the entire codebase to ensure no centralized utilities or secondary paths are left exposed.
**Prevention:** Always update the central security utilities (`src/security.py`) when discovering a network boundary bypass, and perform a codebase-wide audit for similar logic.

## 2025-04-25 - [SSRF Bypass via Redirects and DNS Rebinding]
**Vulnerability:** The web_fetch tool was vulnerable to SSRF bypasses because it resolved DNS twice (once for validation and once via `requests`) allowing for DNS rebinding attacks. Also, `requests` automatically followed redirects by default, allowing attackers to supply an external URL that redirects to internal endpoints (like localhost).
**Learning:** Checking a domain for a private IP must be coupled with strict control over exactly what URL is fetched. Relying on default HTTP client redirection behaviors or independent DNS lookups creates bypasses. Also, DNS resolution failures must fail-closed.
**Prevention:** Always follow redirects manually to validate every redirect target. Ensure DNS resolution failures result in blocking the request (fail-closed), or better yet, inject the resolved IP into the request so DNS rebinding is impossible.
