"""Catalog of sensible default values and Mockito matchers per Java type.

Inspired by Squaretest's defaulttypes.json and testme-idea's defaultTypeValues map.
Values are rendered as Java source-code literals, so the consumer can drop them
directly into a test scaffold.
"""

from typing import Dict, Optional

# Primitives / core wrappers
PRIMITIVE_DEFAULTS: Dict[str, str] = {
    "int": "0",
    "Integer": "0",
    "long": "0L",
    "Long": "0L",
    "short": "(short)0",
    "Short": "(short)0",
    "byte": "(byte)0",
    "Byte": "(byte)0",
    "float": "0.0f",
    "Float": "0.0f",
    "double": "0.0",
    "Double": "0.0",
    "boolean": "false",
    "Boolean": "false",
    "char": "'a'",
    "Character": "'a'",
    "String": "\"test\"",
    "CharSequence": "\"test\"",
    "Object": "new Object()",
    "BigDecimal": "java.math.BigDecimal.ZERO",
    "BigInteger": "java.math.BigInteger.ZERO",
    "UUID": "java.util.UUID.randomUUID()",
    "LocalDate": "java.time.LocalDate.now()",
    "LocalDateTime": "java.time.LocalDateTime.now()",
    "LocalTime": "java.time.LocalTime.now()",
    "Instant": "java.time.Instant.now()",
    "Date": "new java.util.Date()",
    "Duration": "java.time.Duration.ZERO",
    "Locale": "java.util.Locale.ENGLISH",
    "Currency": "java.util.Currency.getInstance(\"USD\")",
    "File": "new java.io.File(\"./tmp\")",
    "Path": "java.nio.file.Paths.get(\"./tmp\")",
    "URI": "java.net.URI.create(\"http://localhost\")",
    "URL": "new java.net.URL(\"http://localhost\")",
    "Class": "Object.class",
    "void": "",
    "Void": "null",
}

# Generic containers: parameterized defaults use Java 9+ immutable factories.
GENERIC_DEFAULTS: Dict[str, str] = {
    "List": "java.util.List.of()",
    "Set": "java.util.Set.of()",
    "Map": "java.util.Map.of()",
    "Collection": "java.util.List.of()",
    "Iterable": "java.util.List.of()",
    "Iterator": "java.util.Collections.emptyIterator()",
    "Optional": "java.util.Optional.empty()",
    "Stream": "java.util.stream.Stream.empty()",
    "IntStream": "java.util.stream.IntStream.empty()",
    "LongStream": "java.util.stream.LongStream.empty()",
    "DoubleStream": "java.util.stream.DoubleStream.empty()",
    "Queue": "new java.util.LinkedList<>()",
    "Deque": "new java.util.ArrayDeque<>()",
    "CompletableFuture": "java.util.concurrent.CompletableFuture.completedFuture(null)",
    "Future": "java.util.concurrent.CompletableFuture.completedFuture(null)",
    "Mono": "reactor.core.publisher.Mono.empty()",
    "Flux": "reactor.core.publisher.Flux.empty()",
    "ResponseEntity": "org.springframework.http.ResponseEntity.ok().build()",
    "Page": "org.springframework.data.domain.Page.empty()",
}

# Mockito matchers per primitive type
PRIMITIVE_MATCHERS: Dict[str, str] = {
    "int": "anyInt()",
    "Integer": "anyInt()",
    "long": "anyLong()",
    "Long": "anyLong()",
    "short": "anyShort()",
    "Short": "anyShort()",
    "byte": "anyByte()",
    "Byte": "anyByte()",
    "float": "anyFloat()",
    "Float": "anyFloat()",
    "double": "anyDouble()",
    "Double": "anyDouble()",
    "boolean": "anyBoolean()",
    "Boolean": "anyBoolean()",
    "char": "anyChar()",
    "Character": "anyChar()",
    "String": "anyString()",
    "List": "anyList()",
    "Set": "anySet()",
    "Map": "anyMap()",
    "Collection": "anyCollection()",
    "Iterable": "anyIterable()",
}


def _base_name(type_text: str) -> str:
    """Strip generics and nested package prefix: `java.util.List<String>` -> `List`."""
    t = (type_text or "").strip()
    t = t.split("<", 1)[0].strip()
    return t.rsplit(".", 1)[-1]


def default_for(type_text: str) -> str:
    """Render a Java literal suitable as a default value for the given type.

    Falls back to `mock(<Type>.class)` for unknown reference types so the caller can
    emit a safe placeholder without NullPointerExceptions in arithmetic paths.
    """
    if not type_text:
        return "null"
    bare = _base_name(type_text)
    if bare in PRIMITIVE_DEFAULTS:
        return PRIMITIVE_DEFAULTS[bare]
    if bare in GENERIC_DEFAULTS:
        return GENERIC_DEFAULTS[bare]
    # Arrays
    if type_text.endswith("[]"):
        inner = type_text[:-2].strip()
        inner_bare = _base_name(inner)
        return f"new {inner_bare}[0]"
    # Unknown reference type -> safe mocked instance
    return f"org.mockito.Mockito.mock({bare}.class)"


def matcher_for(type_text: str) -> str:
    """Return a Mockito matcher expression for the given Java type."""
    if not type_text:
        return "any()"
    bare = _base_name(type_text)
    if bare in PRIMITIVE_MATCHERS:
        return PRIMITIVE_MATCHERS[bare]
    # any(Type.class) is more specific and avoids compile issues with overloaded methods.
    return f"any({bare}.class)"


def merge_overrides(overrides: Optional[Dict[str, str]]) -> None:
    """Allow the project config to extend/override the default map at runtime."""
    if not overrides:
        return
    for k, v in overrides.items():
        PRIMITIVE_DEFAULTS[k] = v
