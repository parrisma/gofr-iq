# Simulation Folder Consolidation Plan

**Architect**: Systems Architecture & Sales Trading SME  
**Date**: 2026-01-18  
**Objective**: Eliminate redundancy, consolidate documentation, create operational excellence

---

## Current State Assessment

### Documentation (10 files, 1,279 lines)
```
295 lines - simulation_enhancement_plan.md        [MASTER - Keep & Enhance]
374 lines - SIMULATION_GAP_ANALYSIS.md           [ARCHIVE - Historical]
215 lines - SIMULATION_ENHANCEMENT_PROPOSAL.md   [ARCHIVE - Historical] 
100 lines - RUNNING_SIMULATION.md                [CONSOLIDATE - Operational Guide]
 82 lines - simulation_enhanced_workflow.md      [DELETE - Superseded]
 68 lines - GAP_REMEDIATION_PLAN.md              [DELETE - Completed]
 57 lines - readme.md                            [ENHANCE - Entry Point]
 46 lines - objective.md                         [CONSOLIDATE - Into README]
 42 lines - synthetic_data_proposal.md           [DELETE - Implemented]
  ? lines - archive/simulation_ssot_plan.md      [KEEP - Archive]
```

### Scripts (18 Python, 7 Shell)
**Core Operational Scripts** (Keep):
- `run_simulation.sh` - Master orchestrator
- `run_simulation.py` - Python orchestrator
- `reset_simulation_env.sh` - Clean slate
- `generate_synthetic_stories.py` - Story generation
- `ingest_synthetic_stories.py` - Document ingestion
- `load_simulation_data.py` - Consolidated universe + clients loader
- `validate_feeds.py` - Feed validation
- `query_client_feed.py` - Feed query CLI

**IPS/Profile Management** (Keep):
- `generate_client_ips.py` - IPS generation
- `client_profiler.py` - IPS filtering/ranking
- `demo_ips_filtering.py` - IPS demo

**Utility Scripts** (Review):
- `check_documents.py` - Diagnostic
- `check_cache.py` - Diagnostic
- `validate_simulation.py` - Stage gate validation
- `setup_neo4j_constraints.py` - Setup

**Redundant/Legacy** (Delete):
- `backfill_sources.py` - Replaced by orchestrator
- `backfill_sources.sh` - Replaced by orchestrator
- `load_sources_to_neo4j.py` - Replaced by orchestrator
- `generate_synthetic_clients.py` - Replaced by orchestrator
- `run_backfill.sh` - No longer used
- `query_feed.sh` - Redundant wrapper
- `validate_feeds.sh` - Redundant wrapper
- `setup_neo4j_constraints.sh` - Redundant wrapper

---

## Phase 1: Delete Redundant Files

### Documents to Delete
```bash
rm simulation/simulation_enhanced_workflow.md
rm simulation/GAP_REMEDIATION_PLAN.md
rm simulation/synthetic_data_proposal.md
```

**Rationale**:
- `simulation_enhanced_workflow.md` - Content merged into run_simulation.sh
- `GAP_REMEDIATION_PLAN.md` - Gap remediated, now in enhancement_plan.md
- `synthetic_data_proposal.md` - Proposal implemented

### Scripts to Delete
```bash
rm simulation/backfill_sources.py
rm simulation/backfill_sources.sh
rm simulation/load_sources_to_neo4j.py
rm simulation/generate_synthetic_clients.py
rm simulation/run_backfill.sh
rm simulation/query_feed.sh
rm simulation/validate_feeds.sh
rm simulation/setup_neo4j_constraints.sh
```

**Rationale**:
- Backfill scripts: Functionality now in run_simulation.sh orchestrator
- Shell wrappers: Thin wrappers around Python scripts - call Python directly
- load_sources_to_neo4j.py: Sources created by orchestrator during run_simulation.sh
- generate_synthetic_clients.py: Client data now in universe builder

---

## Phase 2: Archive Historical Documents

### Move to Archive
```bash
mkdir -p simulation/archive/planning
mv simulation/SIMULATION_GAP_ANALYSIS.md simulation/archive/planning/
mv simulation/SIMULATION_ENHANCEMENT_PROPOSAL.md simulation/archive/planning/
```

**Rationale**: Historical analysis documents - useful for understanding evolution, not for daily operations

---

## Phase 3: Consolidate Documentation

### 3.1 New Structure (4 Core Documents)

