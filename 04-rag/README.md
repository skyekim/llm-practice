# 04 – RAG

Question answering over the full text of the postings from exercise 2.
`build_index.py` splits each posting into chunks, embeds them with
all-MiniLM-L6-v2, and stores them in a pgvector `chunks` table.
`search_test.py` prints the closest chunks for a query, and `answer.py`
retrieves the top 10 chunks and has Claude Haiku 4.5 answer from them with
chunk ID citations.

## Questions and Answers

### 1. What is an embedding, and why did you chunk the postings?

An embedding is a list of numbers that represents what a text means.
all-MiniLM-L6-v2 turns any text into 384 numbers, and texts with similar
meanings get vectors that are close together. In `embedding_tests.py`,
"remote work" is close to "work from home" even though they share no words,
and far from "studying computer science". Search works by embedding the
question the same way and asking Postgres for the closest chunks
(`ORDER BY embedding <=> query`).

A whole posting covers the company, the role, requirements, benefits, and
salary. One vector for all of that blurs every topic together, so a question
about benefits would only weakly match any posting. With chunks, each
paragraph gets its own vector and a search can land on the one that answers
the question.

The postings are organized into sections, so I split on blank lines and
merged short pieces (under 50 characters), like a lone "Requirements"
heading, into the paragraph after them. That gave 130 chunks. One limit
mattered later: the model only reads about the first 1,000 characters of a
chunk and silently ignores the rest.

### 2. How did semantic search compare with keyword search?

I ran the same questions as plain `ILIKE` queries:

| Question | Keyword search | Semantic search |
| --- | --- | --- |
| Visa sponsorship | Found Bevel | Found Bevel, barely (0.345) |
| Five days in office | Found Edra, Guac, Sola | Missed Sola |
| Mentoring | Found Lorum | Missed it |
| Immigration | 0 rows | Missed Bevel's visa line |
| Four-day week | 0 rows (correct) | None found (correct) |

Keyword search won whenever the exact word was in the text, no matter where.
It found "mentor" at character 1,594 of a 1,664-character chunk, past the
point the embedding model reads. But it only finds the words you think to
type: "immigration" returned nothing because the posting says "visa", and
the five-day query needed both `'%5 days%'` and `'%five days%'`.

Semantic search should win on synonyms, but it didn't find Bevel for
"immigration" either. The visa line is one item in a ten-item benefits list,
so the chunk as a whole is about "benefits", not immigration. The two methods
fail in different ways, which is why many real systems run both and combine
the results.

### 3. How did changing k and chunk size affect the answers?

Chunk size: I split any chunk over 300 characters at line breaks, which
raised the count from 130 to 185 chunks. This fixed mentoring. Lorum's
"Share knowledge, mentor peers" sentence went from cut off at the end of a
long chunk to its own short chunk, and it ranked first (0.543). It didn't
help visa or immigration: Bevel's benefits list is 263 characters, under the
limit, so it didn't change and scored exactly the same. Sola's "5 days a
week" line is now in a smaller chunk but is still one of three bullets about
skills, and still missed the top 5.

The first version had a side effect: when a heading was followed by a long
one-line paragraph, the split separated them, so chunks like "The Role" and
"About Lorum" came back as results on their own. I fixed it by never ending
a chunk while it's still under 50 characters.

k: Raising TOP_K from 5 to 10 fixed three questions. Bevel's benefits chunk 
ranked 9th and Sola's "5 days a week" chunk ranked 8th, so with k = 5 they 
were cut off, and with k = 10 Claude found them and answered correctly. 
"Which companies use Kubernetes?" went from naming only Current to all five 
companies. Immigration still failed, because Bevel's visa chunk wasn't in 
the top 10 either. A bigger k only helps when the right chunk ranks close 
to the cutoff. The extra chunks were mostly loosely related, but the model 
ignored them and cited only the relevant ones. Input tokens roughly doubled 
(433 → 785 for the Bevel question), but each question still cost about $0.001, 
so I kept k = 10.

### 4. Did the model ever answer from outside the excerpts, or fail to say "I don't know"?

It never made up an answer. When the excerpts didn't have it, it said so:
for hybrid jobs, Bevel's benefits, and immigration. It also correctly said
no company offers a four-day work week, and it noticed that Giga's chunk
describes being mentored, not mentoring others.

There were two smaller problems. In the first run it said "no company
offers a 4-day work week" after seeing 5 chunks from 4 companies; later runs
correctly said "in the excerpts". And it was too cautious once: it said
Mistral's Kubernetes chunk "doesn't specify which company", even though the
label said `mistral`.

The bigger issue is that its honest "I don't know" answers were often wrong
for me. Hazel's posting says "Hybrid in NYC" and Bevel's has a benefits
section, but with k = 5 those chunks weren't retrieved. The model can only be as
good as the chunks it's given, so retrieval was the weak link, not the
model.

### 5. What kinds of questions does RAG handle badly?

- Facts buried in lists: "visa sponsorship" is one line among ten
  benefits, so "Which companies help with immigration?" missed it.
- Text past the model's cutoff: mentoring was invisible until the chunks
  got smaller.
- Questions that name a company: "What benefits does Bevel offer?" returned
  five Bevel chunks, but the intro, history, and diversity statement instead
  of the benefits section, which ranked 9th. The company name outweighed
  "benefits". Raising k worked around it, but filtering
  to the company's chunks first (`WHERE p.slug = 'bevel'`) and then ranking
  would fix this.
- Vague questions: "What does the company build" doesn't name a company,
  so it returned general company pitches with scores all between 0.41 and
  0.48.
- Questions about every posting: five postings mention Kubernetes, but
  with k = 5 "Which companies use Kubernetes?" only named Current. k = 10
  found all five, but any fixed k runs out once more postings match than
  chunks are retrieved. Like the counting question in exercise 3, "list
  all" questions are better answered by structured data.
