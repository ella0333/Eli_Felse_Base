# Model options

Which models work with Eli Felse, what they need to support, and how to configure them.

## The short version

Any **instruct model** served through an **OpenAI-compatible API** (`/v1/chat/completions`)
will work, as long as it meets two requirements: it must support **structured output**
(JSON schema responses) and it must support **custom system prompts**. The framework
relies heavily on both.

## Supported backends

| Backend | Type | Structured output | Notes |
|---|---|---|---|
| [LM Studio](https://lmstudio.ai) | Local | Grammar-constrained | Recommended for local. Output literally cannot violate the schema. |
| [Ollama](https://ollama.com) | Local | Grammar-constrained | Same grammar enforcement as LM Studio. |
| [llama.cpp server](https://github.com/ggerganov/llama.cpp) | Local | Grammar-constrained | Direct llama.cpp HTTP server. |
| [vLLM](https://github.com/vllm-project/vllm) | Local/Cloud | Grammar-constrained | High-throughput serving. |
| [OpenAI](https://platform.openai.com) | Cloud (paid) | API-validated | Works well. Set a daily token budget. |
| [Anthropic](https://console.anthropic.com) | Cloud (paid) | API-validated | Claude models. Use via OpenRouter, or with an OpenAI-compatible proxy (e.g. LiteLLM). Set a daily token budget. |
| [OpenRouter](https://openrouter.ai) | Cloud (paid) | Varies by model | Routes to many providers. Check that your chosen model supports structured output. |
| Any OpenAI-compatible endpoint | Either | Varies | If it speaks `/v1/chat/completions`, it should work. |

## Model requirements

### Structured output

Eli Felse's safety model depends on structured output. The model never "executes" anything;
it picks from menus (JSON enum fields), and the framework validates every response against a
strict JSON schema before acting on it. On grammar-constrained backends (LM Studio, Ollama,
llama.cpp), the output literally cannot violate the schema. On cloud APIs, the framework's
validation loop is the guardrail; weaker, but still enforced. See
[safety claims](safety-claims.md) for the full breakdown.

### System prompt support

The framework uses a custom system prompt to define the agent's personality, identity,
context, and behavioral rules. The system prompt is swapped dynamically as the agent
moves between activities. **Your model must properly support the system role in the chat
completions format** models that ignore or poorly handle custom system prompts will
not work.

For example, older Gemma models (Gemma 1, Gemma 2) did not support system prompts at all
and would silently ignore them, making the agent behave as a generic chatbot with no
personality or context. Gemma only added system prompt support in its more recent releases.
Always check that your chosen model's chat template actually uses the system message.

### Reasoning models are not required

Many models now ship with built-in extended reasoning / chain-of-thought capabilities. When
structured output is enabled, most backends disable the model's native reasoning mode
since the output must conform to the JSON schema. Eli Felse handles this by including a
`thinking` field in every schema; the model gets a dedicated place to reason within the
structured response itself. This means reasoning models offer no special advantage here;
any instruct model that meets the requirements above will work.

### What Eli Felse runs on

The framework isn't tied to any specific model. Pick whichever instruct model fits your
hardware and budget. As an example, Eli Felse uses
[Magistral-Small](https://huggingface.co/mistralai/Magistral-Small-2506) and it works
great. If you're running locally, [unsloth](https://huggingface.co/unsloth/Magistral-Small-2509-GGUF)
provides optimized GGUF versions of many models for faster inference.

On paid APIs, **always set a daily token budget**. The agent runs autonomously and will
make calls all day. The `daily_token_budget` config auto-sleeps the agent when it hits
the cap.

## Configuration reference

All model settings live in `config.yaml` under the `provider` and `model_params` sections.

### Provider settings

```yaml
provider:
  kind: "openai_compat"            # "openai_compat" or "mock"
  base_url: "http://localhost:1234/v1"
  api_key_env: ""                  # env var name holding your API key ("" = none)
  model: "publisher/model-name"    # name or full path (see "model" below)
  utility_model: ""                # optional second model for background work
  max_context_tokens: 36000        # must not exceed your server's configured limit
  request_timeout: 300             # seconds before a request times out
  daily_token_budget: 0            # 0 = unlimited; set this on paid APIs
  lmstudio_loader: false           # auto-load via the lms CLI (LM Studio only)
```

### Key settings explained

**model:** The model identifier format depends on how you're connecting:

| Connection type | Format | Example |
|---|---|---|
| **Local** (LM Studio, Ollama) | Identifier path as shown by the server | `qwen2.5-14b-instruct`, `unsloth/magistral-small-2509` |
| **Aggregator** (OpenRouter) | `publisher/model-name` | `openai/gpt-5.6-luna`, `anthropic/claude-sonnet-4` |
| **Direct API** (OpenAI, Anthropic) | Just the model name, no prefix | `gpt-5.6-luna`, `claude-sonnet-4` |

A common mistake is using `openai/gpt-5.6-luna` (the OpenRouter format) when connecting
directly to `api.openai.com`, which expects just `gpt-5.6-luna`. The framework handles
this automatically: if the API returns an "invalid model ID" error and your model name
contains a `/`, it will strip the prefix and retry. If the retry succeeds, the setup
wizard's connection test will also update your `config.yaml` with the corrected name.

In LM Studio, the model identifier is shown in the Developer tab when the server is running.
In Ollama, it's the name you pulled (e.g. `qwen2.5:14b`).

**utility_model:** An optional second, smaller model used for background tasks like
memory extraction and summarization. These tasks don't need personality or creativity,
so a fast small model works well. Leave empty to use the main model for everything.

**max_context_tokens:** The framework hard-limits every prompt to this many tokens. It
must be at or below what your model server is actually configured for. If it's higher, the
server will silently truncate and quality drops. When in doubt, use a lower number.

**daily_token_budget:** Total tokens (all calls, including background work) allowed per
day. When the budget is hit, the agent auto-sleeps until the daily reset. **Never leave
this at 0 on a paid API unless you truly mean unlimited.**

### Generation parameters

It is best to start with the recommended model params listed on Hugging Face or the default params provided with API models and adjust from there.

```yaml
model_params:
  default:
    temperature: 0.7           # in-character creativity (higher = more varied)
    temperature_raw: 0.3       # background/utility calls (lower = more precise)
    top_p: 0.95
    top_k: 0                   # 0 = disabled
    repeat_penalty: 1.05
    max_tokens: 3000           # max response length for in-character calls
    max_tokens_raw: 4000       # max response length for background calls
    chat_template_kwargs: null # e.g. {enable_thinking: false} for models that need it
```

**Provider-specific parameters:** Some parameters (like `repeat_penalty`, `top_k`,
`chat_template_kwargs`) are supported by local backends but not by cloud APIs like
OpenAI. If the API returns an "unknown parameter" error, the framework automatically
removes the offending parameter and retries. The parameter stays removed for all
subsequent calls in that session. The setup wizard's connection test will also detect
these issues and update your `config.yaml` to remove unsupported parameters upfront.

You can override these per model by adding an entry keyed to the exact model name:

```yaml
model_params:
  default:
    temperature: 0.7
  "qwen2.5-14b-instruct":
    temperature: 0.8
    repeat_penalty: 1.1
```

### Quirks

```yaml
provider:
  quirks:
    no_think_suffix: false     # append "/no_think" to user turns (some Qwen builds need this)
```

Some model builds have non-standard behaviors. The quirks section handles known edge cases.
Currently, the only quirk is `no_think_suffix` for certain Qwen builds that need an explicit
signal to skip chain-of-thought reasoning in the raw output.

## Response pacing

```yaml
provider:
  response_delay_min: 1
  response_delay_max: 40
```

A randomized delay before each in-character response. If you're running a model locally,
this gives your GPU time to cool between calls. It also makes response timing feel more
natural. Set both to 0 for instant replies.

## Demo mode

Don't have a model yet? Run with canned responses to explore the interface:

```bash
elifelse run --provider mock --max-iterations 3
```

No model, no API key, no config file needed for demo mode.
