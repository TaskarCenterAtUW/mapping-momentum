<!-- @format -->

# Contributing

This project does not currently accept external contributions.

---

## Version Control & Workflow

This project follows standardized version control conventions:

### Semantic Versioning

Use [Semantic Versioning](https://semver.org/) (MAJOR.MINOR.PATCH):

- **Major (X.0.0)**:
    - New major features or upgrades
- **Minor (0.X.0)**:
    - Significant changes to core features
- **Patch (0.0.X)**:
    - Minor fixes, fixing typos, doing chores

### Conventional Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat: description`
- `fix: description`
- `chore: description`

Examples:

```
feat: add support for unit conversion
feat: add new rolling average chart type
fix: resolve variable type issue
fix: correct typo in comment
chore: update changelog
```

### Branch Naming

Use structured branch names:

**Format**: `<devops-work-item-number>-short-description`

**Examples**:

```
1234-add-unit-conversion-support
1024-add-rolling-average-chart
9876-fix-variable-type-issue
2048-fix-typo-in-comment
```

### Pull Request & Release Process

1. Create a branch following the naming convention
2. Make commits using conventional commit format
3. Open a pull request to `main` and merge it

#### Changelog & Tagging a Release

Changelog entries and version numbers are managed manually in `CHANGELOG.md`.

1. Determine the correct [Semantic Version](https://semver.org/) bump and prepend a versioned and dated section with new `### Features` / `### Fixes` entries to `CHANGELOG.md`.

2. Commit the changelog update last:

    ```
    chore: update changelog for vX.Y.Z
    ```

3. On the GitHub website, go to **Releases** → **Draft a new release**.
    1. In **Choose a tag**, type the new version (e.g. `v12.3.4`) and select **Create new tag on publish**.
    2. Set the title to `vX.Y.Z`.
    3. Paste the release summary as the description.
    4. Click **Publish release**.

### Getting Started (Windows 10/11)

This section of the guide explains how to set up a Windows environment for contributing to Mapping Momentum for the first time.

1. Install [Visual Studio Code](https://code.visualstudio.com/)

2. Clone the repository

    ```powershell
    git clone https://github.com/TaskarCenterAtUW/mapping-momentum
    cd mapping-momentum
    ```

3. Install [Python 3](https://www.python.org/downloads/)

4. Set up Python virtual environment
    1. Create the virtual environment

        ```powershell
        python3 -m venv .venv
        ```

    2. Activate the virtual environment

        ```powershell
        .\.venv\Scripts\Activate.ps1
        ```

5. Install requirements

    ```powershell
    pip install -r requirements.txt
    ```
