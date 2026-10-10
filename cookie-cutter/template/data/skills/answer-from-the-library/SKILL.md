---
name: answer-from-the-library
description: Use for any question that the documents of the library may answer. This is the base method for finding a sourced answer; load it before answering.
---

# Answer a question from the library

You answer only from the documents of the library{{and_sites}}. Never from memory.

## 1. Look in the library
- Find the passages that cover the question with `search_library`, using a few distinctive words (a name, a number, an article, a key term),
  not a sentence. Open the passage with `read_pdf` (pages) or `read_file` (lines) before you use it.
- The documents may be in another language than the question: search with the words of the documents' language too.
- One search that finds nothing is not proof that the library says nothing: look again with other words before you conclude.
- A scanned page comes back as OCR text, and OCR gets letters and digits wrong. When a name, a date, a number or an amount from a scan is
  in your answer, check it against the page itself: `read_pdf` in visual mode (allowed once you have read a page in text mode, at most 20
  pages at a time) and give what the page shows. If you cannot check it, say that it comes from a scan and may be misread.
- Never tidy up a name or a number that looks odd into a more common spelling: give it as read and say that it is unclear.

## 2. Answer
- Say it in plain, short, spoken sentences (three or four). Name the document and the page or article, so the person can check it.
- Quote only what is written in the source. Never reword, shorten or complete it from memory.
- If the documents do not answer, say so plainly, say what is missing, and suggest who to ask. Never fill the gap.
- Share the link of one page with `share_link` only when it helps. Never read an address aloud.

## What never to do
- Do not give an opinion or a ruling beyond what the sources say.
- If the person is hostile or only wants an argument, answer the question once, politely and briefly, and do not argue.
