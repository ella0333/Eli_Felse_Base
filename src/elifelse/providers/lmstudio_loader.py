"""Optional LM Studio integration via the `lms` CLI.

LM Studio has no REST endpoint for loading models with a specific context
length; the supported way is its CLI. Everything here is guarded by
shutil.which() — if `lms` isn't installed, the framework simply uses whatever
model is already loaded.
"""

from __future__ import annotations

import asyncio
import json
import shutil

from elifelse.textutils import print_system


def lms_available() -> bool:
    return shutil.which("lms") is not None


async def _run(args: list[str], timeout: float) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        return 1, "timed out"
    return proc.returncode or 0, (stdout or b"").decode(errors="replace").strip()


async def _is_already_loaded(model: str, context_tokens: int) -> bool:
    """Check if the requested model is already loaded with sufficient context."""
    code, out = await _run(["lms", "ls", "--json"], timeout=30)
    if code != 0:
        return False
    try:
        data = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return False
    models = data if isinstance(data, list) else []
    for entry in models:
        entry_path = entry.get("path") or entry.get("id") or ""
        entry_ctx = entry.get("context_length") or entry.get("max_context_length") or 0
        if model in entry_path and int(entry_ctx) >= context_tokens:
            return True
    return False


async def lms_load_models(
    model: str,
    context_tokens: int,
    utility_model: str | None = None,
    utility_context_tokens: int | None = None,
) -> None:
    """Unload everything, then load the main (and optional utility) model with
    the configured context length and max GPU offload."""
    if not lms_available():
        print_system("'lms' CLI not found on PATH; using whatever model is already loaded.")
        return

    if await _is_already_loaded(model, context_tokens):
        print_system(f"Model already loaded: {model}")
    else:
        print_system("Unloading all models via lms CLI...")
        code, out = await _run(["lms", "unload", "--all"], timeout=60)
        if code != 0:
            print_system(f"Unload warning (ok if nothing was loaded): {out[:200]}")
        await asyncio.sleep(2)

        print_system(f"Loading '{model}' (context {context_tokens}) via lms CLI...")
        print_system("(this may take a minute for large models)")
        code, out = await _run(
            ["lms", "load", model, "--context-length", str(context_tokens), "--gpu", "max"],
            timeout=300,
        )
        if code == 0:
            print_system(f"Model loaded: {model}")
            await asyncio.sleep(3)  # let the API server register the model
        else:
            print_system(f"Model load failed: {out[:300]}")
            if "multiple" in out.lower() or "ambiguous" in out.lower():
                print_system(
                    "The name matched multiple models. Use the full path "
                    "(e.g. 'publisher/model-name') to avoid ambiguity."
                )
            else:
                print_system("The model may need to be loaded manually in LM Studio.")

    if utility_model and utility_model != model:
        ctx = utility_context_tokens or context_tokens
        if await _is_already_loaded(utility_model, ctx):
            print_system(f"Utility model already loaded: {utility_model}")
        else:
            await asyncio.sleep(2)
            print_system(f"Loading utility model '{utility_model}' (context {ctx})...")
            print_system("(this may take a minute for large models)")
            code, out = await _run(
                ["lms", "load", utility_model, "--context-length", str(ctx), "--gpu", "max"],
                timeout=300,
            )
            if code == 0:
                print_system(f"Utility model loaded: {utility_model}")
                await asyncio.sleep(3)  # let the API server register the model
            else:
                print_system(f"Utility model load failed: {out[:300]}")
                if "multiple" in out.lower() or "ambiguous" in out.lower():
                    print_system(
                        "The name matched multiple models. Use the full path "
                        "(e.g. 'publisher/model-name') to avoid ambiguity."
                    )
                else:
                    print_system("The model may need to be loaded manually in LM Studio.")
