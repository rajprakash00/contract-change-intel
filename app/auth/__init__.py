"""Identity provider access (W5·C): Auth0 OIDC bearer verification.

This layer owns the only JWT/JWKS machinery, the same way `app/llm` owns the
only LLM SDK imports: it converts wire/protocol failures into its own error
types, which `app/errors.py` maps onto HTTP once, app-wide.
"""
