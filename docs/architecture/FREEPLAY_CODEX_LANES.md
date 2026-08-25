# Freeplay Codex Lane Workflow

**Status:** Implemented local operator workflow; not an S2 experiment scheduler

**Scope:** Durable Git worktrees for visible, interactive Codex CLI sessions that
develop or inspect the FactoryVerse freeplay harness

## Purpose

A lane gives one operator Codex session a bounded, durable place to work without
sharing mutable source or campaign artifacts with another lane. It exists to make
parallel harness development reviewable. Creating a lane does not start Codex,
Docker, Factorio, or a campaign.

The FactoryVerse lane CLI uses ordinary Git worktrees. This follows the same basic
foreground/background model described in the
[official Codex worktree documentation](https://learn.chatgpt.com/docs/environments/git-worktrees),
but FactoryVerse owns the worktree path, branch, output root, development slot,
and launch contract itself. It is not a Codex-app-managed worktree or Handoff.

## Ownership model

| Object | Owns | Does not own |
| --- | --- | --- |
| Foreground session | Integration, review, and decisions in the current checkout | A separate lane's source or campaign |
| Lane | Worktree, branch, ancestry floor, output root, operator objective, Codex launch policy, and default development slot | Scientific assignment, runtime lease, evaluated model thread, verdict, or comparison |
| Operator Codex session | Interactive reasoning and edits inside one lane | Factorio lifecycle or experimental truth |
| S2 experiment | Frozen conditions, assignments, paired seeds, actual slots, budgets, validity, and outcome rules | Source editing or gameplay control |
| Campaign supervisor | Campaign world, evaluated actor, sessions, checkpoints, and lifecycle | Cross-campaign comparison |
| S1 allocation | One runtime session's host slot, ports, Compose project, paths, and lease | Model, seed, treatment, or task verdict |

An operator Codex session entered with `fv lane enter` is not the evaluated Codex
actor launched by `fv freeplay-eval codex`. The first works on or operates the
harness. The second is part of a campaign's scientific configuration.

## When a lane is useful

Use a lane when work should have an independent source history, output root, or
interactive Codex operator, including:

- a one-variable harness or instruction candidate;
- an investigation that may create disposable code;
- an independently reviewable implementation branch;
- an ad hoc development campaign that must not share artifacts with another lane;
  or
- a long-lived Codex CLI session you want to enter again later.

Do not create a lane merely for read-only repository analysis, unit tests on the
shared baseline, documentation synthesis, or coordination. Those can remain in the
foreground session until their source needs to diverge.

## Create a lane

From any worktree in the repository:

```bash
uv run fv lane create clock-policy-a \
  --base HEAD \
  --root ../FactoryVerse-lanes \
  --development-slot 0 \
  --env-file .env \
  --objective "Implement and test one clock-policy candidate"
```

`--root`, `--path`, and `--env-file` resolve relative to the directory from which
the command is invoked. Without `--root` or `--path`, the worktree is created under
a sibling directory named `<primary-worktree>-lanes`. `--output-dir` resolves
inside the new worktree and is rejected if it escapes that boundary.

Creation atomically chooses a lane name and default development slot under the
repository's shared Git metadata. Concurrent creation processes cannot claim the
same name or development slot. The durable manifest is stored under:

```text
<git-common-dir>/factoryverse-lanes/<lane-name>.json
```

The branch defaults to `research/lane-<lane-name>`. The manifest records the exact
starting commit, while later descendant commits and dirty state remain visible in
`lane status`.

### Development-slot semantics

The lane's slot is only a collision-avoiding default for ad hoc development. It is
not held when the lane is idle, and it is not part of a scientific treatment.
The S1 supervisor acquires the authoritative host lease only when a campaign
starts.

An S2 experiment must use the slot from its frozen assignment, even when that slot
differs from the lane default. Treatments must be randomized or counterbalanced
across slots and start order rather than permanently mapped to lane identities.

## Inspect before entering

```bash
uv run fv lane list
uv run fv lane status clock-policy-a
uv run fv lane path clock-policy-a
uv run fv lane enter clock-policy-a --dry-run
```

`status` verifies that the path remains a registered worktree, the expected branch
is checked out, and the current HEAD descends from the recorded floor. It also
reports dirty state, Codex executable availability, and campaign state summaries
found under the lane's output root.

`path` prints only the canonical worktree path so it can be copied into an editor
or terminal. `enter --dry-run` prints the exact Codex command and injected operator
contract without launching it.

## Enter the visible Codex CLI

```bash
uv run fv lane enter clock-policy-a
```

An additional assignment can be appended without changing the durable lane
objective:

```bash
uv run fv lane enter clock-policy-a \
  --prompt "Audit the phase transition exception paths before editing"
```

Entry uses the lane worktree as Codex's working directory, applies the recorded
sandbox and approval policy, and preserves terminal scrollback by default. The
injected contract requires the operator to report its worktree, branch, status,
ancestry, and objective before acting. It must show the exact campaign command
before launching gameplay and must not commit, push, merge, or delete worktrees
without explicit user direction.

This is a cooperative operational boundary, not an adversarial security sandbox.
All Git worktrees share repository metadata, and host compute remains shared.

## Environment behavior

Lane commands do not implicitly load the invoking checkout's `.env`. On entry:

1. inherited `FV_*` variables are removed;
2. only `FV_*` values from the lane's optional `--env-file` are loaded;
3. `FV_OUTPUT_DIR` is replaced with the lane-private output root; and
4. lane name and default development slot are exposed as
   `FACTORYVERSE_LANE_NAME` and
   `FACTORYVERSE_LANE_DEVELOPMENT_SLOT`.

Non-`FV_*` parent environment values remain available so normal shell and Codex
authentication continue to work. The env file is an operational input and can
change; S2 must independently freeze and verify the effective scientific
configuration for comparative work.

## Campaign use

For an ad hoc development campaign, the lane's default is appropriate:

```bash
uv run fv freeplay-eval codex \
  --campaign clock-policy-a-smoke-001 \
  --model <model> \
  --slot 0 \
  <other-development-options>
```

For an S2 experiment, do not derive the campaign ID, slot, source commit, or
configuration from the lane prompt. Use the experiment's immutable assignment and
generated command. A lane may produce candidate source, but comparative workers
must use the exact clean assigned commit and placement schedule.

## Review and artifact flow

The expected review loop is:

```text
lane create
  -> lane status and enter --dry-run
  -> visible interactive Codex work
  -> inspect Git diff and lane output
  -> retain, reimplement, or discard the candidate
  -> integrate only after explicit review
```

`fv lane status` lists campaign lifecycle summaries, but campaign artifacts remain
owned by the Freeplay campaign store under the lane's private output root. Engine,
database, checkpoint, and supervisor evidence outrank operator-authored summaries.
The lane CLI does not merge branches or classify experimental results.

If the Codex process exits, the lane remains registered and can be entered again.
If a campaign supervisor dies, use S1's label-verified recovery command rather than
Docker directly:

```bash
uv run fv freeplay-eval recover --campaign <campaign-id>
```

## Safe retirement

Run retirement from a different worktree:

```bash
uv run fv lane retire clock-policy-a
```

Retirement fails closed if:

- it is invoked from inside the target lane;
- the worktree or branch no longer matches the manifest;
- tracked or untracked changes are present;
- a campaign is provisioning or running; or
- any files remain under the lane output root.

On success, it removes the clean worktree and lane registry entry, releases the
default development slot, and preserves the Git branch. It never deletes campaign
artifacts or the branch. Review, move, or otherwise preserve any artifacts and
source changes before retirement.

## What lanes deliberately do not solve

Lanes do not provide:

- adversarial filesystem or Python isolation;
- automatic model or campaign scheduling;
- scientific randomization, pairing, grading, or retry policy;
- exact-commit enforcement for comparative attempts;
- host CPU, disk, memory, or network isolation; or
- automatic integration of candidate changes.

S1 owns runtime non-interference. S2 must own scientific assignment and validity.
The foreground session remains the place where candidate diffs and evidence are
reviewed before integration.
