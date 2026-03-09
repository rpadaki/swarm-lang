"""AST node definitions for the Swarm language."""

from dataclasses import dataclass, field


@dataclass
class Const:
    name: str
    value: str


@dataclass
class RegDecl:
    names: list[str]
    bindings: dict[str, str] = field(default_factory=dict)
    initializers: dict[str, object] = field(default_factory=dict)


@dataclass
class TagDecl:
    name: str
    index: int | None = None


@dataclass
class InitBlock:
    body: list


@dataclass
class StateBlock:
    name: str
    body: list


@dataclass
class FuncDef:
    name: str
    body: list


@dataclass
class FuncCall:
    name: str
    args: list[str] = field(default_factory=list)


@dataclass
class Become:
    target: str


@dataclass
class Assignment:
    target: str
    expr: object
    line: int = 0


@dataclass
class BinExpr:
    left: str
    op: str
    right: str


@dataclass
class CallExpr:
    func: str
    args: list[str] = field(default_factory=list)
    line: int = 0


@dataclass
class ActionStmt:
    func: str
    args: list[str] = field(default_factory=list)
    line: int = 0


@dataclass
class IfStmt:
    cond: tuple
    body: list
    else_body: list | None = None
    line: int = 0


@dataclass
class WhileStmt:
    cond: tuple
    body: list
    line: int = 0


@dataclass
class LoopStmt:
    body: list


@dataclass
class MatchStmt:
    var: object
    cases: list
    default_body: list | None = None


@dataclass
class MatchCase:
    value: str
    body: list


@dataclass
class BoolDecl:
    names: list[str]


@dataclass
class BehaviorDef:
    name: str
    params: list[str]
    exits: list[str]
    body: list


@dataclass
class StateFromBehavior:
    name: str
    behavior: str
    args: list[str]
    wiring: dict[str, str]


@dataclass
class Import:
    path: str
    line: int = 0


@dataclass
class PackageDecl:
    name: str


@dataclass
class UsingDecl:
    name: str


@dataclass
class ExportConst:
    name: str
    value: str


@dataclass
class ExportFunc:
    name: str
    params: list[str]
    ret: str | None
    body: list
    exported: bool = True
    is_action: bool = False
    is_volatile: bool = False
    stable_predicate: str | None = None


@dataclass
class AsmBlock:
    tokens: list[str]


@dataclass
class Break:
    pass


@dataclass
class Continue:
    pass


@dataclass
class ExternRegDecl:
    names: list[str]


