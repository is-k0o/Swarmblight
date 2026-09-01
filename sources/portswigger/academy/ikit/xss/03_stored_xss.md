---
agent: ikit
topic: xss
source_type: academy
source_title: "Stored XSS"
source_reference: "https://portswigger.net/web-security/cross-site-scripting/stored"
corpus: ikit_xss_core_v1
---

# Stored XSS

Stored cross-site scripting, also known as persistent or second-order XSS, arises when an application receives data from an untrusted source, stores it, and later includes that data within HTTP responses in an unsafe way.

## What is stored cross-site scripting?

Attacker-controlled input may enter through comments, profiles, messages, orders, logs, imported content, email, third-party feeds, or other application functionality. A later request by the same or another user can cause the stored value to be emitted into a browser context.

The important property is persistence across requests. Seeing the same value in an immediate response does not by itself prove that the value was stored.

## Impact of stored XSS attacks

If stored attacker-controlled data later executes JavaScript in another user's browser, the impact can be similar to other XSS classes.

Stored XSS can be easier to deliver than reflected XSS because the attack can be self-contained within the vulnerable application. The attacker may only need to place the malicious value into storage and wait for another user to encounter it.

## Stored XSS in different contexts

As with reflected XSS, exploitability depends on the output context in which stored data later appears and on any processing performed both:

- when the data is accepted and stored; and
- when the stored data is inserted into a later response.

The same stored value may be safe in one output context and unsafe in another.

## How to find and test for stored XSS vulnerabilities

Stored XSS testing requires mapping **entry points** to **exit points**.

Potential entry points include:

- URL query parameters and request bodies;
- URL paths;
- request headers;
- application-specific routes such as email, imported feeds, logs, comments, profile fields, or third-party content.

Potential exit points are any later responses in which stored data may appear to any user or role.

A practical methodology is:

1. submit a unique benign marker to an entry point;
2. navigate through relevant application functionality;
3. determine where and when the marker reappears;
4. verify that the value persists across distinct requests rather than being immediately reflected;
5. identify the exact browser context at each exit point;
6. account for transformations applied during storage and output;
7. test a context-appropriate candidate only after the data flow is understood;
8. require browser behavior evidence before classifying the issue as XSS.

The main analytical problem is therefore not simply finding reflection, but linking attacker-controlled **entry → storage → exit → browser context**.
