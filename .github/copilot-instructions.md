# Quick Rules for dbca-utils

## Scope

- Django utilities package (Python 3.12+, Django 5.2+).
- Runtime code: src/dbca_utils.
- Tests and fixtures: tests.

## Core API Snapshot

- utils.env(key, default=None, required=False, value_type=None): env read + coercion for str/list/tuple/bool/int/float.
- models.ActiveMixinManager.current/deleted: active vs soft-deleted query helpers.
- models.ActiveMixin.delete(force=False): soft delete by default via effective_to; hard delete only with force=True.
- models.AuditMixin.has_changed/changed_data: change tracking excluding modified and modifier_id.
- middleware.sync_usergroups: reconcile auth groups, preserving LOCAL_USERGROUPS.
- middleware.SSOLoginMiddleware.process_request: SSO login/logout flow, input sanitization, optional email suffix restriction, optional group sync.

## Coding Conventions

- Keep changes minimal and behavior-preserving.
- Use existing style in touched files (4 spaces, minimal typing, existing super(...) patterns).
- Treat request headers as untrusted; preserve sanitization and auth safety checks.
- Preserve env parsing compatibility in utils.env (especially bool/list/tuple semantics).
- Do not bypass ActiveMixin soft-delete semantics unless explicitly intended.

## Testing Rules

- Add/update tests for behavior changes.
- Prefer integration-style checks with Django TestCase + test client for middleware/views.
- Validate externally visible outcomes: response code/content, auth state, DB state.

## Tooling Rules

- Lint baseline: Ruff line length 140; ignores E265, E501, E722.
- Standard verification commands:
  - pytest -sv
  - tox -v

## High-Risk Change Areas

- middleware.py auth/session/group synchronization.
- utils.py env coercion and error behavior.
- models.py soft-delete and audit change-tracking behavior.
