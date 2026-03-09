"""Optimization passes for Swarm antssembly output."""

from dataclasses import dataclass

from .dce import dce


@dataclass
class OptConfig:
    """Toggle individual optimization passes. All enabled by default."""
    dead_code: bool = True
    jmp_chain: bool = True
    jmp_to_next: bool = True
    unreferenced_labels: bool = True
    noop_sets: bool = True
    set_op_fusion: bool = True
    const_fold: bool = True
    state_reorder: bool = True
    loop_rotate: bool = True
    cmp_reduce: bool = True
    strip: bool = False

    @classmethod
    def none(cls):
        """All optimizations disabled."""
        return cls(
            dead_code=False,
            jmp_chain=False,
            jmp_to_next=False,
            unreferenced_labels=False,
            noop_sets=False,
            set_op_fusion=False,
            const_fold=False,
            state_reorder=False,
            loop_rotate=False,
            cmp_reduce=False,
        )


OPT_ALL = OptConfig()
OPT_NONE = OptConfig.none()

__all__ = ["dce", "OptConfig", "OPT_ALL", "OPT_NONE"]
