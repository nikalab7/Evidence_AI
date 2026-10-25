# Demo walkthrough: Cyma Watches multi-hop investigation

## Question and answer

**Question:** The company that oversees Cyma Watches was founded when?

This question is development-set record `5ae13bf8554299422ee99635` in
`eval/retrieval_dev.jsonl`. Its expected answer is 1894.

**Answer from the live demo:** Cyma SA is owned by Stelux International, Ltd.
and is overseen by Universal Genève, which was founded in 1894.

## Evidence chain

The question needs two documents: one that links Cyma Watches to its overseeing
company, and one that gives that company's founding date.

1. **Cyma Watches**, chunk
   `65ade0ad07ef97358294bb52625e0881ddb3ed81ae904b1d3db3bdf11ddd2ac7`

   > The company is currently owned by Stelux International, Ltd. a Hong Kong-based holdings firm which invests primarily in fine jewellery and watches, and is overseen by fellow "Fédération de L'industrie Horlogère Suisse" member Universal Genève.

2. **Universal Genève**, chunk
   `e2da6126dc58ca6cbe26d1d7b03372085c3f758bbc1fdeac5c9746052fff2e80`

   > Universal Genève SA is a Swiss luxury watch company, founded in 1894 as "Universal Watch".

The first quote links Cyma Watches to Universal Genève. The second provides the
date. The response cites two distinct chunks, one for each step.

## How the answer is checked

1. The agent runs up to four searches and collects evidence from both
   documents.
2. The final answer lists claims with chunk IDs and exact quotes.
3. The citation validator accepts a citation only if its chunk was retrieved
   during this investigation and the quote appears verbatim in that chunk
   (after whitespace normalization).

Exact quote validation shows that the cited text is present. It does not by
itself prove that the text entails the claim, so the reader can still judge
whether each quote supports its step.

## Resource use

One recorded simple investigation on Render took 2.95 seconds, with a peak RSS
of 309,981,184 bytes (about 296 MiB) against Render Free's 512 MiB limit. The
app logs these values as a sanitized `investigation_memory` event that does not
include the question text. A single request is one sample, not a test of
repeated or concurrent load.
