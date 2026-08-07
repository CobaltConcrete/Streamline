# LLM Structured-Output Test Report

Test date: 7 August 2026  
Provider: OpenCode Zen  
Endpoint used by the application: `/v1/responses`

OpenCode's current [Zen endpoint table](https://opencode.ai/docs/zen/) assigns
different endpoint families by model. In particular, DeepSeek V4 models use
`/v1/chat/completions`, while GPT models use `/v1/responses`. The application's
single OpenCode endpoint therefore does not match every advertised model.

## Purpose

This report compares the response the Stream Co-Director expects with actual
responses from the configured OpenCode models. It focuses on whether each
model can produce the strict `ReasoningResponse` JSON shape consumed by the
application.

Model output is nondeterministic. The malformed JSON examples below are the
complete outputs from the most recent evidence-capture run. Some fields differed
slightly in earlier runs, but the same schema-validation problems occurred.

## Test input

The same input was sent to every model:

- Session: The creator is introducing the stream and answering setup questions.
- Cluster ID: `llm-test-c1`
- Cluster kind: question
- Distinct viewers: 4
- Representative viewer comment: `What microphone do you use?`
- Persona: friendly and concise

## Expected decision

Based on the application rules, this is a timely, harmless question shared by
several viewers. The expected decision is `SURFACE`: privately suggest that the
creator answer it. No OBS action is appropriate, so `action_id` remains `null`
and `parameters` remains empty.

One reasonable schema-valid output is:

```json
{
  "proposals": [
    {
      "cluster_id": "llm-test-c1",
      "decision_type": "SURFACE",
      "action_id": null,
      "parameters": {},
      "representative_text": "What microphone do you use?",
      "response_angle": "Name the microphone and briefly explain why it suits the setup.",
      "relevance": 0.9,
      "rationale": "Four viewers asked a timely and harmless setup question."
    }
  ]
}
```

This is a reasoned reference answer, not a captured model response. Other
wording and relevance values could also be valid.

## Conditionally successful model

### `deepseek-v4-flash-free`

With only the application's native `text.format` JSON schema, DeepSeek returned
HTTP 200 but did not obey the schema. In the latest run it produced:

```json
{
  "proposals": [
    {
      "cluster_id": "llm-test-c1",
      "kind": "question",
      "representative_text": "What microphone do you use?",
      "surface": "SURFACE",
      "action_id": null,
      "parameters": {}
    }
  ]
}
```

Failure: `kind` and `surface` are not output-schema fields, while
`decision_type`, `response_angle`, `relevance`, and `rationale` are missing.

The request was then repeated with the complete JSON contract written directly
in the system prompt. DeepSeek returned:

```json
{
  "proposals": [
    {
      "cluster_id": "c1",
      "decision_type": "SURFACE",
      "action_id": null,
      "parameters": {},
      "representative_text": "What microphone do you use?",
      "response_angle": "Briefly name the microphone and highlight why it works well for your setup.",
      "relevance": 0.9,
      "rationale": "Common setup question from multiple viewers during the introduction, timely for the creator to answer."
    }
  ]
}
```

Result: schema validation succeeded. This is conditional success because the
current production prompt does not yet contain that explicit fallback contract.
The diagnostic used `c1` as its cluster ID, so that value differs from the
otherwise equivalent `llm-test-c1` used in the multi-model run.

## Models that returned malformed output

### `laguna-s-2.1-free`

```json
{
  "proposals": [
    {
      "action_id": null,
      "parameters": {},
      "type": "SURFACE",
      "cluster_id": "llm-test-c1",
      "confidence": 0.75,
      "reasoning": "The cluster contains a genuine question about the creator's streaming setup, which aligns with the session summary indicating the creator is answering setup questions. This is a relevant, non-hostile inquiry that the creator can promptly address.",
      "representative_text": "What microphone do you use?"
    }
  ]
}
```

Failure: it invented `type`, `confidence`, and `reasoning` instead of using
`decision_type`, `relevance`, and `rationale`; `response_angle` is also missing.

### `longcat-2.0-free`

