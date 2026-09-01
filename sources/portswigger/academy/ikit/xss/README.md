# Ikit XSS Core v1

First real XSS source corpus for Swarmblight's Ikit / InjectionRat.

## Included source pages

1. Cross-site scripting overview
2. Reflected XSS
3. Stored XSS
4. XSS contexts
5. Exploiting XSS
6. Preventing XSS
7. Content Security Policy
8. Dangling markup injection

## Deliberately excluded

- DOM-based XSS and the wider DOM-based vulnerability corpus (separate future DOM curriculum)
- PortSwigger XSS cheat sheet / bulk payload catalog
- Lab solution write-ups
- LAB / Solved / Not solved callout blocks

## Forge intent

These files are source material, not KnowledgeCards. The V0.6 forge should chunk,
distill, critique, validate and deduplicate them before any card is approved.

Suggested ingestion metadata:

- agent: ikit
- source-type: academy
- topic: xss

Example:

    python forge.py ingest .\sources\ikit_xss_core_v1\01_xss_overview.md --agent ikit --source-type academy --topic xss

Then build the returned document id with:

    python forge.py build <document-id>
