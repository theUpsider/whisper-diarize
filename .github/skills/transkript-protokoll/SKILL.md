---
name: transkript-protokoll
description: Erstellt aus eingefuegten oder hochgeladenen Gespraechs-, Meeting- oder Interviewtranskripten ein kompaktes, professionelles deutschsprachiges Besprechungsprotokoll und gibt es standardmaessig als herunterladbare Markdown- und PDF-Datei aus. Verwenden, wenn Nutzer ein Protokoll, Meetingprotokoll, Sitzungsprotokoll, Ergebnisprotokoll oder eine Aufgabenliste aus einem Transkript wuenschen. Verdichtet Wiederholungen und Smalltalk, ordnet Sprecher anhand direkter Hinweise und bekannten Teamkontexts bestmoeglich zu, trennt Beschluesse, Kernpunkte und offene Fragen und schliesst mit Hausaufgaben und Verantwortlichkeiten ab.
---

# Transkript-Protokoll

Aus einem Transkript direkt ein kompaktes Ergebnisprotokoll erzeugen. Keine Rueckfragen stellen, wenn das Transkript ausreichend verwertbar ist. Fehlende Angaben neutral kennzeichnen.

## Arbeitsablauf

1. Das gesamte Transkript lesen.
2. Sprecher systematisch zuordnen:
   - zuerst direkte Selbstvorstellungen, Namensnennungen und Ansprachen auswerten;
   - danach Projektinhalte, Rollen, typische Themen, Antwortbeziehungen und Reihenfolge der Redebeitraege abgleichen;
   - bei KATALYST-Teammeetings zusaetzlich `references/team-sprecherzuordnung.md` verwenden;
   - Zuordnungen ueber das gesamte Transkript auf Konsistenz pruefen.
3. Smalltalk, Wiederholungen, Abschweifungen und rein technische Gespraechsfragmente entfernen.
4. Inhalt in vier Kategorien ordnen:
   - Ergebnisse und Beschluesse
   - wesentliche besprochene Punkte
   - offene Fragen oder Entscheidungen
   - Hausaufgaben und Verantwortlichkeiten
5. Doppelte Aussagen zusammenfuehren und die Formulierungen verdichten.
6. Das Protokoll anhand von `assets/protokoll-vorlage.md` erstellen.
7. Dieselbe finale Fassung als UTF-8-Markdown-Datei und als PDF-Datei erzeugen.
8. Die PDF visuell rendern und auf abgeschnittenen Text, fehlerhafte Tabellen, Ueberlagerungen und defekte Zeichen pruefen.
9. Im Chat beide Download-Links ausgeben.

## Sprecherzuordnung

- Sprecher aktiv und bestmoeglich zuordnen; nicht vorschnell bei anonymen Sprecherlabels bleiben.
- Direkte Hinweise haben Vorrang vor Rollen- oder Themenprofilen.
- Eine Zuordnung erst nach Abgleich mehrerer Beitraege festlegen.
- Bei hoher Evidenz den Namen ohne Zusatz verwenden.
- Bei mittlerer Evidenz im Metadatenhinweis `Name (Zuordnung wahrscheinlich)` verwenden.
- Bei schwacher oder widerspruechlicher Evidenz das originale Sprecherlabel beibehalten.
- Keine Namen erfinden und keine Zuordnung allein aus Stimme, Geschlecht oder allgemeinen Stereotypen ableiten.
- Aufgaben nur dann einer Person zuordnen, wenn Transkript und Sprecherzuordnung gemeinsam ausreichend klar sind; sonst `Nicht zugeordnet` verwenden.

## Verbindliche Qualitaetsregeln

- Neutral, sachlich und professionell auf Deutsch schreiben.
- Auf ein Ergebnisprotokoll zielen, nicht auf eine chronologische Nacherzaehlung.
- Typischer Umfang: etwa 1 bis 2 Seiten beziehungsweise 400 bis 900 Woerter. Nur bei sehr umfangreichen oder entscheidungsreichen Sitzungen darueber hinausgehen.
- Keine Gespraechsbeitraege woertlich wiedergeben, ausser ein exakter Wortlaut ist entscheidend.
- Nur ausdruecklich vereinbarte oder eindeutig aus dem Gespraech folgende Beschluesse als Beschluesse ausweisen.
- Vorschlaege, Vermutungen und Diskussionsideen nicht als Entscheidungen darstellen.
- Fehlende Fristen mit `Offen` kennzeichnen.
- Offensichtliche Transkriptionsfehler still korrigieren, wenn die Bedeutung eindeutig ist. Unsichere Begriffe mit `[unklar]` markieren oder neutral umformulieren.
- Sensiblen Smalltalk, private Nebengespraeche, abwertende Aussagen und irrelevante Produktwerbung weglassen.
- Aufgaben konkret und handlungsorientiert formulieren: Verb + Gegenstand + erwartetes Ergebnis.
- Die Sektion `Hausaufgaben und Verantwortlichkeiten` als letzte inhaltliche Sektion ausgeben.
- Leere optionale Sektionen weglassen.
- Markdown und PDF muessen inhaltlich identisch sein.

## Metadaten

Folgende Angaben uebernehmen, wenn sie aus Transkript oder Dateinamen hervorgehen:

- Datum
- Thema beziehungsweise Sitzungsname
- Teilnehmende
- Quelle beziehungsweise Transkriptdatei
- naechster Termin

Fehlt eine zentrale Angabe, `Nicht angegeben` verwenden. Keine Rueckfrage nur wegen fehlender Metadaten stellen.

Wenn mindestens eine Sprecherzuordnung nur wahrscheinlich ist, nach den Metadaten einen kurzen kursiven Hinweis zur Unsicherheit einfuegen. Keine ausfuehrliche Herleitung im Protokoll darstellen.

## Ausgabedateien

- Basisname: `Protokoll_<YYYY-MM-DD>_<kurzer-themen-slug>`
- Wenn Datum oder Thema fehlen: `Protokoll`
- Erzeugen:
  - `<Basisname>.md`
  - `<Basisname>.pdf`
- Fuer die PDF-Erzeugung die verfuegbaren PDF- oder Dokumentwerkzeuge verwenden. Bei textlastigen Protokollen kann Markdown direkt sauber in PDF umgewandelt oder ueber ein Dokumentformat exportiert werden.
- PDF nach der Erzeugung in Bilder rendern und visuell pruefen.
- Nur die finalen Dateien als Download anbieten; Zwischenartefakte nicht verlinken.
- Wenn keine PDF-Erstellung verfuegbar ist, die Markdown-Datei erzeugen und transparent angeben, dass die PDF nicht erstellt werden konnte.

## Ressourcen

- `assets/protokoll-vorlage.md`: verbindliche Grundstruktur fuer das Protokoll.
- `references/team-sprecherzuordnung.md`: Teamrollen und Themenhinweise fuer KATALYST-Sprecherzuordnungen.
- `references/agent-prompt.md`: eigenstaendiger Prompt fuer einen KI-Agenten oder eine andere Automatisierung.
