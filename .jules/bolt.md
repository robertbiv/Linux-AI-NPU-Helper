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

## 2025-02-27 - [Optimizing Path.parts for hidden file checks]
**Learning:** Instantiating a `pathlib.Path` object and accessing `.parts` just to check for hidden path components (e.g., `any(part.startswith(".") for part in Path(path).parts)`) is incredibly slow. Profiling revealed it takes ~1.3 seconds for 10,000 iterations, whereas simple string checks (`if "/." not in path and not path.startswith(".")`) and splitting (`path.split("/")`) accomplish the exact same behavior in ~0.2 seconds—up to 30x faster for paths without hidden components, and 5x faster for paths with them.
**Action:** Replace `Path(path).parts` with direct string manipulation (`in` checks and `.split("/")`) in hot loops like `_has_hidden_component` that process thousands of file paths.

## 2025-02-28 - [Optimizing proc parsing with string search]
**Learning:** Parsing large text files like `/proc/[pid]/status` or `/proc/meminfo` line-by-line using `splitlines()` within a loop is a significant performance anti-pattern due to excessive string object allocations, especially when repeated across thousands of processes (e.g., in `process_info.py`).
**Action:** Instead of `splitlines()`, use native string operations: find the exact index with `.find('Field:')` and extract the target value using slicing up to the next newline (`end = text.find("\n", idx)`). This approach is up to 4x faster and prevents thousands of temporary string allocations in hot paths like `_proc_mem_kb()`.

## 2025-03-01 - [Optimizing regex parsing of large text outputs]
**Learning:** When parsing large multi-line text outputs (like results from `grep` or `rg`) for regex matches, calling `text.splitlines()` and iterating through every line to apply `.match()` creates immense memory allocation overhead.
**Action:** Instead, append `re.MULTILINE` to the compiled regular expression and use `pattern.finditer(text)`. This allows the C-level regex engine to scan the single string lazily without allocating millions of temporary string objects. In benchmarks, this reduces parsing time by over 300x (e.g., from ~1.9s down to ~0.005s) when searching for limited results.
### 2025-05-14
- Caching desktop environment detection in `src/gui/theme.py` using `@lru_cache(maxsize=1)` resulted in a ~45x performance improvement (from 3.08μs to 0.07μs per call).
- When caching functions that depend on environment variables, ensured tests clear the cache using `func.cache_clear()` to maintain test isolation.

## 2025-05-14 - [Optimizing proc parsing in system_info.py]
**Learning:** Parsing large system files like `/proc/meminfo` and `/proc/cpuinfo` line-by-line using `splitlines()` within a loop is a significant performance bottleneck due to excessive string object allocations for every line. Profiling showed that using `splitlines()` can be up to 6x slower than using native string operations.
**Action:** Instead of `splitlines()`, use native string operations like `.find()` and slicing for targeted field extraction (e.g. `_query_memory()`), or use `re.finditer` with `re.MULTILINE` (e.g. `_query_cpu()`) to allow the C-level engine to lazily scan the string without allocating massive amounts of temporary line strings.
2024-05-24: Documented that `lru_cache` optimization for `detect_desktop_environment` was successfully implemented and measured to provide a 30x speedup in caching DE detection logic. (Task was to optimize, but code already had it).
2024-05-24: Fixed implicit GitHub Action `submit-pypi` failure due to deprecated node20 version and lack of `contents: write` permissions by explicitly overriding the workflow with `.github/workflows/dependency-submission.yml` configured to use node24 environment.
