---
agent: ikit
topic: xss
source_type: academy
source_title: "Dangling markup injection"
source_reference: "https://portswigger.net/web-security/cross-site-scripting/dangling-markup"
corpus: ikit_xss_core_v1
---

# Dangling markup injection

Dangling markup injection is a browser-side injection technique that may enable data capture when attacker-controlled markup can alter the HTML structure but a full XSS exploit is not available.

## Core mechanism

Suppose attacker-controlled input appears inside an HTML attribute and can terminate the current attribute or element. If a new resource-loading element or attribute can be introduced but deliberately left unterminated, the browser may consume subsequent response content as part of that attribute value until it encounters a matching delimiter.

If the resulting attribute causes an external request, portions of subsequent page content may be incorporated into the request URL.

The security consequence can therefore be data disclosure rather than JavaScript execution.

## Conditions to analyze

A dangling-markup hypothesis should distinguish:

- whether attacker input can alter markup structure;
- the exact HTML parser context;
- which delimiters can be introduced;
- whether a resource-loading element or attribute can be created;
- what later response content may be consumed;
- whether the browser actually issues a request;
- CSP and browser-specific restrictions;
- whether sensitive data is present in the captured region.

HTML injection alone is not proof of successful dangling-markup exfiltration.

## Relationship to XSS

Dangling markup is especially relevant when the same injection point looks promising for XSS but script execution is blocked by filtering, CSP, browser behavior, or another control.

The failure of a candidate XSS payload does not imply that all browser-side injection consequences are eliminated.

## Defenses

Context-appropriate output encoding and strict input validation can prevent the attacker from altering the intended markup structure.

CSP can mitigate some variants by restricting resource-loading destinations or resource types, but it is not a universal defense.

Browser-specific parsing mitigations can also prevent particular payload structures from generating outbound requests, so exploitability must be confirmed in the target browser behavior.
