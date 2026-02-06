System of tools build with Claude LLM generation. Public Domain.

Guide for Using Converter and what we want it to accomplish.
https://youtu.be/peQf-9lWNYA

(Sorry about how long it is.)

-----------

# Change Log

2026-02-06
- Multi-material component inport now functional.
- Transparency to Opacity conversion functional, not sure exactly the "factor" conversion.
- Collider and Rigidbodies are detected in Unity prefabs, but not properly translated into O3DE components.
  - There should be logic around Shape Collider == Static Rigidbody + Shape Collider + Equivalent Shape Component
  - There should be logic where Rigidbody == Dynamic Rigidbody
- Mesh/Model offsets are a mess.
