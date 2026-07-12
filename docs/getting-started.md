# Getting started

A full walkthrough for setting up Eli Felse from scratch with no prior experience needed.

## 1. Install Python

Download and install **Python 3.10 or newer** from [python.org](https://www.python.org/downloads/).

On Windows, make sure to tick **"Add python.exe to PATH"** in the installer. This lets you
run Python from any terminal.

To verify it worked, open a terminal (PowerShell on Windows, Terminal on Mac) and run:

```bash
python --version
```

You should see something like `Python 3.12.x`.

## 2. Download and install the project

Open a terminal and run:

```bash
git clone https://github.com/ella0333/Eli_Felse_Base.git
cd Eli_Felse_Base
python -m venv .venv
```

Activate the virtual environment:

- **Windows (PowerShell):** `.venv\Scripts\activate`
- **Mac/Linux:** `source .venv/bin/activate`

You should see `(.venv)` at the start of your terminal prompt. Then install:

```bash
pip install -e .
```

## 3. Set up a model

Eli Felse needs a language model to run. You have two options: run one locally (free and
private) or connect to a paid API. For a full breakdown of which models work, see the
[Model Options Guide](model-options.md).

### Option A: Local model with LM Studio (recommended)

[LM Studio](https://lmstudio.ai) is a free desktop app that runs language models on your
own machine. Nothing leaves your computer.

1. Download and open LM Studio
2. In the search tab, download a model (anything that fits your GPU/RAM works)
   (an instruct model around 7B-14B is a good start)
3. Open the **Developer** tab and click **Start Server**. You should see
   `http://localhost:1234` listed
4. Note the identifier of the model you intend to use (e.g., `unsloth/magistral-small-2509`),
   The setup wizard will ask for it
5. Also note the maximum **context length** the model supports; the wizard's
   "max context tokens" answer must not be higher than this

### Option B: Paid API (OpenAI, Anthropic, OpenRouter, etc.)

If you want to use a hosted model or frontier model instead:

1. Get an API key from your provider ([OpenAI](https://platform.openai.com/api-keys),
   [OpenRouter](https://openrouter.ai/keys), or any OpenAI endpoint compatible service)
2. The setup wizard will ask for the server URL and which environment variable holds
   your API key
3. Your key goes in a `.env` file (never in `config.yaml`), so it stays out of git

**Model name format matters:**
- **Direct APIs** (OpenAI at `api.openai.com`): use just the model name, e.g. `gpt-5.6-luna`
- **Aggregators** (OpenRouter): use the `publisher/model` format, e.g. `openai/gpt-5.6-luna`
- If you get it wrong, the framework auto-corrects by stripping the prefix on retry

### Option C: No model (demo mode)

Just want to see how it works? Skip model setup entirely and run:

```bash
elifelse run --provider mock --max-iterations 3
```

This uses canned responses so you can explore the interface without needing any model.

## 4. Run the setup wizard

```bash
elifelse init
```

The wizard walks you through everything:

- **Your name:** how the agent refers to you (defaults to "Developer", or type your own)
- **Model location:** LM Studio, Ollama, paid API, or mock/demo
- **Model name:** exactly as the server reports it
- **Context size:** must match or be below what your model server is configured for
- **Response pacing:** a randomized delay between replies. "Lifelike" adds 1-40 seconds
  of pause, which helps your GPU rest between calls if running locally and makes responses
  feel more natural. "Instant" removes the delay. You can also set custom min/max values.
- **Spend cap:** for paid APIs, a daily token budget (mandatory). For local models,
  optional.
- **Day cycle:** bedtime and wake time (the agent sleeps on schedule, making zero API
  calls overnight)
- **Character:** name, pronouns, personality, backstory for your AI persona

When it's done, it writes `config.yaml` and `persona.yaml`, then runs a quick connection
test against your API. If the test detects issues (wrong model name format, unsupported
parameters), it auto-fixes `config.yaml` and tells you what changed. Both files are plain
text and you can edit them by hand anytime.

## 5. Start the agent

```bash
elifelse run
```

The agent wakes up, picks something to do, and gets on with its day. Type in the terminal
to talk to it.

- `/pause` pause the agent
- `/resume` resume from pause
- `/stop` shut down safely (Ctrl+C also works)
- `/help` show all commands

The next `elifelse run` offers to pick up where it left off.

## Troubleshooting

**"Config file not found":** run `elifelse init` first, or copy `config.example.yaml`
to `config.yaml`.

**Model server not running:** check that LM Studio's Developer tab says *Running* and
the URL matches what's in your `config.yaml`.

**Context length errors:** your `max_context_tokens` in config is higher than what the
model server is actually configured for. Lower it to match.

**API key errors:** make sure the environment variable name in `config.yaml` matches
what's in your `.env` file, and that the `.env` file has your actual key (not the
placeholder).

**"invalid model ID":** you may be using the OpenRouter format (`openai/gpt-5.6-luna`)
on a direct API that expects just the model name (`gpt-5.6-luna`). The framework
will auto-retry with the prefix stripped, but you can also fix it in `config.yaml`.

**"Unknown parameter: 'repeat_penalty'":** some cloud APIs don't support local-only
parameters. The framework auto-removes these and retries. To prevent the error
entirely, remove `repeat_penalty` (and `top_k` if present) from your `model_params`
in `config.yaml`.
