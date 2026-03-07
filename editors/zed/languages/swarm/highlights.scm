; Swarm Language highlight queries for Zed

; ── Keywords ──
[
  "state" "behavior" "init" "func"
  "if" "else" "while" "loop" "match" "case" "default"
  "become" "break" "continue" "exit"
  "const" "register" "tag" "bool"
  "import" "export"
] @keyword

; ── Actions (tick-consuming) ──
["move" "pickup" "drop"] @function

; ── Transition arrow ──
"->" @operator

; ── Walrus operator ──
":=" @operator

; ── Negation ──
"!" @operator

; ── Comparison and binary operators ──
(comparison_operator) @operator
(binary_operator) @operator
"=" @operator

; ── Built-in constants ──
(builtin) @constant

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
(const_declaration name: (identifier) @constant)
(export_const name: (identifier) @constant)
(register_declaration name: (identifier) @variable)
(bool_declaration name: (identifier) @variable)
(tag_declaration name: (identifier) @label)

; ── State/behavior/function names ──
(state_definition name: (identifier) @type)
(state_instantiation name: (identifier) @type)
(state_instantiation behavior: (identifier) @type)
(behavior_definition name: (identifier) @type)
(function_definition name: (identifier) @function)
(export_function name: (identifier) @function)

; ── Function parameters and return ──
(parameter_list (identifier) @variable.parameter)
(export_function return: (identifier) @type)
(function_definition return: (identifier) @type)

; ── Exit declarations ──
(exit_declaration name: (identifier) @label)

; ── Wiring ──
(wiring exit: (identifier) @label)
(wiring target: (identifier) @type)

; ── Transitions ──
(transition target: (identifier) @type)

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
(function_call name: (identifier) @function)
(call_expression
  name: (identifier) @function
  (#not-match? @function "^(sense|probe|smell|sniff|carrying|id|rand|rand_range|mark|set_tag)$"))

; ── Assignment targets ──
(assignment target: (identifier) @variable)

; ── Punctuation ──
["{" "}"] @punctuation.bracket
["(" ")"] @punctuation.bracket
"," @punctuation.delimiter
