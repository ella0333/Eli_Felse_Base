# Red teaming

The pitch of this project is its safety architecture, so red-teaming it is welcome and
expected.

## In scope

Any way to make the agent act outside its schema, or any path from LLM output to
execution (shell, eval, filesystem paths, outbound requests) inside the base or the
official modules.

## Out of scope

Speech-level jailbreaks; making the agent *say* things. See
[safety claims](safety-claims.md); the framework does not claim to control what the
model says, only what it can do.

## How to report

Please do not open a public issue for an in-scope finding. Open a
[private security advisory](https://github.com/ella0333/Eli_Felse_Base/security/advisories/new)
on this repository instead.

Reporters are credited.
