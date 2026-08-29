"""LLM access layer: thin OpenAI wrapper, cost math, structured outputs.

Sits beside storage/ as an external-I/O adapter. Services call into this
package; nothing above it imports the OpenAI SDK directly.
"""
