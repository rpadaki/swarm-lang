" Vim syntax file for Swarm Language (.sw)
" Generated from tree-sitter-swarm grammar.js and queries/highlights.scm

if exists('b:current_syntax')
  finish
endif

" Keywords
syn keyword swarmKeyword state behavior init func
syn keyword swarmKeyword if else while loop match case default
syn keyword swarmKeyword become break continue exit
syn keyword swarmKeyword const register tag bool
syn keyword swarmKeyword import export
syn keyword swarmKeyword package using action volatile stable extern local

" Actions (tick-consuming)
syn keyword swarmAction move pickup drop

" Non-action built-in calls
syn keyword swarmBuiltinFunc sense probe smell sniff carrying id rand rand_range mark set_tag

" Asm keyword
syn keyword swarmKeyword asm

" Built-in constants (directions)
syn keyword swarmConstBuiltin N E S W NORTH EAST SOUTH WEST HERE RANDOM

" Built-in constants (cell/sense types)
syn keyword swarmConstBuiltin EMPTY WALL FOOD NEST ANT
syn keyword swarmConstBuiltin CELL_EMPTY CELL_WALL CELL_FOOD CELL_NEST

" Built-in constants (pheromone channels)
syn keyword swarmConstBuiltin CH_RED CH_BLUE CH_GREEN CH_YELLOW

" Operators
syn match swarmOperator /\(==\|!=\|>=\|<=\|>\|<\)/
syn match swarmOperator /\(:=\)/
syn match swarmOperator /\(+=\|-=\|\*=\|\/=\|%=\|&=\||=\|\^=\|<<=\|>>=\)/
syn match swarmOperator /\(||\|&&\)/
syn match swarmOperator /\(->\)/
syn match swarmOperator /[+\-\*\/%&|^!]/
syn match swarmOperator /\(<<\|>>\)/

" Numbers
syn match swarmNumber /-\?\d\+/

" Strings
syn region swarmString start=/"/ end=/"/

" Comments
syn match swarmComment /\/\/.*$/
syn region swarmComment start=/\/\*/ end=/\*\//

" State/behavior names (identifier after state/behavior keyword)
syn match swarmType /\<state\s\+\zs\w\+/
syn match swarmType /\<behavior\s\+\zs\w\+/
syn match swarmType /\<become\s\+\zs\w\+/

" Const names
syn match swarmConst /\<const\s\+\zs\w\+/

" Function names
syn match swarmFunction /\<func\s\+\zs\w\+/

" Qualified names (module.member)
syn match swarmModule /\<\w\+\ze\.\w\+/
syn match swarmProperty /\.\zs\w\+/

" Highlight links
hi def link swarmKeyword      Keyword
hi def link swarmAction       Special
hi def link swarmBuiltinFunc  Function
hi def link swarmConstBuiltin Constant
hi def link swarmOperator     Operator
hi def link swarmNumber       Number
hi def link swarmString       String
hi def link swarmComment      Comment
hi def link swarmType         Type
hi def link swarmConst        Constant
hi def link swarmFunction     Function
hi def link swarmModule       Include
hi def link swarmProperty     Identifier

let b:current_syntax = 'swarm'
