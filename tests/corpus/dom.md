# DOM attribute flow

An attacker-controlled fragment value is read by client-side code and passed to `setAttribute`.
The supplied observation shows attribute control only. It does not show an event-handler context,
script execution, or security impact. A useful analysis identifies the attribute name, browser
parsing context, later reads of the attribute, and the evidence needed to demonstrate behavior.
