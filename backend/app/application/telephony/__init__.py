"""The SIP gateway's side of the ДДС phone line (I3 E6e, HLD `80-telephony.md` §80.2.3, §80.3.5,
§80.3.7, `openapi.yaml` tag `telephony`).

Four use cases, each reached only with the gateway's service credential (`SIM_SIP_GATEWAY_SECRET`)
and never with a trainee's bearer token:

* `DialFromSip` — a registered softphone dialled a number: the session selection and the dial plan,
  then the same `startDdsCall` use case with the `SIP` endpoint (`dial_from_sip.py`);
* `ReportSipLeg` — the gateway's softphone leg went `UP` / `FAILED` / `DOWN`
  (`report_sip_leg.py`);
* `GetTelephonyCall` and `GetSipCredential` — the two reads (`reads.py`).

Like every ДДС use case none of them is handed a world-truth, caller-belief or operator-card
repository (SPEC §42 test 3, INV 3).
"""
