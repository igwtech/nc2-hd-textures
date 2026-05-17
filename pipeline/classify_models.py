#!/usr/bin/env python3
"""
Inventory + subject/material classification of gfx/modeltextures.

NC2 model-texture names encode faction/class + body part. These are UV
atlases (per-texel svBRDF unreliable on a UV unwrap), so the correct ORME
is a SUBJECT-INFORMED profile, not pixel decomposition. This script
classifies every texture and reports coverage + the unclassified tail so
the regex table can be tightened before any Replicate spend.

Classes -> ORME intent (R=occ G=rough B=metal A=emis):
  skin        humanoid head/face/hands  : M0    R0.55 dielectric, smooth-ish
  cloth       top/trouser/legs/torso    : M0    R0.85 fabric, AO from folds
  powerarmor  PA / dreddoom / traderpa  : M0.80 R0.35 painted metal, optics emis
  robot       cop/war/spider/drone bots : M0.85 R0.30 metal, sensor emis
  mutant      mutants / freaks / mobs   : M0    R0.85 organic, bio-emis heuristic
  object      props/area/doy/misc       : name-heuristic (metal/wood/...) fallback
Roughness/AO still take a per-pixel nudge from the regen luminance; the
class sets the base + the metallic/emissive policy.
"""
import re, subprocess, sys, collections
from pathlib import Path
import ncconfig

SRC = ncconfig.GAME_DIR / "gfx" / "modeltextures"

# body part (suffix-ish) — decides skin vs cloth within a humanoid
PART = [
    ("skin",  re.compile(r"(head|face|hand|cophead|skull)", re.I)),
    ("cloth", re.compile(r"(top|trouser|legs?|torso|trous|jacket|coat|"
                         r"boot|glove|cloth|service|body|suit|uniform|"
                         r"vest|armor|guard)", re.I)),
]
# subject (faction / creature / mech). Order = priority.
SUBJECT = [
    ("powerarmor", re.compile(r"(powerarmor|_pa\b|dreddoom|traderpa|"
                              r"\bpa_|heavyarmor)", re.I)),
    ("robot", re.compile(r"(copbot|warbot|spiderbot|droid|drone|\bbot\b|"
                         r"turret|mech|sentry|guardian)", re.I)),
    ("mutant", re.compile(r"(mutant|freak|mob|monster|zombie|creature|"
                          r"larva|spider|warm|brain)", re.I)),
    ("humanoid", re.compile(r"(spy|tank|private|psimonk|psim|monk|"
                            r"pfemale|pmale|afemale|anarcho|dancer|fat|"
                            r"security|medic|nomad|haendler|trader|"
                            r"npc\d|asia|ital|cran|desert|civ|cop|"
                            r"male|female|picster|xmas|bnc|mc\b|militarybase)",
                           re.I)),
]
OBJECT_HINT = re.compile(r"(crate|barrel|box|door|tank_|pipe|vent|"
                         r"terminal|console|sign|lamp|light|chair|table|"
                         r"weapon|gun|rifle|cannon|veh|car|bike|hover)", re.I)


def subject_of(name: str, subdir: str):
    s = subdir.lower()
    if s == "powerarmor":
        sub = "powerarmor"
    else:
        sub = None
        for label, rx in SUBJECT:
            if rx.search(name):
                sub = label
                break
    if sub in (None, "humanoid"):
        for label, rx in PART:
            if rx.search(name):
                # humanoid + part -> skin / cloth
                return ("skin" if label == "skin" else "cloth")
        if sub == "humanoid":
            return "cloth"          # humanoid, unknown part -> assume cloth
        if OBJECT_HINT.search(name):
            return "object"
        return None                 # unclassified
    # robot / mutant / powerarmor: head still = its own surface, keep subject
    return sub


def main():
    files = sorted(p for p in SRC.rglob("*")
                   if p.suffix.lower() in (".dds", ".bmp"))
    cls = collections.Counter()
    by_subdir = collections.Counter()
    uncl = []
    rows = []
    for p in files:
        nm = p.stem
        if nm.startswith("pak_"):
            nm = nm[4:]
        subdir = p.parent.name if p.parent != SRC else "(root)"
        c = subject_of(nm, subdir)
        cls[c or "UNCLASSIFIED"] += 1
        by_subdir[subdir] += 1
        if c is None:
            uncl.append(f"{subdir}/{nm}")
        rows.append((str(p.relative_to(SRC)), c or "UNCLASSIFIED"))

    print(f"modeltextures: {len(files)} textures, subdirs={dict(by_subdir)}")
    print("\nclass distribution:")
    for k, v in cls.most_common():
        print(f"  {k:12s} {v:4d}  ({100*v/len(files):.0f}%)")
    cov = 100 * (len(files) - cls['UNCLASSIFIED']) / len(files)
    print(f"\ncoverage: {cov:.1f}%  unclassified={cls['UNCLASSIFIED']}")
    if uncl:
        print("unclassified sample (tighten regex):")
        for u in uncl[:50]:
            print("  ", u)

    man = ncconfig.MODEL_CLASS_TSV
    man.parent.mkdir(parents=True, exist_ok=True)
    with man.open("w") as f:
        for rel, c in rows:
            f.write(f"{rel}\t{c}\n")
    print(f"\nmanifest -> {man}")


if __name__ == "__main__":
    main()
