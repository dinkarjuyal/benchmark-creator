"""FastAPI corruption catalog for CDBench multi-domain evaluation.

20 hand-crafted corruptions across 4 FastAPI source files, targeting:
  - Dependency resolution (dependencies/utils.py)
  - Request routing and serialization (routing.py)
  - Application lifecycle (applications.py)
  - Parameter handling (params.py)

Each corruption is a (find, replace) pair with subtlety grading (1-5).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generators.coding_diffusion import CorruptionSpec

FASTAPI_ROOT = Path("/mnt/localssd/cdbench/sandboxes/fastapi/fastapi")

SOURCE_FILES = {
    "fastapi/dependencies/utils.py": FASTAPI_ROOT / "dependencies" / "utils.py",
    "fastapi/routing.py": FASTAPI_ROOT / "routing.py",
    "fastapi/applications.py": FASTAPI_ROOT / "applications.py",
    "fastapi/params.py": FASTAPI_ROOT / "params.py",
}

SOURCE_TO_TESTS = {
    "fastapi/dependencies/utils.py": [
        "tests/test_dependency_cache.py",
        "tests/test_dependency_class.py",
        "tests/test_dependency_contextmanager.py",
        "tests/test_dependency_overrides.py",
        "tests/test_dependency_security_overrides.py",
    ],
    "fastapi/routing.py": [
        "tests/test_additional_responses_router.py",
        "tests/test_custom_route_class.py",
        "tests/test_router_prefix.py",
    ],
    "fastapi/applications.py": [
        "tests/test_application.py",
        "tests/test_additional_responses_default_validationerror.py",
    ],
    "fastapi/params.py": [
        "tests/test_param_class.py",
        "tests/test_ambiguous_params.py",
    ],
}

# ── 20 hand-crafted corruptions ─────────────────────────────────────────────

FASTAPI_CORRUPTIONS = [
    # --- fastapi/dependencies/utils.py (6 corruptions) ---
    # 1. Skip repeats flipped: dependency caching breaks
    CorruptionSpec("fa_01", "fastapi/dependencies/utils.py",
        "if skip_repeats and sub_dependant.cache_key in visited:",
        "if skip_repeats or sub_dependant.cache_key in visited:",
        "get_flat_dependant: AND→OR in skip_repeats check (caches deps that should re-run)", "", "", "dependencies", 3),

    # 2. Path params misclassified as query params
    CorruptionSpec("fa_02", "fastapi/dependencies/utils.py",
        'if field_info_in == params.ParamTypes.path:',
        'if field_info_in == params.ParamTypes.query:',
        "add_param_to_fields: path→query param classification (path params treated as query)", "", "", "dependencies", 2),

    # 3. Coroutine detection inverted
    CorruptionSpec("fa_03", "fastapi/dependencies/utils.py",
        "return inspect.iscoroutinefunction(call)",
        "return not inspect.iscoroutinefunction(call)",
        "is_coroutine_callable: returns NOT iscoroutine (sync fns run as coroutines and vice versa)", "", "", "dependencies", 4),

    # 4. Async gen detection inverted
    CorruptionSpec("fa_04", "fastapi/dependencies/utils.py",
        "return inspect.isasyncgenfunction(dunder_call)",
        "return not inspect.isasyncgenfunction(dunder_call)",
        "is_async_gen_callable: inverted detection (async generators treated as regular)", "", "", "dependencies", 4),

    # 5. Dependency cache never populated (first entry never written)
    CorruptionSpec("fa_05", "fastapi/dependencies/utils.py",
        "if sub_dependant.cache_key not in dependency_cache:",
        "if sub_dependant.cache_key in dependency_cache:",
        "solve_dependencies: cache condition inverted (deps never cached, always re-resolved)", "", "", "dependencies", 3),

    # 6. Values: path_params override query_params on name collision
    CorruptionSpec("fa_06", "fastapi/dependencies/utils.py",
        "values.update(path_values)",
        "values.update(query_values)",
        "solve_dependencies: path_values→query_values (path params lost, query params used instead)", "", "", "dependencies", 3),

    # --- fastapi/routing.py (6 corruptions) ---
    # 7. Response validation skipped for coroutines
    CorruptionSpec("fa_07", "fastapi/routing.py",
        "if is_coroutine:\n            value, errors_ = field.validate(response_content, {}, loc=(\"response\",))",
        "if not is_coroutine:\n            value, errors_ = field.validate(response_content, {}, loc=(\"response\",))",
        "serialize_response: coroutine check inverted (sync responses validated, async skipped)", "", "", "routing", 4),

    # 8. Dependency error guard inverted: endpoints only run when there ARE errors
    CorruptionSpec("fa_08", "fastapi/routing.py",
        "if not errors:",
        "if errors:",
        "get_request_handler: error guard inverted (endpoints only execute when dependency validation fails, all valid requests return 422)", "", "", "routing", 2),

    # 9. JSON content-type detection broken
    CorruptionSpec("fa_09", "fastapi/routing.py",
        'if subtype == "json" or subtype.endswith("+json"):',
        'if subtype == "json" and subtype.endswith("+json"):',
        "get_request_handler: OR→AND in JSON subtype check (only matches 'json' that also ends with '+json' — impossible)", "", "", "routing", 3),

    # 10. Form body not closed properly (push_async_callback removed)
    CorruptionSpec("fa_10", "fastapi/routing.py",
        "file_stack.push_async_callback(body.close)",
        "file_stack.push_async_callback(body.reset)",
        "get_request_handler: form body close→reset (reset is not a valid method on FormData)", "", "", "routing", 2),

    # 11. Response status_code: is_not_None → is_not_0
    CorruptionSpec("fa_11", "fastapi/routing.py",
        "if current_status_code is not None:",
        "if current_status_code is not 0:",
        "route handler: None-check→0-check for status_code (status 200 overridden by prior None)", "", "", "routing", 2),

    # 12. Body parsing: content-type header missing case handled wrong
    CorruptionSpec("fa_12", "fastapi/routing.py",
        "if not content_type_value:\n                                json_body = await request.json()",
        "if not content_type_value:\n                                json_body = Undefined",
        "get_request_handler: no content-type → skip JSON parsing (body treated as raw bytes always)", "", "", "routing", 4),

    # --- fastapi/applications.py (5 corruptions) ---
    # 13. Include router: prefix not applied to API route path
    CorruptionSpec("fa_13", "fastapi/routing.py",
        "route = route_class(\n            self.prefix + path,\n            endpoint=endpoint,",
        "route = route_class(\n            path,\n            endpoint=endpoint,",
        "APIRouter.add_api_route: drops prefix from route path (HTTP routes registered at root instead of under prefix)", "", "", "routing", 2),

    # 14. OpenAPI schema: always regenerated (never cached)
    CorruptionSpec("fa_14", "fastapi/applications.py",
        "if not self.openapi_schema:",
        "if self.openapi_schema:",
        "FastAPI.openapi: cache condition inverted (schema regenerated every call, expensive + mutable)", "", "", "applications", 3),

    # 15. Lifespan: on_event deprecation points to wrong handler
    CorruptionSpec("fa_15", "fastapi/applications.py",
        "on_event is deprecated, use lifespan event handlers instead.",
        "on_event is deprecated, use startup event handlers instead.",
        "FastAPI.on_event: wrong deprecation message (points to startup instead of lifespan)", "", "", "applications", 5),

    # 16. Lifespan merge: both None → yield {} instead of None
    CorruptionSpec("fa_16", "fastapi/routing.py",
        "if maybe_nested_state is None and maybe_original_state is None:",
        "if maybe_nested_state is not None and maybe_original_state is not None:",
        "merged_lifespan: AND condition inverted (yields {} when both None, yields None when both present)", "", "", "routing", 4),

    # 17. Swagger UI redirect missing
    CorruptionSpec("fa_17", "fastapi/applications.py",
        "async def swagger_ui_redirect(req: Request) -> HTMLResponse:",
        "async def swagger_ui_redirect(req: Request) -> RedirectResponse:",
        "setup: swagger redirect returns wrong type (RedirectResponse instead of HTMLResponse)", "", "", "applications", 3),

    # --- fastapi/params.py (3 corruptions) ---
    # 18. Param alias: query→header
    CorruptionSpec("fa_18", "fastapi/params.py",
        'in_ = ParamTypes.query',
        'in_ = ParamTypes.header',
        "Query default: in_ query→header (all Query params treated as Header params)", "", "", "params", 2),

    # 19. Path param: allows default value (should not)
    CorruptionSpec("fa_19", "fastapi/params.py",
        'assert default is ..., "Path parameters cannot have a default value"',
        'assert default is not ..., "Path parameters cannot have a default value"',
        "Path.__init__: assert inverted (requires default value for path params, breaking required path params)", "", "", "params", 3),

    # 20. Body embed: always embed even when not requested
    CorruptionSpec("fa_20", "fastapi/params.py",
        "self.embed = embed",
        "self.embed = True",
        "Body.__init__: embed always True regardless of parameter (body always wrapped in parent model)", "", "", "params", 3),
]
