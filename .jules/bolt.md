## 2025-02-23 - [Optimizing Path Iteration in process_info.py]
**Learning:** Instantiating `pathlib.Path` objects and calling `.exists()` on each generated path for large directories like `/proc` is incredibly slow.
**Action:** Replace `Path("/proc").iterdir()` and `(p / "stat").exists()` with `os.scandir("/proc")` and `os.stat()` which is ~3.8x faster by avoiding heavy object instantiations. Crucial pattern for system-level tools querying `/proc` or `/sys` directories containing thousands of entries.

## 2025-02-24 - [Refactoring Path.iterdir to os.scandir]
**Learning:** When refactoring `pathlib.Path.iterdir()` to `os.scandir()` for performance, note that `os.scandir()` yields `os.DirEntry` objects rather than `Path` objects. Path concatenations using the slash operator (e.g., `entry / "file"`) will fail with a `TypeError` and must be updated to use strings (e.g., `f"{entry.path}/file"`). Also, ensure that the iteration context manager (`with os.scandir(...) as it:`) encompasses only what is necessary, and take care to maintain the exact logic flow and indentation.
**Action:** When performing this optimization, carefully review the entire loop body and update all property access and path operations on the loop variable to be compatible with `os.DirEntry` (using `.name`, `.path`, `.is_file()`, etc.).

## 2025-02-25 - [AppTool .desktop caching optimization]
**Learning:** Instantiating `pathlib.Path` objects via `Path.glob` and then calling `read_text()` on each file can be surprisingly slow for high-volume reads (like `/usr/share/applications/`). Using `os.scandir` to yield `os.DirEntry` objects and standard `open()` is over 2x faster, avoiding string allocations and heavy abstractions. Additionally, freedesktop `.desktop` specifications mandate UTF-8, so adding `encoding='utf-8'` instead of relying on the system default makes the parsing both faster and more correct.
**Action:** Replaced `Path.glob` with `os.scandir` in `_load_desktop_cache` for `AppTool`. The cache loads in ~4ms instead of ~8-9ms.

## 2025-02-26 - [Deferring expensive file reads in sorting operations]
**Learning:** In tools reading `/proc` or similar file systems, iterating over all entries to read expensive properties (like `cmdline` or `name` via `read_sys_file()`) *before* sorting is a significant performance bottleneck. For operations like finding the top 10 CPU/Memory processes, fetching those fields for hundreds of processes that won't even make the top 10 is unnecessary.
**Action:** When filtering and sorting top N items from a large list, collect only the bare minimum fields required for sorting into a simple tuple/list (e.g. `(pid, mem_kb)`), sort it, slice to the top N, and *then* perform the expensive I/O operations (like reading `/proc/[pid]/cmdline`) only on those top N items. This simple change reduces execution time of `top_mem` and `top_cpu` significantly.
