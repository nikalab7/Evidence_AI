# Interview demo: Cyma Watches multi-hop investigation

## Status

The project owner supplied this successful response from the public EvidenceAI
interface. It is a real owner-reported live example; this workspace did not
replay the request or inspect its Render logs. The response body shows two
different cited chunks. The corresponding `investigation_memory` measurement
is still needed for an observed latency/RSS comparison.

## Question and answer

**Question:** The company that oversees Cyma Watches was founded when?

This question matches development-set record
`5ae13bf8554299422ee99635` in `eval/retrieval_dev.jsonl`; its expected answer is
1894 and its supporting titles match the two-source response.

**Reported answer:** Cyma SA is owned by Stelux International, Ltd. and is
overseen by Universal Genève, which was founded in 1894.

## Evidence chain

The question requires linking an entity in one document to a second document
that contains the requested date:

1. **Cyma Watches** — retrieved chunk
   `65ade0ad07ef97358294bb52625e0881ddb3ed81ae904b1d3db3bdf11ddd2ac7`

   > The company is currently owned by Stelux International, Ltd. a Hong Kong-based holdings firm which invests primarily in fine jewellery and watches, and is overseen by fellow "Fédération de L'industrie Horlogère Suisse" member Universal Genève.

2. **Universal Genève** — retrieved chunk
   `e2da6126dc58ca6cbe26d1d7b03372085c3f758bbc1fdeac5c9746052fff2e80`

   > Universal Genève SA is a Swiss luxury watch company, founded in 1894 as "Universal Watch".

The first quote establishes the bridge from Cyma Watches to Universal Genève.
The second provides the date, 1894. The response reports exact quotes and two
distinct chunk IDs, so it is a stronger demonstration than retrieving one
isolated fact.

## What to explain in the interview

1. The user asks about the founding year of the company overseeing Cyma Watches.
2. A paragraph about Cyma Watches identifies Universal Genève as that company.
3. A different paragraph about Universal Genève states its founding year.
4. The final response combines the two pieces and shows a citation for each.
5. The citation validator checks that the chunk IDs are in the retrieved
   evidence and that each quote occurs verbatim after whitespace normalization.

The response excerpt does not reveal the agent's actual tool-call sequence, so
do not claim a specific number of searches or Gemini calls from this example.
Exact quote validation proves that the cited text was present; it does not by
itself prove factual entailment. The reader should still assess whether the
first quote supports the entity link and the second supports the date. In the
owner-shared UI excerpt, both source links point to the HotpotQA dataset page;
the displayed source titles and exact quotes identify the cited passages.

## Live memory measurement still needed

The earlier owner-reported simple investigation had **2.9497 seconds** elapsed,
**309,981,184 bytes** peak RSS, and **5,660,672 bytes** reported RSS growth. Those
values were not independently verified in this workspace. The Cyma example's
matching `investigation_memory` event was not available locally, so its latency
and memory values are not yet known and cannot be compared yet.

In Render, open the Frankfurt service's **Logs** and search for
`investigation_memory`. Correlate the event timestamp with the Cyma request
time; the application deliberately does not log the question text. Copy the
sanitized JSON event containing at least:

- `elapsed_seconds`
- `peak_rss_bytes`
- `rss_before_bytes`, `rss_after_bytes`, and `rss_growth_bytes`
- `concurrent_at_start` and `peak_concurrent_investigations`
- `outcome` and `sampled_peak_below_limit`

The event can be pasted here without credentials or question text. Compare
`peak_rss_bytes` with the simple-question value and Render's 536,870,912-byte
limit. A single multi-hop request is one sample, not a repeated or concurrent
memory-safety test.