```
simulation/
├── README.md                    [MASTER ENTRY POINT]
├── OPERATIONAL_GUIDE.md         [HOW TO RUN]
├── ARCHITECTURE.md              [WHAT & WHY]
├── VALIDATION.md                [TESTING & RESULTS]
└── archive/
    └── planning/
```

### 3.2 README.md (Master Entry Point)
**Length**: ~100 lines  
**Sections**:
1. **Quick Start** (3 commands to run simulation)
2. **What Is This?** (Purpose, use cases)
3. **Components** (Scripts, data, outputs)
4. **Document Index** (Links to other 3 docs)
5. **Common Operations** (Reset, validate, query)

### 3.3 OPERATIONAL_GUIDE.md (SOP)
**Consolidates**: RUNNING_SIMULATION.md + orchestrator documentation  
**Length**: ~150 lines  
**Sections**:
1. **Prerequisites** (Infrastructure, tokens, env)
2. **Standard Workflow** (6-step process)
3. **Orchestrated Run** (run_simulation.sh usage)
4. **Manual Steps** (When to run individual scripts)
5. **Validation** (How to verify each stage)
6. **Troubleshooting** (Common issues)

### 3.4 ARCHITECTURE.md (System Design)
**Consolidates**: objective.md + universe design + IPS architecture  
**Length**: ~200 lines  
**Sections**:
1. **System Objective** (Client-centric RAG story selection)
2. **Universe Model** (16 companies, relationships, factors)
3. **Client Model** (Archetypes, portfolios, IPS)
4. **Story Generation** (LLM prompting, scenarios)
5. **Graph Schema** (Node types, relationships)
6. **IPS Architecture** (External JSON, filtering, reranking)
7. **Feed Intelligence** (Query flow, scoring)

### 3.5 VALIDATION.md (Testing & Results)
**Consolidates**: simulation_enhancement_plan.md results + validation patterns  
**Length**: ~150 lines  
**Sections**:
1. **Phase Status** (What's complete, what's parked)
2. **Validation Harness** (validate_feeds.py usage)
3. **Test Scenarios** (Direct holdings, supply chain, competitor, etc.)
4. **Current Results** (Pass rates, known issues)
5. **IPS Demo** (demo_ips_filtering.py results)
6. **Next Steps** (Parked features, future work)

---

## Phase 4: Script Consolidation

### 4.1 Core Script Set (9 Operational Scripts)

**Orchestration**:
- `run_simulation.sh` - Master orchestrator (keep as-is)
- `reset_simulation_env.sh` - Clean slate (keep as-is)

**Generation**:
- `generate_synthetic_stories.py` - Story generation (keep)
- `generate_client_ips.py` - IPS generation (keep)

**Loading**:
- `ingest_synthetic_stories.py` - Document ingestion (keep)
- `load_simulation_data.py` - Consolidated universe + clients loader (keep)
- `setup_neo4j_constraints.py` - Constraints (keep, called by orchestrator)

**Query & Validation**:
- `query_client_feed.py` - Feed query CLI (keep)
- `validate_feeds.py` - Feed validation (keep)

**IPS**:
- `client_profiler.py` - IPS filtering/ranking (keep)
- `demo_ips_filtering.py` - IPS demo (keep)

### 4.2 Utility Scripts (Keep for Diagnostics)
- `check_documents.py` - Useful for debugging
- `check_cache.py` - Useful for cache inspection
- `validate_simulation.py` - Stage gate validation (used by orchestrator)

### 4.3 Script Consolidation Actions

**Legacy loader merge (completed)**:
```python
# Completed: load_simulation_data.py now covers companies, instruments, factors, clients, portfolios
```

**Result**: 11 operational scripts (down from 18)

---

## Phase 5: Directory Structure

