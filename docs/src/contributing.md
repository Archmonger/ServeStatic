## Creating a development environment

If you plan to make code changes to this repository, you will need to install the following dependencies first:

-   [Git](https://git-scm.com/downloads)
-   [Python 3.9+](https://www.python.org/downloads/)
-   [Hatch](https://hatch.pypa.io/latest/)

Once you finish installing these dependencies, you can clone this repository:

```shell
git clone https://github.com/Archmonger/ServeStatic.git
cd ServeStatic
```

## Executing test environment commands

By utilizing `hatch`, the following commands are available to manage the development environment.

### Tests

| Command | Description |
| --- | --- |
| `hatch test` | Run Python tests using the current environment's Python version |
| `hatch test --all` | Run tests using all compatible Python and Django versions |
| `hatch test --python 3.9` | Run tests using a specific Python version |
| `hatch test --include "django=5.1"` | Run tests using a specific Django version |
| `hatch test -k test_get_js_static_file` | Run only a specific test |

??? question "What other arguments are available to me?"

    The `hatch test` command is a wrapper for `pytest`. Hatch "intercepts" a handful of arguments, which can be previewed by typing `hatch test --help`.

    Any additional arguments in the `test` command are directly passed on to pytest. See the [pytest documentation](https://docs.pytest.org/en/stable/reference/reference.html#command-line-flags) for what additional arguments are available.

### Linting and Formatting

| Command | Description |
| --- | --- |
| `hatch fmt` | Run all linters and formatters |
| `hatch fmt --check` | Run all linters and formatters, but do not save fixes to the disk |
| `hatch fmt --linter` | Run only linters |
| `hatch fmt --formatter` | Run only formatters |
| `hatch run precommit:check` | Run all [`pre-commit`](https://pre-commit.com/) checks configured within this repository |
| `hatch run precommit:update` | Update the [`pre-commit`](https://pre-commit.com/) hooks configured within this repository |

### Documentation

| Command | Description |
| --- | --- |
| `hatch run docs:serve` | Start the `mkdocs` server to view documentation locally |
| `hatch run docs:build` | Build the documentation |
| `hatch run docs:linkcheck` | Check for broken links in the documentation |

??? tip "Configure your IDE for linting"

    This repository uses `hatch fmt` for linting and formatting, which is a [modestly customized](https://hatch.pypa.io/latest/config/internal/static-analysis/#default-settings) version of [`ruff`](https://github.com/astral-sh/ruff).

    You can install `ruff` as a plugin to your preferred code editor to create a similar environment.
