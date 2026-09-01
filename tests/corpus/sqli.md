# Quote and server error

A server returns status 500 after a single quote is supplied. The error is an anomaly, not proof
that attacker input changed SQL query structure. A discriminating comparison needs stable controls
and evidence that separates query behavior from generic input-validation or application failures.
