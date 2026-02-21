from __future__ import annotations

import json
from typing import Optional

from arkbreeder.storage.models import Creature


def creature_from_row(row) -> Creature:
    return Creature(
        id=row["id"],
        external_id=row["external_id"],
        name=row["name"],
        species=row["species"],
        sex=row["sex"],
        level=row["level"],
        stats=json.loads(row["stats_json"]) if row["stats_json"] else {},
        mutations_maternal=row["mutations_maternal"],
        mutations_paternal=row["mutations_paternal"],
        mother_id=row["mother_id"],
        father_id=row["father_id"],
    )


def add_creature(conn, creature: Creature) -> Creature:
    cursor = conn.execute(
        '''
        INSERT INTO creatures (
            external_id, name, species, sex, level, stats_json,
            mutations_maternal, mutations_paternal, mother_id, father_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            creature.external_id,
            creature.name,
            creature.species,
            creature.sex,
            creature.level,
            json.dumps(creature.stats),
            creature.mutations_maternal,
            creature.mutations_paternal,
            creature.mother_id,
            creature.father_id,
        ),
    )
    return creature.with_id(cursor.lastrowid)


def update_creature(conn, creature: Creature) -> Creature:
    conn.execute(
        '''
        UPDATE creatures SET
            external_id = ?,
            name = ?,
            species = ?,
            sex = ?,
            level = ?,
            stats_json = ?,
            mutations_maternal = ?,
            mutations_paternal = ?,
            mother_id = ?,
            father_id = ?
        WHERE id = ?
        ''',
        (
            creature.external_id,
            creature.name,
            creature.species,
            creature.sex,
            creature.level,
            json.dumps(creature.stats),
            creature.mutations_maternal,
            creature.mutations_paternal,
            creature.mother_id,
            creature.father_id,
            creature.id,
        ),
    )
    return creature


def upsert_creature(conn, creature: Creature) -> Creature:
    if creature.external_id:
        row = conn.execute(
            "SELECT * FROM creatures WHERE external_id = ?",
            (creature.external_id,),
        ).fetchone()
        if row is not None:
            return update_creature(conn, creature.with_id(row["id"]))
    return add_creature(conn, creature)


def get_creature(conn, creature_id: int) -> Optional[Creature]:
    row = conn.execute(
        "SELECT * FROM creatures WHERE id = ?",
        (creature_id,),
    ).fetchone()
    if row is None:
        return None
    return creature_from_row(row)


def list_creatures(conn, species: Optional[str] = None) -> list[Creature]:
    if species:
        rows = conn.execute(
            "SELECT * FROM creatures WHERE species = ? ORDER BY id DESC",
            (species,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM creatures ORDER BY id DESC").fetchall()
    return [creature_from_row(row) for row in rows]