```json
{
  "proposals": [
    {
      "action_id": null,
      "parameters": {},
      "representative_text": "What microphone do you use?",
      "decision": "SURFACE"
    }
  ]
}
```

Failure: it used `decision` instead of `decision_type` and omitted
`cluster_id`, `response_angle`, `relevance`, and `rationale`.

### `mimo-v2.5-free`

```json
[
  {
    "action": "SURFACE",
    "action_id": null,
    "parameters": {},
    "representative_text": "What microphone do you use?"
  }
]
```

Failure: the top level is a bare array instead of an object containing
`proposals`. It also used `action` instead of `decision_type` and omitted
`cluster_id`, `response_angle`, `relevance`, and `rationale`.

### `nemotron-3-ultra-free`

```json
[
  {
    "cluster_id": "llm-test-c1",
    "action": "SURFACE",
    "representative_text": "What microphone do you use?",
    "action_id": null,
    "parameters": {}
  }
]
```

Failure: the top level is a bare array, `action` is not `decision_type`, and
`response_angle`, `relevance`, and `rationale` are missing.

## Models that failed before returning proposal JSON

| Model | HTTP status | Failure point | Provider message / interpretation |
|---|---:|---|---|
| `gpt-5.6-terra` | 401 | OpenCode account authorization | `Insufficient balance.` The API key was recognized, but the workspace lacked paid credit. |
| `ling-3.0-flash-free` | 503 | Upstream availability | `Endpoint is unavailable.` The routed model deployment was not serving requests. |
| `ling-3.0-tiny-free` | 503 | Upstream availability | `Endpoint is unavailable.` The routed model deployment was not serving requests. |
| `north-mini-code-free` | 401 | Upstream provider authorization | The upstream provider returned 401 without a billing-specific explanation. This points to OpenCode/provider credentials or entitlement rather than the local JSON parser. |
| `deepseek-v4-pro` (requested as "DSV4 Max Thinking") | 401 | OpenCode account authorization | Tested through its documented `/chat/completions` endpoint with high/max reasoning requested. OpenCode returned `Insufficient balance.` before inference. |

These failures never reached application schema validation because no proposal
text was returned.

## Summary

| Model | Transport | Native schema | Outcome |
|---|---|---|---|
| `gpt-5.6-terra` | 401 | Not reached | Failed: insufficient balance |
| `deepseek-v4-flash-free` | 200 | Failed | Passed only with explicit prompt contract |
| `laguna-s-2.1-free` | 200 | Failed | Wrong and missing fields |
| `ling-3.0-flash-free` | 503 | Not reached | Failed: endpoint unavailable |
| `ling-3.0-tiny-free` | 503 | Not reached | Failed: endpoint unavailable |
| `longcat-2.0-free` | 200 | Failed | Wrong and missing fields |
| `mimo-v2.5-free` | 200 | Failed | Bare array and wrong/missing fields |
| `nemotron-3-ultra-free` | 200 | Failed | Bare array and wrong/missing fields |
| `north-mini-code-free` | 401 | Not reached | Failed: upstream authorization |
| `deepseek-v4-pro` ("DSV4 Max Thinking") | 401 | Not reached | Failed: insufficient balance |

The evidence indicates that the local JSON parser is behaving correctly. The
main compatibility problem is that OpenCode's free-model routes do not enforce
the native structured-output schema consistently. Keeping strict local Pydantic
validation while repeating the exact contract in the system prompt is the
demonstrated fallback.

## DSV4 Max Thinking test note

The OpenCode inventory and documentation do not publish a separate model ID
named `dsv4-max-thinking`. The closest and most capable DeepSeek V4 entry is
`deepseek-v4-pro`, so the test interpreted "DSV4 Max Thinking" as that model
with high/max reasoning requested.

The request used the documented `/v1/chat/completions` endpoint and the explicit
JSON contract demonstrated above. It returned in 0.64 seconds with HTTP 401:

```text
CreditsError: Insufficient balance.
```

Consequently, the model generated no answer and its JSON-following ability
could not be evaluated. This was a billing gate, not a parsing or reasoning
failure.
