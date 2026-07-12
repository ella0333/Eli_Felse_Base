# Safety claims

What the framework guarantees, and what it doesn't.

## Guaranteed by construction

- **No execution path from LLM output.** The model's output is parsed, validated against
  a JSON schema, and then either displayed, stored, or matched against a fixed enum /
  pattern. It never reaches a shell, an eval, a filesystem path, or an outbound request.
- **Menus are inescapable.** Enum fields must match the allowed list exactly; violations
  are regenerated (up to 5 attempts), and an out-of-enum value can never reach a caller.
- **Schema enforcement strength varies by backend.** On local grammar-constrained
  Backends (LM Studio, llama.cpp, Ollama) output literally cannot violate the schema.
  On APIs without strict schema support, the validation loop is the only guardrail;
  weaker, and documented as such.

## Not guaranteed

- **What the agent says.** Prompt injection can influence the agent's words. It cannot
  Trigger unprogrammed actions, call tools, or execute shell commands.
- **Third-party modules.** A module is arbitrary Python you install. The module contract
  (see [developing modules](developing-modules.md)) and the review process reduce honest
  mistakes; they cannot stop a determined bad actor. Install modules with the same
  judgment as any other software.
- **Modules that post publicly** (social media, email) are opt-in and default read-only,
  but once enabled, the agent's words go where you point them.

## The module contract

> LLM output may be (1) displayed, (2) stored, or (3) passed to a constrained parser
> (an enum, a pattern, a game engine, a sandbox). It may NEVER reach a shell, an eval,
> a filesystem path, or an outbound request. If your module follows this, it preserves
> the framework's safety guarantee. If it doesn't, it must say so in its README.
