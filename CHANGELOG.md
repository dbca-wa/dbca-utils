# Changelog

## 3.0.16 (2026-11-03)

- Security: restrict SSO logout redirects to relative URLs and trusted DBCA domains.
- Match configured logout paths exactly (ignoring a trailing slash) rather than by prefix.
- Normalise `REMOTE_USER` and `X-Email` SSO headers (trim whitespace, lowercase email) and compare email addresses case-insensitively.
- Add a `GROUP_SEPARATOR` setting for parsing Auth2 groups (default `,`), trim group names, and fall back safely when the separator is empty.
- Fix `ALLOWED_EMAIL_SUFFIXES` handling and validate that configured suffixes are strings.
- `env()` now treats blank or whitespace-only values as unset for `int` and `float` types, using the default or raising when required.
- Fix `ActiveMixin.delete()` so `force=True` performs a hard delete; the default remains a soft delete.
- `AuditMixin` change tracking now re-baselines after `save()`, `refresh_from_db()` and soft delete, so saved changes are no longer reported.
- Healthcheck: normalise incoming workload mappings, avoid `KeyError` when selecting the oldest workload, and fix off-by-one workload cleanup.
- Added unit tests for the middleware, model and environment changes; README updates (`PORT` -> `WORKLOAD_PORT`).

## 3.0.15 (2026-10-21)

- Update dependencies to address security advisories, including a `sqlparse` CVE.
- Refresh GitHub Actions workflows and Dependabot configuration (weekly checks, cooldown).

## 3.0.14 (2026-08-14)

- Refactor Auth2 group synchronisation into `SSOLoginMiddleware` and add unit tests.
- Attach `AnonymousUser` to unauthenticated requests and optimise user lookup.
- Validate configured email suffix values.
- Move static data initialisation out of `process_request`.
- Fix double-counting of `cpu_total` in the healthcheck summary.
- Migrate tox configuration into `pyproject.toml`, switch the build backend to `uv_build`, and update `pytest-django`.

## 3.0.13 (2026-07-29)

- Restructure the health data output and fix issues found during testing.

## 3.0.12 (2026-07-28)

- Healthcheck: fix typos, add comments, and remove unbounded `while` loops.
- Remove the unused `urls.py` module and settings import.
- Add `requests` and `psutil` as dependencies.

## 3.0.11 (2026-07-27)

- Adjust health data for StatefulSet workloads.

## 3.0.10 (2026-07-24)

- Move `currentworkload` into the `summary` section of the health data.

## 3.0.9 (2026-07-24)

- Only include `currentprocess`, `currentworkload` and `cmdline` in health data when debug mode is enabled.

## 3.0.8 (2026-07-23)

- Use `psutil` instead of `ps` to collect process resource data.
- Update healthcheck environment variables and README.

## 3.0.7 (2026-07-03)

- Fix an indentation issue in the healthcheck code.

## 3.0.6 (2026-07-03)

- Match volumes by their `source` rather than `target` when harvesting volume usage.

## 3.0.5 (2026-07-03)

- Harvest usage data for volumes whose source starts with `//`.

## 3.0.4 (2026-07-03)

- Harvest volume usage data in the healthcheck.

## 3.0.3 (2026-06-29)

- Disable cache timeouts for the `workloads` and `assignedworkloads` cache keys.

## 3.0.2 (2026-06-29)

- Version bump only.

## 3.0.1 (2026-06-29)

- Fix healthcheck handling of failed workloads whose cached data is a string rather than a dict.

## 3.0.0 (2026-06-29)

- Add the healthcheck Django app and view for harvesting workload resource data.
- Add `/healthcheck/healthdata` and `/workload/healthcheck/healthdata` endpoints.
- Add healthcheck configuration via environment variables.
- Update dependencies.

## 2.2.0 (2026-05-13)

- Drop support for Python 3.10 and 3.11, add support for Python 3.14.
- Drop support for Django 4.2 and 5.0, add support for Django 6.0.

## 2.1.5 (2025-10-31)

- Bugfix: `last_name` was incorrectly replaced by `first_name` in SSOLoginMiddleware.

## 2.1.4 (2025-10-14)

- Drop Django 4.0 support.
- Bump project dependencies.

## 2.1.3 (2025-04-29)

- Update `SSOLoginMiddleware` to sanitise user-supplied name input values.

## 2.1.2 (yanked)

## 2.1.1 (2025-04-10)

- Define the build system in `pyproject.toml` (missed in the switch to uv).

## 2.1.0 (2025-04-07)

- Switch to using uv as the project build system.
- Drop support for Python 3.9 and Django 3.2, add support for Python 3.13 and Django 5.2.
- Update `pyproject.toml` metadata to the modern format and PEP 508 dependency declarations.
- Add unit tests for `utils.env`.
- Add a security policy.
- Update GitHub workflows to use uv and tox-uv.
- Update README.

## 2.0.3 (2024-12-19)

- Refactor project layout to use Poetry as the build system, `pyproject.toml` to maintain metadata and configuration.
- Add unit tests.
- Add additional GitHub workflows.

## 2.0.2 (2024-03-05)

- Set `last_login` to the current time when creating a new user on SSO login.

## 2.0.1 (2024-02-22)

- Restore Auth2 user group synchronisation that was accidentally removed in 2.0.0.
- Add a GitHub Actions CI workflow.

## 2.0.0 (2024-02-15)

- Refactor `SSOLoginMiddleware` for Django 3.2+ and remove deprecated code paths.
- Remove `AuditMiddleware`, `SimpleLazyUser` group patching and the deprecated `curry` helper.
- Remove the `dbca_utils.requests` API.
- Improve error messages in `utils.env` and correct the license text.

## 1.1.6 (2022-03-21)

- Drop support for Python 3.6, Django 2.1 and 3.1; add support for Django 3.2.

## 1.1.5 (2021-08-23)

- Fix a bug when looking up groups by name during Auth2 user group synchronisation.

## 1.1.4 (2021-06-22)

- Add the `LOCAL_USERGROUPS` setting to prevent Auth2 from modifying locally managed group memberships.
- Trim whitespace from members of comma-separated group lists.
- Replace the `.flake8` configuration with `setup.cfg`.

## 1.1.3 (2021-06-22)

- Change the Auth2 group separator from `.` to `,`.
- Remove Python 3.5 from supported versions.
- Reformat the codebase with Black and clean up unused imports.

## 1.1.2 (2021-06-15)

- Populate Django auth groups from Auth2 groups, with backward compatibility for existing group memberships.
- Update license year.

## 1.1.1 (2020-02-06)

- Version bump only.

## 1.1.0 (2020-02-06)

- Add Django 3.0 compatibility.
- Formatting and cleanup fixes.

## 1.0.2 (2019-08-29)

- Add type conversion logic to `utils.env`.

## 1.0.1 (2019-03-07)

- Fix packaging configuration in `setup.py` to include the package correctly.

## 1.0.0 (2018-12-13)

- Initial release: SSO login middleware, audit model mixin and middleware, environment helper, and requests API.
