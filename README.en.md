# LLM Wiki

[简体中文](README.md) | **English**

Let your agent build and maintain a Markdown wiki with traceable sources.

Inspired by Andrej Karpathy's [LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f), this project compiles incoming material into a persistent collection of linked pages. The agent integrates new evidence, revises existing knowledge, and answers questions against that accumulated work. You choose the sources and questions; the agent handles the maintenance.

## What it maintains

- Captured sources with available origin information, timestamps, and versions.
- Summaries, entities, concepts, analyses, and topic hubs linked to their evidence.
- Topic checks on every ingestion, with resumable reviews of older summaries and recorded reasons for deferred topics.
- Answers and research suggestions with citations, explicit uncertainty, and preserved disagreements.
- Navigation and operation logs, backed by checks for broken links, missing evidence, and stale dependencies.

Use it for ongoing research, technical reference collections, and shared knowledge that needs a traceable connection to its sources.

## Install through your agent

Use an agent with network access, local file access, and tool execution. The project supports macOS and Linux. Keep the skill and knowledge base in separate directories within the workspace:

| Workspace-relative location | Purpose |
| --------------------------- | ------- |
| `skills/llm-wiki/` | Skill instructions, templates, and tools |
| `my-wiki/` | Sources, knowledge pages, and logs |

```text
Install llm-wiki in this workspace:
https://github.com/wuzhao/llm-wiki

Read the repository instructions and SKILL.md. Use this agent's workspace
skill directory if supported; otherwise put the complete project at
skills/llm-wiki and provide an explicit loading instruction.
Keep the skill separate from the knowledge base and preserve existing installations.
Prepare the environment and dependencies, verify the tools, and report
the installation path, verification results, and how to load it later.
```

`skills/llm-wiki/` is a location for explicit loading; automatic discovery depends on the agent. Existing installations elsewhere can also be selected explicitly.

## Build your first wiki

These examples use this workspace's skill installation and `my-wiki/`. Substitute your own paths. In a new session, identify the skill and knowledge base locations and use the installation's loading instruction if needed.

### Initialize an empty knowledge base

```text
Use this workspace's llm-wiki installation to initialize a separate,
empty knowledge base at my-wiki/. Validate it and report its absolute path.
```

