---
name: "build-your-own-x"
description: "Finds Build Your Own X tutorials and turns them into practical implementation paths. Invoke when user asks to build a technology from scratch."
---

# Build Your Own X

Use this skill when the user wants to learn, design, or implement a technology from scratch using the Build Your Own X approach.

Primary source:
- GitHub repository: `https://github.com/codecrafters-io/build-your-own-x`
- Raw index: `https://raw.githubusercontent.com/codecrafters-io/build-your-own-x/master/README.md`

## When To Invoke

Invoke this skill when the user asks for any of the following:

- "build your own X"
- "from scratch"
- "recreate a database/compiler/web server/shell/git/docker/etc."
- "find a Build Your Own X tutorial"
- "use build-your-own-x"
- "implement X by following a tutorial path"

Common examples:

- Build your own database
- Build your own programming language
- Build your own Git
- Build your own shell
- Build your own web server
- Build your own Docker
- Build your own renderer
- Build your own AI model

## Workflow

1. Confirm the target technology and preferred language if the user did not specify them.
2. Fetch or search the official Build Your Own X README from GitHub.
3. Locate the matching category and extract relevant tutorial links.
4. Prefer tutorials that match the user's language, platform, and current project constraints.
5. Convert the tutorial list into a concrete learning or implementation plan.
6. If implementation is requested, make the smallest useful working version first.
7. Validate behavior with runnable commands, tests, or a minimal demo.

## Search Commands

Use one of these commands when local Git access is useful:

```powershell
git ls-remote https://github.com/codecrafters-io/build-your-own-x.git HEAD
```

For a temporary local copy:

```powershell
git clone --depth 1 https://github.com/codecrafters-io/build-your-own-x.git <temporary-path>
```

Do not clone the repository into the user's project unless they explicitly ask for a local copy. Prefer a temporary directory or direct raw README access for discovery.

## Response Style

When only research is requested, return:

- The official repository URL
- The matched category
- The best tutorial links
- A short recommendation on which one to start with

When implementation is requested, return:

- A small milestone plan
- The first minimal version to build
- Files to touch
- Verification steps
- Risks or assumptions

## Engineering Guardrails

- Do not copy tutorial code blindly into the project.
- Keep changes aligned with the current repository architecture.
- Prefer minimal, testable increments over large rewrites.
- Preserve existing project rules, naming conventions, and dependency constraints.
- Cite external tutorial sources in the final explanation when they influenced the implementation.