### Final Structure
```
simulation/
├── README.md                           [Entry point - 100 lines]
├── OPERATIONAL_GUIDE.md                [SOP - 150 lines]
├── ARCHITECTURE.md                     [Design - 200 lines]
├── VALIDATION.md                       [Testing - 150 lines]
│
├── run_simulation.sh                   [Master orchestrator]
├── reset_simulation_env.sh             [Clean slate]
│
├── generate_synthetic_stories.py       [Story generation]
├── generate_client_ips.py              [IPS generation]
├── ingest_synthetic_stories.py         [Document ingestion]
├── load_simulation_data.py             [Universe + clients loader]
├── setup_neo4j_constraints.py          [Constraints setup]
│
├── query_client_feed.py                [Feed query CLI]
├── validate_feeds.py                   [Feed validation]
├── client_profiler.py                  [IPS filtering/ranking]
├── demo_ips_filtering.py               [IPS demo]
│
├── check_documents.py                  [Diagnostic]
├── check_cache.py                      [Diagnostic]
├── validate_simulation.py              [Stage gates]
│
├── universe/
│   ├── __init__.py
│   ├── builder.py                      [Universe model]
│   └── types.py                        [Data structures]
│
├── client_ips/                         [IPS JSON files]
│   ├── ips_client-hedge-fund.json
│   ├── ips_client-pension-fund.json
│   └── ips_client-retail.json
│
├── test_output/                        [Generated stories]
│   └── synthetic_*.json
│
├── tokens.json                         [Cached auth tokens]
├── .env.openrouter                     [OpenRouter key]
│
└── archive/
    ├── planning/
    │   ├── SIMULATION_GAP_ANALYSIS.md
    │   ├── SIMULATION_ENHANCEMENT_PROPOSAL.md
    │   └── simulation_ssot_plan.md
    └── scripts/                        [Deprecated scripts]
```

---

## Implementation Steps

### Step 1: Backup Current State
```bash
cd /home/gofr/devroot/gofr-iq/simulation
tar -czf ../simulation_backup_$(date +%Y%m%d).tar.gz .
```

### Step 2: Delete Redundant Files
```bash
# Documents
rm simulation_enhanced_workflow.md
rm GAP_REMEDIATION_PLAN.md
rm synthetic_data_proposal.md

# Scripts
rm backfill_sources.py backfill_sources.sh
rm load_sources_to_neo4j.py
rm generate_synthetic_clients.py
rm run_backfill.sh query_feed.sh validate_feeds.sh setup_neo4j_constraints.sh
```

### Step 3: Archive Historical Docs
```bash
mkdir -p archive/planning archive/scripts
mv SIMULATION_GAP_ANALYSIS.md archive/planning/
mv SIMULATION_ENHANCEMENT_PROPOSAL.md archive/planning/
```

### Step 4: Create New Documentation
```bash
# Create 4 consolidated docs
touch OPERATIONAL_GUIDE.md
touch ARCHITECTURE.md
touch VALIDATION.md
# Rewrite README.md
```

### Step 5: Consolidate Scripts
```bash
# Legacy loaders merged into load_simulation_data.py
# run_simulation.sh/run_simulation.py now call the consolidated loader
```

### Step 6: Update Cross-References
```bash
# Update all docs to reference new structure
# Update scripts to reference new doc locations
```

### Step 7: Validate
```bash
# Run full simulation to verify nothing broke
./run_simulation.sh --count 5
./validate_feeds.py
```

---

## Success Metrics

### Before
- **10 markdown files**, 1,279 lines total
- **18 Python scripts**, 7 shell wrappers
- Fragmented documentation with duplication
- Unclear entry point for new users

### After
- **4 markdown files**, ~600 lines total (50% reduction)
- **11 operational scripts** (39% reduction)
- Clear hierarchy: README → Guide/Architecture/Validation
- Single source of truth per topic
- No duplication
- Operational focus

---

## Timeline

- **Phase 1** (Delete): 15 minutes
- **Phase 2** (Archive): 5 minutes
- **Phase 3** (Documentation): 2-3 hours (content consolidation)
- **Phase 4** (Scripts): 1 hour (merge load scripts)
- **Phase 5** (Structure): 30 minutes
- **Testing**: 1 hour

**Total**: ~5 hours

---

## Risk Mitigation

1. **Full backup** before any deletions
2. **Git branch** for consolidation work
3. **Test suite** validation after changes
4. **Rollback plan**: Restore from backup if issues
5. **Incremental commits**: Commit after each phase

---

## Approval Checkpoints

- [ ] Phase 1 complete: Files deleted, verified no breakage
- [ ] Phase 2 complete: Archives moved, structure clean
- [ ] Phase 3 complete: New docs written, reviewed
- [ ] Phase 4 complete: Scripts consolidated, tested
- [ ] Phase 5 complete: Final structure validated
- [ ] Full simulation run successful
- [ ] Documentation reviewed and approved

---

## Next Actions

1. **Review this plan** with stakeholders
2. **Create git branch**: `feature/simulation-consolidation`
3. **Execute Phase 1**: Delete redundant files
4. **Execute Phase 2**: Archive historical docs
5. **Execute Phase 3**: Write consolidated documentation
6. **Execute Phase 4**: Consolidate scripts
7. **Test & validate**: Run full simulation
8. **Merge to main**: After approval