Initialization requires an empty target. Open an existing wiki directly rather than initializing it again. For English page content, see [Language and schema](#language-and-schema).

### Ingest source material

A local text file:

```text
Ingest /path/to/article.md into my-wiki/.
Update its source summary and integrate new evidence into the relevant pages.
```

A web page, using its actual URL:

```text
Ingest this page into my-wiki/: <page URL>
```

Pasted text:

```text
Ingest the following note into my-wiki/.
Title: Cache validity
Text: Reusing a cached result requires clear validity and invalidation conditions.
```

### Query the wiki

```text
Query my-wiki/: when is caching appropriate?
Cite the supporting pages and explain the conditions and disagreements
behind the claims.
```

Queries are read-only by default. Ask to archive the answer to save it as an analysis page.

## Keep the wiki useful

### Revisit a changed source

```text
Ingest the updated /path/to/article.md into my-wiki/. Update affected pages,
preserve relevant history and conflicts, and list anything awaiting review.
```

### Explore an open question

```text
Explore the caching material in my-wiki/. Identify unanswered questions,
missing evidence, and connections worth investigating.
```

Exploration is read-only by default. Request saving explicitly to keep the result.

### Synthesize existing summaries

```text
Review the existing summaries in my-wiki/. Create or update entity and
concept pages when the evidence supports them; retain deferred topics
with their reasons and the information needed to revisit them.
```

The first synthesis pass reviews the existing backlog. Later rounds run during ingestion when the configured interval is reached. Page creation depends on useful evidence, not mention counts or a quota.

### Check and repair

Start with a check:

```text
Check the health of my-wiki/. Report findings and proposed actions.
```

To apply repairs:

```text
Apply the safe fixes from that report, recheck, and list the findings
that still need judgment or additional evidence.
```

### If you want to operate the tools yourself

Ask the agent about any of these workflows, modes, or tools:

| Operation | Name to use with the agent | Result |
| --------- | -------------------------- | ------ |
| Initialize | `init` | Create the base structure and files in an empty directory |
| Ingest and update | `ingest` | Handle new sources, revisions, duplicate input, and unfinished processing; maintain summaries and relevant pages |
| Synthesize knowledge | `synthesize` | Review existing summaries, maintain entity and concept pages, and retain deferred topics |
| Query | `query` | Synthesize an answer with citations; read-only by default |
| Archive an answer | `query` with an archive/save request | Save the answer as an analysis page |
| Explore | `explore` | Investigate knowledge gaps, connections, and structural improvements; read-only by default |
| Save an exploration | `explore` with a save request | Save an analysis or topic hub |
| Check health | `lint` | Report structural, navigation, evidence, conflict, and freshness findings |
| Preview repairs | `lint --fix --dry-run` | Preview deterministic repairs without changing files |
| Apply safe repairs | `lint --fix` | Apply the supported deterministic fixes |
| Clean up | `cleanup` | Remove authorized targets, clean up references, and check the result |
| Search | `search` | Return matching pages and snippets with pagination |
| Analyze source impact | `impact` | List affected pages without changing files |

Archiving and saving are workflow options; `search` and `impact` are supporting tool capabilities. The agent maps these names to the current implementation.

```text
Explain ingest, query, lint, and safe repairs. Give me manual steps and
commands for my environment, including which reading and synthesis steps
still require the agent.
```

## How it works

The skill defines the rules and page templates. Tools handle capture, search, dependency inspection, and deterministic checks; the agent interprets evidence and maintains the written knowledge. Each operation identifies the skill location and target knowledge base first.

### Compilation and retrieval

```text
ingest
[Files / URLs / Text]
         │
         ▼
[Agent with Skill rules]
         │
         ▼
[Ingestion tool] ▶ [raw/ and URL snapshots in raw/assets/]
         │
         ▼
[Agent: compile / update wiki/]
         │
         ▼
[Update index and Read-only lint]
         │
         ├─ blocking errors ▶ [Correct and recheck]
         ├─ pass            ▶ [Log completion and remaining warnings]
         └─ cannot finish   ▶ [Report writes and log incomplete status]

query / explore
[Question] ▶ [Agent: index and full-text search]
                              │
                              ▼
                [Read wiki/ and verify raw/]
                              │
                              ▼
          [Answer with citations / Research directions]
```

Ingest uses source identity and actual changes to choose initial capture or a version update; matching titles do not establish identity. Pasted-text revisions need an existing source identity, supplied by the agent through `--source-id`. An unchanged source that was fully processed returns its existing pages. If summary compilation, topic checks, or propagation of a prior update were unfinished, the agent completes that work. Every ingestion checks core entities, concepts, and related older summaries. Sufficient evidence leads to a page update or creation; deferred topics remain recorded in summary metadata. The read-only `synthesis_wiki.py` tool lists review batches and resumes progress from summaries and log checkpoints. Duplicate source content does not advance the interval.

For source revisions, the agent combines dependency records with full-text search to review affected claims. Current findings, history, and unresolved conflicts remain distinct. Archived analyses retain their historical text and are flagged for review when dependencies change. Queries read candidate pages in batches and trace important numbers, quotations, and conflicts back to raw sources.

### Storage and provenance

The wiki persists independently of a chat session as local Markdown with YAML metadata and associated files.

| Location | Contents |
| -------- | -------- |
| `raw/` | Source material layer; material pages record bodies, origin information, capture times, and versions |
| `raw/assets/` | Original web responses and attachments within the source layer; not processed as material pages |
| `wiki/` | Summaries, entities, concepts, analyses, hubs, navigation, and logs |

The index locates content, the overview describes coverage, and monthly logs record operations and pending reviews. Back up the complete knowledge base: logs summarize changes but do not provide a full file history. After manual edits, ask the agent to check references and navigation.

See the [schema guide](references/schema.md), [schema.json](references/schema.json), and this project's [OKF 0.2 frontmatter profile](references/okf-frontmatter.md) for the file conventions.

### Language and schema

The policies and templates currently use Chinese, with some headings and index categories required by the schema. For English prose, retain those structural labels and frontmatter values; renaming them changes the schema contract.

### Operational boundaries

- Extraction preserves code, links, and simple HTML tables; complex tables retain HTML. The fetcher does not execute JavaScript, download page images, or extract PDF and other binary attachment contents. Supply usable text when needed.
- Existing raw bodies are read-only. `lint --fix` only fills determinable `type` and `title` fields there. Other metadata corrections require source evidence and a log record.
- Structural validity and a matching number do not prove a claim. Reading can continue across batches; disclose unreadable content and distinguish partial results from conclusions about the whole wiki.
- Checks report findings by default; safe repairs handle deterministic cases. Deletion, renaming, and bulk link changes require an impact report and authorization for the exact targets.
- Blocking errors need correction and rechecking; nonblocking warnings may remain if disclosed. Record incomplete status when writes have occurred but the operation cannot finish, and report any logging failure. Multi-file updates are not atomic and successful writes are not automatically rolled back.
- Workflows run on request. Web changes require ingesting the source again; checks can detect local source file changes. Directory separation is not a filesystem sandbox. The agent's configuration and model service determine access and how content sent to a remote model is handled.

## Documentation and contributions

| Entry point | Purpose |
| ----------- | ------- |
| [SKILL.md](SKILL.md) | Task routing and core guardrails |
| [Policy index](references/README.md) | Workflow rules |
| [Synthesis policy](references/synthesis-policy.md) | Page criteria, deferred topics, and periodic review |
| [Preflight](references/preflight.md) | Workspace, skill, knowledge base, and tool paths |
| [Provenance and updates](references/provenance-policy.md) | Citations, source versions, and change propagation |
| [Lint policy](references/lint-policy.md) | Write checks and safe repair scope |
| [Page templates](templates/) | Generated page structures |
| [AGENTS.md](AGENTS.md) | Repository development rules |
| [Golden Sample](references/golden-sample.md) | Minimum workflow regressions |

Reproducible issues and focused pull requests are welcome. For changes, have the agent follow `AGENTS.md` and complete its consistency and regression checks.

## License

A license has not been selected; this repository currently has no `LICENSE` file.
