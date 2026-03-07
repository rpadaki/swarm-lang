# Tree-sitter for the Swarm Compiler: Evaluation

## Recommendation

Keep the hand-rolled parser for the compiler. Use tree-sitter exclusively for editor tooling (syntax highlighting, Zed/VS Code extensions). The two parsers serve fundamentally different purposes, and the cost of bridging tree-sitter's CST to the compiler's AST exceeds the cost of maintaining the hand-rolled parser — which is 450 lines of straightforward recursive descent and changes infrequently.

The grammars have already drifted in meaningful ways (register bindings/initializers, behavior parameters, operator precedence tiers), and that drift is fine. The tree-sitter grammar needs to be forgiving and produce a usable tree from broken input; the compiler parser needs to be precise and produce good error messages from valid input. Trying to make one parser serve both masters would compromise both.

For the LSP specifically, the incremental parsing benefit is real but modest. The largest Swarm programs are a few hundred lines. Re-parsing from scratch on each keystroke is already effectively instantaneous. If LSP performance ever becomes a bottleneck, the fix is to cache the last-good AST on parse failure, not to adopt tree-sitter as the compiler frontend.

## Analysis

### 1. Maintenance Burden

The two parsers have already diverged. The hand-rolled parser supports register blocks with bindings (`register (x(ant.dx))`) and initializers (`= expr`), behavior parameters, state instantiation with arguments, and C-style operator precedence across 7 tiers. The tree-sitter grammar has none of these — it uses flat `commaSep1(identifier)` for registers and a single `prec.left(1)` for all binary expressions. This drift happened within the first two commits and is evidence that the two grammars naturally evolve at different rates for different reasons. Keeping them loosely coupled (both parse `.sw` files, but neither depends on the other) is the right architecture.

### 2. Error Messages

The hand-rolled parser produces messages like `line 12: expected IDENT(state), got OP(=)` with exact line numbers from the token stream. These are adequate and easy to improve (e.g., adding "did you mean..." suggestions). Tree-sitter's error recovery is designed for resilience, not diagnostics — it inserts ERROR and MISSING nodes into the tree, which then require a second pass to produce human-readable messages. For a compiler whose job is to reject bad programs, the hand-rolled approach is strictly better.

### 3. Performance

Irrelevant. The tokenizer and parser together handle the largest Swarm programs in under 1ms. Tree-sitter would be faster in absolute terms but the difference is unmeasurable.

### 4. Dependencies

The compiler currently requires only Python stdlib plus `dataclasses`. The LSP adds `pygls` and `lsprotocol`. Adding `tree-sitter` (which requires a C compiler at install time and ships native `.so` files) would be a significant dependency escalation for the core compiler path. This matters because the compiler is invoked by LLM agents in sandboxed environments where native dependencies may not be available.

### 5. CST-to-AST Transformation

The compiler uses 20+ dataclass AST nodes with semantic fields (`bindings`, `initializers`, `is_action`, `is_volatile`, `stable_predicate`, `wiring`). Tree-sitter produces a generic CST with named children. A CST-to-AST pass would be roughly the same size as the current parser (400-500 lines) but harder to debug because errors in the transformation manifest as wrong codegen rather than parse failures. This is net-negative complexity.

### 6. Incremental Parsing

The LSP re-parses on every `textDocument/didChange`. For a language where programs are 50-300 lines, full re-parse is effectively free. Incremental parsing would matter at 10k+ lines. Swarm will not reach that scale.

### 7. Language Size

Swarm has ~20 keywords, ~15 statement types, and ~8 expression forms. The entire parser + tokenizer + AST is 680 lines. Tree-sitter is designed for languages 10-100x this complexity. The overhead of maintaining a `grammar.js`, generating C code, compiling WASM artifacts, and writing a CST-to-AST bridge would exceed the total size of the current implementation.
