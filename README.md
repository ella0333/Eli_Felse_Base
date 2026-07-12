# Eli Felse | Base

[![CI](https://github.com/ella0333/Eli_Felse_Base/actions/workflows/ci.yml/badge.svg)](https://github.com/ella0333/Eli_Felse_Base/actions/workflows/ci.yml)

!["Eli" Anime Character with grey hair and green eyes, and grey x hair clip](https://i.imgur.com/Mo4gDYT.png)

**Meet the base module of Eli Felse, a framework built to explore safer ways to create
autonomous AI assistants.**

## What makes Eli different from other AI agents

Rather than the user prompting an LLM to execute commands, the LLM makes the choices and
Python automation does the rest. This is an exploration into safer ways to run and contain
more autonomous AI models.

This release is an easy starting point for beginners, but I really encourage you to have
fun building your own characters and frameworks with this same base concept, I've created
a **[guide here](https://elifelse.org/dev-blog/guide-build-your-own-eli)**

## Learn More about the Project

Eli Felse is part of a public demo, weekly blogs, open-source releases, and a growing community.

**[24/7 live public demo](https://elifelse.org/eli/)**

**[Introduction Blog](https://elifelse.org/dev-blog/meet-eli)**

**[Join the Discord community](https://discord.com/invite/2C4znNnyM7)**

## Quick start

```bash
git clone https://github.com/ella0333/Eli_Felse_Base.git
cd Eli_Felse_Base
python -m venv .venv
.venv\Scripts\activate        # Windows   (Mac/Linux: source .venv/bin/activate)
pip install -e .
elifelse init
elifelse run
```

The setup wizard walks you through everything: model connection, persona, schedule, and
features. It also runs a quick connection test at the end to verify your config works
and auto-corrects common issues (wrong model name format, unsupported parameters).

New to all of this? Follow the **[Getting Started Guide](docs/getting-started.md)** for a
Full walkthrough from zero, including model and API setup.

Looking for which models work best? See the **[Model Options Guide](docs/model-options.md)** for
recommendations, requirements, and configuration.

## Runtime commands

| Command | Description |
|---|---|
| `/message <text>` | Send a message to the agent (works anytime, even outside chat) |
| `/pause` | Pause the agent |
| `/resume` | Resume the agent |
| `/stop` | Shut down safely |
| `/dashboard` | Open the web dashboard (status, logs, memory) |
| `/help` | Show available commands |

## Startup options

| Command | Description |
|---|---|
| `elifelse init` | Run the interactive setup wizard |
| `elifelse saves` | List all saved states |
| `elifelse run` | Start the agent |
| `elifelse run --load NAME` | Resume from a specific save |
| `elifelse run --fresh` | Skip crash recovery, start clean |
| `elifelse run --provider mock` | Run without a model for demo purposes |

## Features

- **Schema-constrained safety:** the model picks from fixed menus, never executes anything
- **Memory:** vector recall and automatic fact consolidation
- **Day/night cycle:** sleeps on schedule, zero API calls overnight
- **Built-in activities:** journal, chat, eat, nap, ponder, environment
- **Saves and recovery:** named saves, crash recovery, nightly backups
- **Cost controls:** daily token budgets, auto-sleep when the cap is hit
- **Response pacing:** configurable delays between replies (helps GPU rest when running locally)
- **Privacy:** everything stays in `data/`, delete it, and it's gone
- **Dashboard:** localhost web UI for status, logs, and memory

## Additional modules

More modules will be released regularly and can be easily connected by dropping them into
`data/modules/`. Some examples of what's planned:

- **Social:** Discord, Slack, Twitter, Reddit, Live streaming
- **Games:** board games, text RPGs, Pokémon Blue
- **Explore:** web search, news
- **Creative:** blog, story writing, music
- **Other:** reading

See **[developing modules](docs/developing-modules.md)** for instructions on building your own.

## Platform support

Eli Felse was built and tested on **Windows**. It should work on **macOS** and **Linux**
Too, but those platforms haven't been extensively tested yet.

## Docs

- **[Model options](docs/model-options.md):** which models work and how to configure them
- **[Safety claims](docs/safety-claims.md):** what is and isn't guaranteed
- **[Developing modules](docs/developing-modules.md):** build your own activity
- **[Modules](docs/modules.md):** community module list
- **[Red teaming](docs/red-teaming.md):** reporting safety issues

---

[![elif else](https://img.shields.io/badge/elif_else-869b9f?style=flat)](https://elifelse.org/)
[![MIT License](https://img.shields.io/badge/MIT_License-869b9f?style=flat)](LICENSE)
