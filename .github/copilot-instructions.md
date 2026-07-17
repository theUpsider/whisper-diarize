# Copilot Workspace Instructions

This workspace contains a reusable skill for generating meeting minutes (Protokoll) from transcripts.

## Available Skills

### transkript-protokoll (Transkript → Besprechungsprotokoll)

**Location:** `.github/skills/transkript-protokoll/SKILL.md`

Erstellt aus Gesprächs-, Meeting- oder Interviewtranskripten ein kompaktes, professionelles deutschsprachiges Besprechungsprotokoll als Markdown- und PDF-Datei.

**When to use:** User asks for a Protokoll, Meetingprotokoll, Sitzungsprotokoll, Ergebnisprotokoll, or Aufgabenliste from a transcript.

**Workflow:**

1. Run `uv run python main.py` to transcribe + diarize MP4 files → `output/final_transcript.txt`
2. Ask agent to use the `transkript-protokoll` skill on `output/final_transcript.txt` to generate the protocol

**Key files:**

- Skill definition: `.github/skills/transkript-protokoll/SKILL.md`
- Protocol template: `.github/skills/transkript-protokoll/assets/protokoll-vorlage.md`
- Team speaker mapping: `.github/skills/transkript-protokoll/references/team-sprecherzuordnung.md`
- Standalone agent prompt: `.github/skills/transkript-protokoll/references/agent-prompt.md`
