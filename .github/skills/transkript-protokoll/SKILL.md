---
name: transkript-protokoll
description: Creates compact, professional German meeting minutes from pasted or uploaded conversation, meeting, or interview transcripts and returns them by default as downloadable Markdown and PDF files. Use when users want meeting minutes, a protocol, session notes, an outcome summary, or an action list from a transcript. Condenses repetition and small talk, assigns speakers from direct clues and known team context whenever possible, separates decisions, key points, and open questions, and ends with action items and responsibilities.
---

# Transcript Minutes

Create compact German meeting minutes directly from a transcript. Do not ask follow-up questions when the transcript is usable enough. Mark missing information neutrally.

## Workflow

1. Read the full transcript.
2. Assign speakers systematically:
   - first evaluate direct self-introductions, name mentions, and direct address;
   - then compare project content, roles, typical topics, reply relationships, and speaking order;
   - for KATALYST team meetings, also use `references/team-sprecherzuordnung.md`;
   - check assignments for consistency across the full transcript.
3. Remove small talk, repetition, digressions, and purely technical conversation fragments.
4. Organize the content into four categories:
   - outcomes and decisions
   - key discussion points
   - open questions or pending decisions
   - action items and responsibilities
5. Merge duplicate statements and tighten the wording.
6. Create the minutes using `assets/protokoll-vorlage.md`.
7. Produce the same final version as a UTF-8 Markdown file and as a PDF file.
8. Visually render the PDF and check for clipped text, broken tables, overlaps, and corrupted characters.
9. Return download links for both files in the chat.

## Speaker assignment

- Actively assign speakers whenever possible; do not stay with anonymous speaker labels too quickly.
- Direct clues take priority over role or topic profiles.
- Finalize an assignment only after comparing multiple contributions.
- With strong evidence, use the name without qualification.
- With medium evidence, use `Name (Zuordnung wahrscheinlich)` in the metadata note.
- With weak or conflicting evidence, keep the original speaker label.
- Do not invent names or infer identity from voice, gender, or stereotypes.
- Assign tasks to a person only when the transcript and speaker mapping are sufficiently clear together; otherwise use `Nicht zugeordnet`.

## Required quality rules

- Write in neutral, factual, professional German.
- Target outcome-oriented meeting minutes, not a chronological retelling.
- Typical length: about 1 to 2 pages or roughly 400 to 900 words. Go beyond that only for very large or decision-heavy meetings.
- Do not quote contributions verbatim unless exact wording is essential.
- Mark something as a decision only when it was explicitly agreed or follows unambiguously from the conversation.
- Do not present suggestions, assumptions, or discussion ideas as decisions.
- Mark missing deadlines with `Offen`.
- Quietly correct obvious transcription errors when the meaning is clear. Mark uncertain terms with `[unklar]` or rephrase them neutrally.
- Omit sensitive small talk, private side conversations, disparaging statements, and irrelevant product promotion.
- Phrase tasks concretely and actionably: verb + object + expected outcome.
- Output the `Hausaufgaben und Verantwortlichkeiten` section as the last content section.
- Omit empty optional sections.
- Markdown and PDF must be identical in content.

## Metadata

Carry over the following information when it is available from the transcript or file name:

- date
- topic or meeting title
- participants
- source or transcript file
- next meeting

If a key field is missing, use `Nicht angegeben`. Do not ask follow-up questions only because metadata is missing.

If at least one speaker assignment is only probable, add a short italic uncertainty note after the metadata. Do not include a detailed justification in the minutes.

## Output files

- Base name: `Protokoll_<YYYY-MM-DD>_<short-topic-slug>`
- If the date or topic is missing: `Protokoll`
- Generate:
  - `<base-name>.md`
  - `<base-name>.pdf`
- Use the available PDF or document tooling for PDF generation. For text-heavy minutes, Markdown may be converted cleanly to PDF directly or exported through a document format.
- Render the PDF to images after generation and inspect it visually.
- Offer only the final files for download; do not link intermediate artifacts.
- If PDF generation is unavailable, create the Markdown file and clearly state that the PDF could not be created.

## Resources

- `assets/protokoll-vorlage.md`: required base structure for the minutes.
- `references/team-sprecherzuordnung.md`: team roles and topic hints for KATALYST speaker assignment.
- `references/agent-prompt.md`: standalone prompt for an AI agent or other automation.
