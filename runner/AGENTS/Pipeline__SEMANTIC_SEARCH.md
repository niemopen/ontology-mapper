# Semantic Search Protocol

> **Repo**: OntologyMapper | **Version**: 3.0 | **Updated**: 2026-04-09
> **Used by**: Stage 3 (Align)

---

## Purpose

This document describes semantic search evaluation at Stage 3. `om-batch-search` writes separate files: one per source type to `search-results/types/` and one per source property to `search-results/properties/`. Each file contains ranked candidates (filtered to top 25, 75% score floor). `om-orchestrate-eval` evaluates each file via a bounded concurrent `claude -p` call — the LLM reasons about candidates, picks the best match, and writes its evaluation back. `om-collect-alignments` then reassembles the results.

---

## Element-First Search

Before choosing a target type, check whether the target ontology already defines a specific element or property for the source concept. If it does, the type follows from that element — not from name similarity alone. An element that semantically matches the source concept tells you which type to use.

---

## Property-Path Concepts

Some source "classes" are really simple data values (a country name, a language name, a telephone number). Check whether the concept is better represented as a property on a parent type rather than as a standalone type. If so, map it to the existing property that carries this data rather than creating a new type-level alignment.

---

## Type Patterns

Each target ontology defines its own set of type patterns in the reference catalog's `typePatterns` section. These describe structural patterns in the target ontology — what kinds of types exist and how they relate to matching decisions. The evaluator reads these as context, not as a selection list.

---

## Action Selection

The valid actions for each target ontology are defined in the reference catalog's `actions` section. The evaluator selects one action per source concept from this list. The action descriptions explain when each action applies. There are no hardcoded action names — the list is determined by the target ontology.
