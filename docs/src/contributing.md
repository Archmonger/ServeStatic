# Contributing

## Tool Setup

### `python`

To contribute code or documentation updates, an installation of Python 3 is required.

### `hatch`

This project utilizes [`hatch`](https://hatch.pypa.io/latest/) to manage Python environments for development and testing.  Follow
[the `hatch` installation instructions](https://hatch.pypa.io/latest/install/) before continuing through this document.

### `pre-commit`

Additionally, this project uses [`pre-commit`](https://pre-commit.com/) Git hooks to run linting and formatting checks against each commit.  See [the `pre-commit` installation instructions](https://pre-commit.com/#install) for how to install this tool.

Once installed, run `pre-commit install` to set up the git hook scripts:

``` shell
$ pre-commit install
pre-commit installed at .git/hooks/pre-commit
```

### Git

Clone the repository using:

``` shell
git clone https://github.com/Archmonger/ServeStatic.git
cd ServeStatic
```

All example commands are exected to be run from the `ServeStatic` folder.

## Code Contributions

Ensure you have followed the [tool setup](tools.md) instructions before following the instructions below.

### Development

#### Linting

The project uses `flake8` and `isort` for linting and uses `black` to format code.  To run the all linters:

``` shell
hatch run lint:check
```

Or select a specific linter:

``` shell
hatch run lint:flake8
```

!!! tip

    Linting is likely to see an update in the near future to use `ruff` for linting and formatting.

### Testing

Tests are run aross a matrix of Python and Django versions to ensure full compatibility with all supported versions.

#### Full Test Suite

To run the full test suite, using the system Python:

``` shell
hatch test
```

To select a particular Python version:

``` shell
hatch test --python 3.9
```

!!! tip

    `hatch` can manage Python versions for you, for example installing Python 3.9: `hatch python install 3.9`

    See the [hatch documentation](https://hatch.pypa.io/latest/tutorials/python/manage/)

To select a particular Django version:

``` shell
hatch test --include "django=5.1"
```

#### Specific Test(s)

To run only a specific test:

``` shell
hatch test -k test_get_js_static_file
```

!!! tip

    Additional arguments are passed on to pytest.

    See the [pytest documentation](https://docs.pytest.org/en/8.3.x/reference/reference.html#command-line-flags) for options

## Documentation Contributions

Ensure you have followed the [tool setup](tools.md) instructions before following the instructions below.

### Modifying Documentation

1. Start the `mkdocs` server by running `hatch run docs:serve`
1. Visit http://localhost:8000/ in your preferred browser
1. Edit the documentation.  The site will load change as documentation files change.
