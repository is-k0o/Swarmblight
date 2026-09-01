---
agent: ikit
topic: xss
source_type: academy
source_title: "Reflected XSS"
source_reference: "https://portswigger.net/web-security/cross-site-scripting/reflected"
corpus: ikit_xss_core_v1
---

# Reflected XSS

Reflected cross-site scripting arises when an application receives data in an HTTP request and includes that data within the immediate response in an unsafe way.

## What is reflected cross-site scripting?

A typical example is a search feature that receives a term in a URL parameter and echoes it into the response. If attacker-controlled data reaches an executable browser context without adequate processing, JavaScript supplied by the attacker may execute in the victim user's browser and in the context of that user's session.

The key distinction is not merely that data is reflected. The reflected data must appear in a context where attacker-controlled input can alter browser parsing or execution semantics.

## Impact of reflected XSS attacks

If attacker-controlled JavaScript executes in another user's browser, the attacker may be able to perform actions available to that user, access information visible to the user, modify data the user can modify, or initiate interactions that appear to originate from the victim.

Reflected XSS normally requires an external delivery mechanism that induces the victim to make an attacker-controlled request. This generally makes delivery less self-contained than stored XSS.

## Reflected XSS in different contexts

The location of the reflected data in the response determines exploitability and the techniques that are relevant. Important contexts include text between HTML tags, HTML attribute values, JavaScript strings, URL-bearing attributes, and other parser contexts.

Validation, encoding, sanitization, and other transformations performed before reflection can change which characters or structures reach the browser and therefore change exploitability.

## How to find and test for reflected XSS vulnerabilities

A systematic manual methodology is:

- **Test each relevant entry point.** Query parameters, body parameters, URL path components, and sometimes HTTP headers can all carry attacker-controlled data.
- **Use a unique benign marker first.** Determine whether and where the input is reflected before attempting to reason about exploitation.
- **Determine the reflection context.** Identify which parser will consume the reflected data and whether it is in HTML text, an attribute, JavaScript, a URL, or another context.
- **Account for transformations.** Observe validation, encoding, normalization, or filtering before choosing a candidate test.
- **Test a context-appropriate candidate.** A candidate must demonstrate that attacker-controlled input can alter executable semantics; reflection alone is insufficient.
- **Test alternative techniques only when justified by the observed context and transformations.**
- **Confirm in a real browser.** A response that looks promising in an HTTP client is not itself proof of browser execution.

## Reflected XSS versus related cases

**Reflected XSS vs stored XSS:** reflected XSS uses data from the current request; stored XSS persists attacker-controlled data and emits it in a later response.

**Reflected XSS vs self-XSS:** self-XSS cannot normally be delivered to another user through a crafted request alone and typically requires the victim to submit attacker-supplied input themselves, often via social engineering.
