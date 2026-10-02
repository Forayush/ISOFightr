"""M1 debug sandbox: placeholder fighters moved freely, with no physics.

Roadmap M1: "Placeholder fighter sprite moved by a debug free-cam (no physics yet), including
z up/down to test sorting". This is a stand-in for the sim's ``Match`` and ``Fighter``, which
arrive in M2; it exists only so the stage renderer, depth sorting, shadows and camera can be
exercised. It is not gameplay logic and is deleted when real fighters replace it.

Pure Python (no ``arcade``), stepped once per fixed tick like the sim will be.
"""

from __future__ import annotations

from dataclasses import dataclass

from isofightr.config import SANDBOX_MOVE_SPEED, SANDBOX_PLAYER_COUNT, SANDBOX_RISE_SPEED
from isofightr.sim.input_frame import Dir8, facing_from_move, stick_to_world
from isofightr.sim.math3d import Vec3
from isofightr.sim.stage import Stage


@dataclass(slots=True)
class SandboxEntity:
    """A free-moving placeholder: just a position and a facing."""

    entity_id: int
    player_index: int
    pos: Vec3
    facing: Dir8


@dataclass(slots=True)
class Sandbox:
    """The placeholders on a stage and which one the keyboard currently moves."""

    stage: Stage
    entities: list[SandboxEntity]
    controlled: int = 0

    @classmethod
    def create(cls, stage: Stage, player_count: int = SANDBOX_PLAYER_COUNT) -> Sandbox:
        """Spawn ``player_count`` placeholders at the stage's spawn points."""
        sandbox = cls(stage=stage, entities=[])
        for index in range(player_count):
            sandbox.entities.append(SandboxEntity(index, index, Vec3(), Dir8.SE))
        sandbox.reset()
        return sandbox

    @property
    def controlled_entity(self) -> SandboxEntity:
        """The placeholder the keyboard moves."""
        return self.entities[self.controlled]

    def reset(self) -> None:
        """Put every placeholder back on its spawn point, facing the middle of the stage."""
        centre = self.stage.respawn_point()
        for entity in self.entities:
            entity.pos = self.stage.spawn_point(entity.player_index)
            toward_centre = facing_from_move((centre - entity.pos).xy)
            entity.facing = Dir8.SE if toward_centre is None else toward_centre

    def cycle_control(self) -> None:
        """Hand keyboard control to the next placeholder."""
        self.controlled = (self.controlled + 1) % len(self.entities)

    def step(self, stick_u: float, stick_v: float, rise: float) -> None:
        """Advance one tick: move the controlled placeholder at a constant speed.

        Args:
            stick_u: screen-relative horizontal input, right positive, in ``[-1, 1]``.
            stick_v: screen-relative vertical input, up positive, in ``[-1, 1]``.
            rise: vertical input, up positive, in ``[-1, 1]``.
        """
        entity = self.controlled_entity
        move = stick_to_world(stick_u, stick_v).normalized()
        new_facing = facing_from_move(move, entity.facing)
        if new_facing is not None:
            entity.facing = new_facing
        step = move * SANDBOX_MOVE_SPEED
        entity.pos = entity.pos + Vec3(step.x, step.y, rise * SANDBOX_RISE_SPEED)
