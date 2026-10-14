"""Rules registry tooling.

The registry in ``rules/registry.toml`` is the single list of rules that govern
this repository. This package validates it, checks that every rule is really
enforced where it claims to be, and renders the human- and agent-facing views.

It must stay standard-library only so it can run in CI jobs that install no
dependencies.
"""
