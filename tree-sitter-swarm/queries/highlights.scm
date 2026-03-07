; Swarm Language highlight queries for tree-sitter

; ── Keywords ──
[
  "state" "behavior" "init" "func"
  "if" "else" "while" "loop" "match" "case" "default"
  "become" "break" "continue" "exit"
  "const" "register" "tag" "bool"
  "import" "export"
  "package" "using" "action" "volatile" "stable" "extern" "local"
] @keyword

; ── Actions (tick-consuming) ──
["move" "pickup" "drop"] @keyword.function

; ── Transition arrow ──
"->" @operator

; ── Walrus operator ──
":=" @operator

; ── Negation ──
"!" @operator

; ── Comparison, binary, and compound operators ──
(comparison_operator) @operator
(binary_operator) @operator
(logical_operator) @operator
(compound_operator) @operator
"=" @operator

; ── Built-in constants ──
(builtin) @constant.builtin

; ── Numbers ──
(number) @number

; ── Strings ──
(string) @string

; ── Comments ──
(line_comment) @comment
(block_comment) @comment

; ── Import path ──
(import_statement path: (string) @string)

; ── Declarations ──
(package_declaration name: (identifier) @module)
(using_declaration name: (identifier) @module)
(const_declaration name: (identifier) @constant)
(export_const name: (identifier) @constant)
(register_declaration name: (identifier) @variable)
(register_entry name: (identifier) @variable)
(register_entry binding: (qualified_name module: (identifier) @module))
(register_entry binding: (qualified_name member: (identifier) @variable))
(register_entry binding: (identifier) @variable)
(extern_register_declaration name: (identifier) @variable)
(bool_declaration name: (identifier) @variable)
(tag_declaration name: (identifier) @label)
(local_declaration name: (identifier) @variable)

; ── State/behavior/function names ──
(state_definition name: (identifier) @type)
(state_instantiation name: (identifier) @type)
(state_instantiation behavior: (identifier) @type)
(behavior_definition name: (identifier) @type)
(function_definition name: (identifier) @function)
(export_function name: (identifier) @function)

; ── Function parameters and return ──
(parameter_list (identifier) @variable.parameter)
(return_annotation name: (identifier) @type)

; ── Qualified names ──
(qualified_name module: (identifier) @module)
(qualified_name member: (identifier) @property)

; ── Exit declarations ──
(exit_declaration name: (identifier) @label)

; ── Wiring ──
(wiring exit: (identifier) @label)
(wiring target: (identifier) @type)

; ── Become targets ──
(become_statement target: (identifier) @type)

; ── Walrus condition target ──
(walrus_condition target: (identifier) @variable)

; ── Asm ──
(asm_block) @embedded
(asm_token) @keyword
"asm" @keyword

; ── Function calls — built-in sense functions ──
(call_expression
  name: (identifier) @function.builtin
  (#match? @function.builtin "^(sense|probe|smell|sniff|carrying|id|rand|rand_range|mark|set_tag)$"))

; ── Function calls — user-defined ──
(function_call name: (identifier) @function.call)
(call_expression
  name: (identifier) @function.call
  (#not-match? @function.call "^(sense|probe|smell|sniff|carrying|id|rand|rand_range|mark|set_tag)$"))

; ── Assignment targets ──
(assignment target: (identifier) @variable)
(compound_assignment target: (identifier) @variable)

; ── Punctuation ──
["{" "}"] @punctuation.bracket
["(" ")"] @punctuation.bracket
"," @punctuation.delimiter
"." @punctuation.delimiter
