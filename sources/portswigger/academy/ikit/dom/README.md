# Ikit DOM Core v1

DOM curriculum for Swarmblight's Ikit / InjectionRat.

## Contents

19 Academy-derived source documents covering the general DOM/taint-flow model
and the vulnerability-specific branches supplied in the source corpus:

1. DOM overview and taint flow
2. DOM XSS
3. Open redirection
4. Cookie manipulation
5. JavaScript injection
6. document.domain manipulation
7. WebSocket URL poisoning
8. Link manipulation
9. Web-message manipulation
10. Ajax request-header manipulation
11. Local file-path manipulation
12. Client-side SQL injection
13. HTML5 storage manipulation
14. Client-side XPath injection
15. Client-side JSON injection
16. DOM-data manipulation
17. DOM denial of service
18. Web messages as a source
19. DOM clobbering

## Cleaning

Removed from the supplied Academy text:

- LAB / LABS callouts
- APPRENTICE / PRACTITIONER / EXPERT labels
- Solved / Not solved statuses
- lab navigation UI
- URL validation bypass cheat-sheet reference
- DOM Invader documentation navigation label

Preserved:

- conceptual explanations
- source/sink lists
- code examples
- exploitability/impact discussion
- prevention guidance

Lab solution write-ups and bulk cheat sheets are intentionally excluded.

These are source documents for the V0.6 Knowledge Forge, not approved KnowledgeCards.

Example ingestion:

    python forge.py ingest .\sources\ikit_dom_core_v1\01_dom_overview.md --agent ikit --source-type academy --topic dom

Then:

    python forge.py build <document-id>
