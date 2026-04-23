1. Modify `src/tools/web_fetch.py` `_is_private_ip(host: str) -> bool` function to resolve hostnames to IP addresses using `socket.gethostbyname()` and then check if the IP is private.
   Currently, the function only checks `if host.lower() in ("localhost", "::1")` and if the host *string* is directly parsable as a private IP via `ipaddress.ip_address`. This means domains that resolve to loopback/private IPs (e.g. `localtest.me` or an attacker-controlled DNS `my-private-ip.attacker.com` pointing to `127.0.0.1`) bypass the SSRF protection. We will import `socket` and use `socket.gethostbyname(host)` to resolve the host and then pass it to `ipaddress.ip_address(ip)` to check if it's loopback/private. We will handle any exceptions during resolution (e.g. `socket.gaierror`) by allowing it to fall through or return False (if it can't resolve, `requests` won't be able to fetch it either, or we let `requests` fail).

2. Modify `tests/test_web_fetch.py` to add a test for DNS resolution of SSRF.
   We can mock `socket.gethostbyname` to return `127.0.0.1` for a fake domain like `attacker.com` and ensure `_is_private_ip` returns `True`.

3. Complete pre commit steps to ensure proper testing, verification, review, and reflection are done.

4. Submit the change with a clear security PR message.
