# Serving: local or cloud models

DRYDOCK runs one graph over swappable model backends. The `fake` provider is bound by
default and is the only one the tests, the bench and CI ever use. Every other provider is
an explicit act: name it on the command line, and have its credentials in the environment.

```bash
uv run drydock build acme-treasury --provider fake        # default; offline, deterministic
uv run drydock build acme-treasury --provider ollama      # local model over the OpenAI-compatible API
uv run drydock build acme-treasury --provider vllm        # same adapter, a vLLM server
uv run drydock build acme-treasury --provider bedrock     # Amazon Bedrock converse API
uv run drydock build acme-treasury --provider anthropic   # Anthropic Messages API
```

The provider changes who writes the plan and the code. It changes nothing about the
harness, the sandbox, the checks, the iteration budget or the approval gate.

## Provider matrix

Each provider is a yaml file, `configs/providers/<name>.yaml`. The yaml names the backend,
the model, an endpoint where one applies, and the *name* of the environment variable that
holds the credential. No yaml file contains a secret.

| Provider | Backend | Runs where | Credential | Extra install |
|---|---|---|---|---|
| `fake` | templates plus seeded fault injection | in process | none | none |
| `ollama` | `openai_compat` over `httpx` | your machine | `OPENAI_API_KEY` (any value) | none |
| `vllm` | `openai_compat` over `httpx` | your GPU host | `OPENAI_API_KEY` (if the server wants one) | none |
| `bedrock` | `boto3` `converse` | your AWS account | AWS credential chain, `AWS_REGION` | `uv sync --extra bedrock` |
| `anthropic` | `anthropic` SDK | Anthropic's API | `ANTHROPIC_API_KEY` | `uv sync --extra anthropic` |

Ollama ignores the API key, but the shared adapter sends whatever `OPENAI_API_KEY` holds as
a bearer token, so the variable must be set to something. For vLLM it must match the value
the server was started with under `--api-key`, if any.

`load_provider` reads the yaml, resolves the credential variable, and raises a
`ProviderError` naming the variable or the missing extra when either is absent. The error
is the whole message; nothing is retried against a half-configured backend.

### Starting each backend

**fake.** Nothing to start. The plan is derived from the spec, the code is rendered from
templates, and the defect declared in the corpus manifest is applied on iteration 1 and
repaired on iteration 2. Zero tokens are recorded.

**Ollama.** Install Ollama, pull the model named under `model:` in
`configs/providers/ollama.yaml`, and confirm the OpenAI-compatible endpoint answers.

```bash
ollama pull <model-from-yaml>
curl http://localhost:11434/v1/models
export OPENAI_API_KEY=ollama        # any non-empty value
uv run drydock build acme-treasury --provider ollama
```

The yaml's `base_url` points at `http://localhost:11434/v1`. Change it if Ollama is on
another host.

**vLLM.** Start the OpenAI-compatible server with Docker, pointing it at the model the yaml
names. The one-liner below assumes an NVIDIA GPU and the NVIDIA container toolkit.

```bash
docker run --rm --gpus all -p 8000:8000 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:latest --model <model-from-yaml>
export OPENAI_API_KEY=unused        # or the key you passed with --api-key
uv run drydock build acme-treasury --provider vllm
```

The yaml's `base_url` points at `http://localhost:8000/v1`. If the server was started with
`--api-key`, put that value in `OPENAI_API_KEY`.

**Bedrock.** The adapter uses the `converse` API through `boto3`, so credentials come from
the default chain: environment variables, a shared credentials file, an SSO session, or an
instance role. Set `AWS_REGION` to a region where the model in the yaml is enabled.

```bash
uv sync --extra bedrock
export AWS_REGION=us-east-1         # a region where the model is enabled for your account
uv run drydock build acme-treasury --provider bedrock
```

The calling identity needs `bedrock:InvokeModel` on the model ARN. Model access is also
gated per account in the Bedrock console; an `AccessDeniedException` with valid credentials
usually means the model has not been enabled there, not that IAM is wrong.

**Anthropic.**

```bash
uv sync --extra anthropic
export ANTHROPIC_API_KEY=...
uv run drydock build acme-treasury --provider anthropic
```

