# Documentation Standards and Formatting

This guide outlines the documentation standards for the Linux AI NPU Assistant project. It serves as a reference for developers to ensure consistency across the codebase and the generated MkDocs site.

---

## The Standards

The project uses [MkDocs](https://www.mkdocs.org/) with the [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) theme for site generation. Auto-generated API documentation is handled by the `mkdocstrings[python]` plugin.

-   **Configuration (`mkdocs.yml`)**: The `mkdocstrings` plugin is configured to parse docstrings using the **Google style** (`docstring_style: google`).
-   **Source Code**: All modules use the **Google style**.

To ensure clean, maintainable, and correctly rendered documentation, all new code and updates to existing code should adhere to the following standards:

### 1. Adopt Google-Style Docstrings

The **Google style** is recommended over the NumPy style because:

1.  **Conciseness**: It uses less vertical space (fewer lines of hyphens) while remaining highly readable.
2.  **Compatibility**: It matches the existing `mkdocstrings` configuration in `mkdocs.yml`.
3.  **Widespread Adoption**: It is highly prevalent in modern Python projects.

#### Example: Google Style (Recommended)

```python
def load(path: str | Path | None = None) -> Config:
    """Load configuration, merging user file over built-in defaults.

    Args:
        path: Explicit path to a `config.yaml` file. When None, the function searches
            the default search paths in order and uses the first file it finds. If no
            file is found, the built-in defaults are used as-is.

    Returns:
        The loaded configuration object.
    """
    ...
```

### 2. Rely on Python Type Hints

Do **not** duplicate type information in the docstring.

-   **Do**: Use standard Python type hints in the function signature (`def func(arg: int) -> str:`).
-   **Don't**: Write `Args: arg (int): The argument...` in the docstring.

The `mkdocstrings` plugin automatically extracts type hints from the signature and renders them beautifully in the API documentation. Duplicating them in the docstring creates maintenance overhead and can lead to conflicting information if the signature is updated but the docstring is forgotten.

### 3. Markdown Features in Docstrings

Because `mkdocstrings` processes docstrings as Markdown, you can use standard Markdown features to enhance readability:

-   Use single backticks for inline code, variable names, or short literals (e.g., `None`, `True`).
-   Use double backticks for cross-references to other elements (e.g., `` `config.yaml` `` or `` :class:`ExternalNetworkBlockedError` `` if using Sphinx-style roles for cross-linking, though standard Markdown is preferred unless cross-linking is explicitly configured).
-   Use standard Markdown lists (`-` or `1.`) for enumerations.

### 4. Module-Level Docstrings

Every Python module should have a docstring at the very top of the file, immediately after the license header.

-   The first line should be a brief, one-sentence summary.
-   Subsequent paragraphs can provide a deeper explanation of the module's purpose.
-   If the module has specific responsibilities or acts as a central hub (like `src.security`), use a Markdown heading (e.g., `## Responsibilities`) followed by a bulleted list to clearly outline them.

### 5. Private vs. Public Members

By default, the `mkdocs.yml` configuration hides private members (those starting with an underscore `_`) from the generated documentation (`filters: ["!^_"]`).

-   Only document internal functions/classes if they are complex and require explanation for other developers working on the codebase.
-   Focus documentation efforts on public APIs that users or other modules will interact with.

### 6. Exception and Return Formatting

Ensure that `Raises` and `Returns` sections follow the strictly required syntax for `mkdocstrings[python]` to parse them correctly:

-   **Returns**: Describe the return value directly. **Do not** specify the return type in the docstring (rely on the function signature's type hint).
    -   *Correct*:
        ```python
        Returns:
            The loaded configuration object.
        ```
    -   *Incorrect* (specifying the type before the description):
        ```python
        Returns:
            Config: The loaded configuration object.
        ```
    -   *Incorrect* (putting the description on a new line):
        ```python
        Returns:
            Config:
                The loaded configuration object.
        ```

-   **Raises**: Format exceptions as `ExceptionType: Description` on a single line. The `mkdocstrings` plugin requires the exception and description to be on the same line to correctly parse it.
    -   *Correct*:
        ```python
        Raises:
            ValueError: If the configuration file is invalid.
        ```
    -   *Incorrect* (description on the next line):
        ```python
        Raises:
            ValueError:
                If the configuration file is invalid.
        ```
