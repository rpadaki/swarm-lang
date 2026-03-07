/// <reference types="tree-sitter-cli/dsl" />
// Tree-sitter grammar for Swarm Language (.sw)

function commaSep1(rule) {
  return seq(rule, repeat(seq(',', rule)));
}

module.exports = grammar({
  name: 'swarm',

  extras: $ => [/\s/, $.line_comment, $.block_comment],

  word: $ => $.identifier,

  rules: {
    source_file: $ => repeat($._top_level),

    _top_level: $ => choice(
      $.package_declaration,
      $.import_statement,
      $.using_declaration,
      $.export_function,
      $.export_const,
      $.const_declaration,
      $.register_declaration,
      $.extern_register_declaration,
      $.bool_declaration,
      $.tag_declaration,
      $.init_block,
      $.state_definition,
      $.state_instantiation,
      $.behavior_definition,
      $.function_definition,
    ),

    // ── Packages / Imports / Exports ──

    package_declaration: $ => seq('package', field('name', $.identifier)),

    using_declaration: $ => seq('using', field('name', $.identifier)),

    import_statement: $ => seq('import', field('path', $.string)),

    export_const: $ => seq('export', 'const', field('name', $.identifier), '=', field('value', $._literal)),

    export_function: $ => seq(
      'export', optional('action'), 'func', field('name', $.identifier),
      '(', optional(field('params', $.parameter_list)), ')',
      optional(field('return_annotation', $.return_annotation)),
      $.block,
    ),

    parameter_list: $ => commaSep1($.identifier),

    // ── Top-level declarations ──

    const_declaration: $ => seq('const', field('name', $.identifier), '=', field('value', $._literal)),

    register_declaration: $ => choice(
      seq('register', commaSep1(field('name', $.identifier))),
      seq('register', '(', repeat($.register_entry), ')'),
    ),

    register_entry: $ => seq(
      field('name', $.identifier),
      optional(seq('(', field('binding', choice($.qualified_name, $.identifier)), ')')),
      optional(seq('=', field('initializer', $._expression))),
      optional(','),
    ),

    extern_register_declaration: $ => seq('extern', 'register', commaSep1(field('name', $.identifier))),

    bool_declaration: $ => seq('bool', commaSep1(field('name', $.identifier))),

    tag_declaration: $ => seq('tag', optional(field('index', $.number)), field('name', $.identifier)),

    init_block: $ => seq('init', $.block),

    state_definition: $ => seq('state', field('name', $.identifier), $.block),

    state_instantiation: $ => seq(
      'state', field('name', $.identifier), '=', field('behavior', $.identifier),
      $.wiring_block,
    ),

    behavior_definition: $ => seq('behavior', field('name', $.identifier), $.behavior_block),

    function_definition: $ => seq(
      'func', field('name', $.identifier),
      '(', optional(field('params', $.parameter_list)), ')',
      optional(field('return_annotation', $.return_annotation)),
      $.block,
    ),

    return_annotation: $ => seq(
      '->',
      optional('volatile'),
      field('name', $.identifier),
      optional(seq('stable', '(', field('predicate', $.condition), ')')),
    ),

    // ── Blocks ──

    block: $ => seq('{', repeat($._statement), '}'),

    behavior_block: $ => seq('{', repeat(choice($.exit_declaration, $._statement)), '}'),

    wiring_block: $ => seq('{', repeat($.wiring), '}'),

    exit_declaration: $ => seq('exit', field('name', $.identifier)),

    wiring: $ => seq(field('exit', $.identifier), '->', field('target', $.identifier)),

    // ── Statements ──

    _statement: $ => choice(
      $.if_statement,
      $.while_statement,
      $.loop_statement,
      $.match_statement,
      $.become_statement,
      $.break_statement,
      $.continue_statement,
      $.move_action,
      $.pickup_action,
      $.drop_action,
      $.mark_statement,
      $.set_tag_statement,
      $.local_declaration,
      $.assignment,
      $.compound_assignment,
      $.function_call,
      $.asm_block,
    ),

    become_statement: $ => seq('become', field('target', $.identifier)),
    break_statement: $ => prec.left('break'),
    continue_statement: $ => prec.left('continue'),

    // ── Actions (consume a tick) ──

    move_action: $ => seq('move', '(', field('direction', $._expression), ')'),
    pickup_action: $ => seq('pickup', '(', ')'),
    drop_action: $ => seq('drop', '(', ')'),

    // ── Non-action statements ──

    mark_statement: $ => seq('mark', '(', field('channel', $._expression), ',', field('intensity', $._expression), ')'),
    set_tag_statement: $ => seq('set_tag', '(', field('tag', $._expression), ')'),

    local_declaration: $ => seq('local', field('name', $.identifier)),

    assignment: $ => seq(field('target', $.identifier), '=', field('value', $._expression)),

    compound_assignment: $ => seq(
      field('target', $.identifier),
      field('operator', $.compound_operator),
      field('value', $._expression),
    ),

    compound_operator: $ => choice('+=', '-=', '*=', '/=', '%=', '&=', '|=', '^=', '<<=', '>>='),

    function_call: $ => seq(
      field('name', choice($.identifier, $.qualified_name)),
      '(', optional($._argument_list), ')',
    ),

    // ── Asm ──

    asm_block: $ => seq('asm', '{', repeat($.asm_token), '}'),
    asm_token: $ => /[A-Za-z_][A-Za-z0-9_]*|-?\d+/,


    // ── Control flow ──

    if_statement: $ => seq(
      'if', field('condition', $.condition), $.block,
      optional(seq('else', choice($.if_statement, $.block))),
    ),

    while_statement: $ => seq('while', field('condition', $.condition), $.block),

    loop_statement: $ => seq('loop', $.block),

    match_statement: $ => seq('match', field('value', $._expression), $.match_block),

    match_block: $ => seq('{', repeat(choice($.match_case, $.match_default)), '}'),
    match_case: $ => seq('case', field('value', $._literal), $.block),
    match_default: $ => seq('default', $.block),

    // ── Conditions ──

    condition: $ => choice(
      $.logical_condition,
      $.walrus_condition,
      $.comparison_condition,
      $.negated_condition,
      $._expression,  // bare truthy (implicitly != 0)
    ),

    logical_condition: $ => prec.left(seq(
      field('left', $.condition),
      field('operator', $.logical_operator),
      field('right', $.condition),
    )),

    logical_operator: $ => choice('||', '&&'),

    walrus_condition: $ => seq(
      field('target', $.identifier),
      ':=',
      field('value', $._expression),
      optional(seq(field('operator', $.comparison_operator), field('right', $._expression))),
    ),

    comparison_condition: $ => prec(1, seq(
      field('left', $._expression),
      field('operator', $.comparison_operator),
      field('right', $._expression),
    )),

    negated_condition: $ => seq('!', field('value', $._expression)),

    comparison_operator: $ => choice('==', '!=', '>', '<', '>=', '<='),

    // ── Expressions ──

    _expression: $ => choice(
      $.binary_expression,
      $.paren_expression,
      $.call_expression,
      $.qualified_name,
      $.identifier,
      $.number,
      $.builtin,
    ),

    qualified_name: $ => seq(
      field('module', $.identifier),
      '.',
      field('member', $.identifier),
    ),

    paren_expression: $ => seq('(', $._expression, ')'),

    binary_expression: $ => prec.left(1, seq(
      field('left', $._expression),
      field('operator', $.binary_operator),
      field('right', $._expression),
    )),

    binary_operator: $ => choice('+', '-', '*', '/', '%', '&', '|', '^', '<<', '>>'),

    call_expression: $ => seq(
      field('name', choice($.identifier, $.qualified_name)),
      '(', optional($._argument_list), ')',
    ),

    _argument_list: $ => commaSep1($._expression),

    // ── Terminals ──

    _literal: $ => choice($.number, $.identifier, $.builtin),

    builtin: $ => choice(
      // Directions
      'N', 'E', 'S', 'W', 'NORTH', 'EAST', 'SOUTH', 'WEST', 'HERE', 'RANDOM',
      // Cell types
      'EMPTY', 'WALL', 'FOOD', 'NEST',
      // Pheromone channels
      'CH_RED', 'CH_BLUE', 'CH_GREEN', 'CH_YELLOW',
    ),

    identifier: $ => /[a-zA-Z_][a-zA-Z0-9_]*/,

    number: $ => /-?\d+/,

    string: $ => /"[^"]*"/,

    line_comment: $ => /\/\/[^\n]*/,

    block_comment: $ => /\/\*[\s\S]*?\*\//,
  },
});
