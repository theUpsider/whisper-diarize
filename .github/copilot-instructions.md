# Copilot Workspace Instructions

This workspace contains a reusable skill for generating meeting minutes from transcripts.

## Available Skills

### transkript-protokoll (Transcript → Meeting Minutes)

**Location:** `.github/skills/transkript-protokoll/SKILL.md`

Creates compact, professional German meeting minutes from conversation, meeting, or interview transcripts as Markdown and PDF files.

**When to use:** User asks for meeting minutes, a protocol, session notes, an outcome summary, or an action list from a transcript.

**Workflow:**

1. Run `uv run python main.py` to transcribe + diarize MP4 files → `output/final_transcript.txt`
2. Ask the agent to use the `transkript-protokoll` skill on `output/final_transcript.txt` to generate the meeting minutes

**Key files:**

- Skill definition: `.github/skills/transkript-protokoll/SKILL.md`
- Protocol template: `.github/skills/transkript-protokoll/assets/protokoll-vorlage.md`
- Team speaker mapping: `.github/skills/transkript-protokoll/references/team-sprecherzuordnung.md`
- Standalone agent prompt: `.github/skills/transkript-protokoll/references/agent-prompt.md`
