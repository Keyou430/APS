# Knowledge Answer and Workbench Design

## Goal

Restore real answers for knowledge-grounded chat and make the knowledge detail
and conversation surfaces practical, high-density enterprise workspaces.

## Boundaries

- Keep token-bound organization context, membership permissions, server-owned
  session scope, nullable legacy `source_ids`, and citation authorization as-is.
- Do not add a migration, anonymous sharing, external guests, delivery, or
  credentials to the repository.
- Keep the knowledge backend isolated from the general agent backend.

## Knowledge Answer Contract

Knowledge chat continues to retrieve only authorized excerpts and stores the
turn plus citations before the stream begins. In a real deployment,
`HERMES_USE_HTTP` must be enabled and knowledge sessions must use the dedicated
`HERMES_KNOWLEDGE_API_URL` service. The service receives the user question as
`input` and the platform-built authorized knowledge instructions separately.

A successful knowledge turn must provide all of the following:

1. an assistant message with non-empty content;
2. a completed stream event;
3. a stable, explicit association between the terminal assistant message and
   the chat turn; and
4. only citations already recorded for that turn.

`associate_terminal_message` must reject a blank terminal output and must only
match a newly created assistant message whose stripped content is non-empty.
An empty output, an empty matched message, an unstable message id, or no exact
match is recorded as `failed`; `association_unavailable` is not exposed as a
separate product state. A stream that ends without a terminal event is recorded
as `interrupted`, never `completed`. Message association runs only after an
observed completed terminal event.

The `knowledge.context` event is emitted before the first upstream run event,
after the turn and its citations have committed. Its delivery therefore does
not depend on Hermes emitting `run.created` first.

Historical citations are intentional turn snapshots. They are returned only
for the recorded turn and are not re-authorized when chat history is read.

## Conversation Workspace

The existing session sidebar remains. The main surface becomes a compact
enterprise workspace:

- Header: conversation title, knowledge scope, run state, and grouped actions.
- Retrieval strip: retrieval mode, citation count, rejected-source count, and
  clear states for retrieving, ready, and failed.
- Messages: readable assistant content panels, distinct user messages, and a
  dedicated citation area below each answer.
- Composer: stable input boundary, concise status feedback, and disabled state
  while a request is active.

The mobile session drawer and current accessibility labels stay intact.

The retrieval strip uses product states derived from existing data rather than
adding database status values:

- `retrieving`: a knowledge request is active before context is available;
- `ready`: context is available while streaming, or the latest persisted turn
  is `completed` with a non-empty associated assistant message; and
- `failed`: the current stream failed, or the persisted turn is `failed` or
  `interrupted`.

After refresh, the strip is rebuilt from the latest assistant message's
`turn_id`, `retrieval_mode`, `turn_status`, and citations. Failed or interrupted
turns render an explicit answer-generation failure panel instead of an empty
assistant bubble. Cancelled and stopped turns retain their distinct wording.

No migration is introduced for `rejected_source_count`. During streaming the
value is the turn-time count returned by retrieval. On history reads for a
selected scope, the API derives a current unavailable-source count as the
difference between the session's currently selected source ids and those still
visible through the current authorization repository. For `all_visible` and
`none`, it is zero. This refreshed value deliberately describes current session
scope and current authorization, not historical authorization at turn time;
the UI labels it accordingly.

## Knowledge Detail Workspace

The detail drawer widens on desktop and begins with a resource summary:
document type, access visibility, access source, update time, and description.
The overview, content, access, and activity tabs remain permission-gated, but
use denser workbench navigation, readable long-form preview, consistent loading
and empty states, and structured access/audit rows. On mobile the drawer stays
full-screen.

## Verification

Tests must first demonstrate the failure cases for non-empty knowledge answers,
empty completed upstream output, retrieval-state rendering, and detail/chat
information hierarchy. The completed work is verified through targeted backend
and web tests, full regression, a non-production deployment, and Browser
acceptance using a real authorized knowledge source. Browser cleanup must retain
at least one tab; never finalize an empty tab set.
