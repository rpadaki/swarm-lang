; Swarm Language highlight queries for Zed

; ── Keywords ──
[
  "state" "behavior" "init" "func"
  "if" "else" "while" "loop" "match" "case" "default"
  "become" "break" "continue" "exit"
  "const" "register" "tag" "bool"
  "import" "export"
  "package" "using" "extern" "action" "local"
] @keyword

; ── Annotations ──
["volatile" "stable"] @attribute

; ── Actions (tick-consuming) ──
["move" "pickup" "drop"] @function

; ── Walrus operator ──
":=" @operator

; ── Transition arrow (return annotations) ──
"->" @operator

; ── Negation ──
"!" @operator

; ── Comparison, binary, and compound operators ──
(comparison_operator) @operator
(binary_operator) @operator
(logical_operator) @operator
(compound_operator) @operator
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

; ── Package / Using ──
(package_declaration name: (identifier) @type)
(using_declaration name: (identifier) @type)

; ── Declarations ──
(const_declaration name: (identifier) @constant)
(export_const name: (identifier) @constant)
(register_declaration name: (identifier) @variable)
(extern_register_declaration name: (identifier) @variable)
(bool_declaration name: (identifier) @variable)
(tag_declaration name: (identifier) @label)
(local_declaration name: (identifier) @variable)

; ── Qualified names ──
(qualified_name module: (identifier) @type)
(qualified_name member: (identifier) @property)

; ── Register entry (more specific, overrides general qualified_name) ──
(register_entry name: (identifier) @variable)
(register_entry binding: (qualified_name module: (identifier) @type))
(register_entry binding: (qualified_name member: (identifier) @variable))
(register_entry binding: (identifier) @variable)

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
(function_call name: (identifier) @function)
(call_expression
  name: (identifier) @function
  (#not-match? @function "^(sense|probe|smell|sniff|carrying|id|rand|rand_range|mark|set_tag)$"))

; ── Assignment targets ──
(assignment target: (identifier) @variable)
(compound_assignment target: (identifier) @variable)

; ── Punctuation ──
["{" "}"] @punctuation.bracket
["(" ")"] @punctuation.bracket
"," @punctuation.delimiter

