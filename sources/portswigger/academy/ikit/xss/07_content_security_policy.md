---
agent: ikit
topic: xss
source_type: academy
source_title: "Content security policy"
source_reference: "https://portswigger.net/web-security/cross-site-scripting/content-security-policy"
corpus: ikit_xss_core_v1
---

# Content Security Policy and XSS

Content Security Policy (CSP) is a browser security mechanism that can mitigate XSS and other browser-side attacks by restricting which resources a page may load and which script execution paths are permitted.

CSP is delivered through the `Content-Security-Policy` response header and consists of directives.

## CSP as an XSS mitigation

Script restrictions may constrain script sources, inline execution, or other resource-loading behavior. Nonces and hashes can be used to authorize specific scripts.

A CSP can prevent or hinder exploitation of an underlying injection behavior. This distinction is important:

**an injection or unsafe data flow can exist even when the current CSP prevents a candidate payload from executing.**

Therefore, evidence should separately track:

- controllability and injection behavior;
- browser parsing context;
- CSP restrictions;
- whether execution is demonstrated under the effective policy;
- the resulting security impact.

## Trust decisions in CSP

Allowing scripts from an external origin is only as safe as the attacker's ability to influence content served from that origin.

A source allow-list should therefore be analyzed as a trust boundary rather than as proof that all content from the source is safe.

Nonce- and hash-based policies can provide stronger authorization when implemented correctly.

## CSP and external requests

Policies often distinguish scripts, images, frames, and other resource types. A policy that blocks script execution may still permit other outbound requests.

This matters for non-script injection classes such as dangling markup, where data disclosure may occur through a resource-loading attribute rather than JavaScript execution.

## Policy injection and bypass reasoning

If attacker-controlled data is incorporated into the CSP itself, determine:

1. where the value is inserted;
2. which directive is affected;
3. whether the attacker can introduce or override effective directives;
4. how the browser resolves duplicate or more-specific directives;
5. whether the altered policy creates an executable or data-exfiltration path.

Do not infer a CSP bypass merely because input is reflected in the header. Browser-effective policy behavior must be demonstrated.

## CSP as defense in depth

CSP should be treated as defense in depth, not as a substitute for correct output encoding, input validation, safe DOM APIs, or other context-specific controls.
