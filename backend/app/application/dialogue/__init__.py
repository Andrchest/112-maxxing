"""The dialogue chain (HLD `50-voice-pipeline.md` §3, §5, §7; D10; SPEC §2, §20-§24, §43).

Interpreter, fact catalog, caller-response generator, response validator and the deterministic
fallback templates. The Fact Access Gate itself is **not** here: it is pure domain code
(`app.domain.facts.gate`, §10.12), and this package calls it.

Two rules this package exists to keep structural rather than conventional (SPEC §2, §21):

* nothing here receives scenario truth. The catalog the interpreter sees carries no value, no
  knowledge state and no disclosure policy (D10), and the caller-response prompt builder accepts
  only an `AllowedFactsPackage`;
* nothing here decides, scores or writes anything. "The LLM IS NOT the simulation" (SPEC §2): no
  module of this package imports an operator or DDS command, a card repository or a scoring
  evaluator.

E13-A ships `catalog.py` only; `interpreter.py`, `generator.py`, `validator.py` and
`fallback_templates_ru.py` are E13-B's.
"""