On Windows PowerShell, replace `export NAME=value` with `$env:NAME = "value"`.

## Data perimeter

This is the part that matters when the spec belongs to a client. The first table lists
exactly what leaves the DRYDOCK process when a real provider is used; the second says where
it goes for each provider. Everything not in the first table stays on the machine running
the graph.

| What leaves the process | Source | When |
|---|---|---|
| Feed contract: the yaml block from `spec.md` (columns, formats, quirks list) | `FeedSpec` | plan and generate |
| Column profiles: row count, signed amount total, null rates, distinct counts | `profile_sample` tool | plan |
| Sample file name, size and sha256 | `list_samples`, `profile_sample` | plan |
| Peeked rows: at most 5 raw lines per sample file, capped in the server | `peek_sample` tool | plan |
| The output contract and one clean template rendering as a worked example | `prompts.py` | generate |
| Previous iteration's `pipeline.py`, `dag.py`, `mapping.yaml` | run store | repair only |
| Harness findings: check id, message, evidence (counts, first 3 bad rows) | `HarnessReport.errors` | repair only |

| Provider | Where the rows above go |
|---|---|
| `fake` | nowhere; nothing leaves the process and no network call is made |
| `ollama` | `base_url` in the yaml, `http://localhost:11434/v1` by default, so the same host |
| `vllm` | `base_url` in the yaml, the machine running the vLLM server |
| `bedrock` | Amazon Bedrock in your AWS account and `AWS_REGION` |
| `anthropic` | Anthropic's API |

Never sent to any provider, under any configuration:

- Whole sample files. The planner has no tool that returns more than five lines, and the
  cap is enforced in the sources server, not in the prompt.
- Anything under `deploy/`. Approved artifacts are written by `publish` and read by
  nothing in the provider path.
- The SQLite store, checkpoints, `events.jsonl`, or other clients' specs and samples.
- Credentials. The yaml holds variable names; the adapters read the values and put them in
  request headers or SDK clients, never in a prompt.

Two consequences worth stating plainly. First, "to localhost" for Ollama means the data
stays on the host, which is the point of the local option; if you move `base_url` to a
shared inference box, the perimeter is that box. Second, the harness findings on repair
include up to three offending rows as evidence for H2, so with a real provider a small
number of transformed rows can travel in addition to the five peeked raw lines. The corpus
is synthetic, so none of this matters here; it would matter for a real client and the
number is bounded by design.

## Tracing with LangSmith

LangGraph emits LangSmith traces when the standard environment toggle is on. It is off by
default and nothing in the repository sets it.

```bash
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=...
export LANGCHAIN_PROJECT=drydock
uv run drydock build acme-treasury --provider fake
```

Traces show each node as a span with the state delta, including the interrupt at
`await_approval` and the resume from a later process. Tracing also sends node inputs and
outputs to LangSmith, which widens the data perimeter above to include LangSmith; leave it
off for anything you would not send to a third party.

Trace links are added to `docs/ship-report.md` only once a recorded run exists. Until then
the ship report lists LangSmith tracing as a documented toggle, not as an observed trace.

## Token usage and events

Every node appends one JSON line to `runs/<run_id>/events.jsonl` with at least `node`,
`iteration`, `ms` and `outcome`. When a real provider is used, `LLMProvider` fires an
`on_usage` callback per model call and the graph writes a line to the same file carrying
`model`, `prompt_tokens`, `completion_tokens` and `latency_ms`, alongside the node name and
iteration. The fake provider records zero tokens. There is no aggregated cost figure anywhere in the repository
because no live run has been recorded; when one is, the sum over `events.jsonl` is the
figure to report, and it belongs in the ship report as observed, not here as a claim.

## What is and is not measured

- The bench and the results card in the README are produced with `fake`. They measure the
  harness, the sandbox and the loop, not any model.
- No accuracy, latency, cost or token count is claimed for `ollama`, `vllm`, `bedrock` or
  `anthropic`. The corresponding rows on the results card read *pending* until a recorded
  run exists.
- The adapters are unit-tested against fake transports and fake SDK clients, so the request
  shape is tested; the live services are not exercised by the gate.
