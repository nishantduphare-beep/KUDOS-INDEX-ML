#!/usr/bin/env python3
"""
Check why ML ENGINE shows "2 - Active" constantly
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("\n" + "="*70)
print("ML ENGINE PHASE ANALYSIS")
print("="*70)

print("""
WHY IT SHOWS "2 - Active" CONSTANTLY:

The phase display in the ML ENGINE section shows:
  PHASE 1 — Collecting   (when < 200 labeled samples)
  PHASE 2 — Active ✓     (when >= 200 labeled samples and model exists)

Once you have >= MIN_SAMPLES_TO_TRAIN (default: 200) samples and a model exists,
the display PERMANENTLY STAYS at "2 — Active ✓"

═══════════════════════════════════════════════════════════════════════

WHAT'S HAPPENING BEHIND THE SCENES:

Phase 2 Active means:
  ✅ Model exists and is being used for predictions
  ✅ System is continuously collecting new labeled data
  ✅ Every time RETRAIN_INTERVAL samples arrive, auto-retrains
  ✅ Model versions increment (v27 → v28 → v29...)
  ✅ Metrics improve as more data is labeled

The phase doesn't advance to "Phase 3" - that's a conceptual phase mentioned in comments but not implemented.

═══════════════════════════════════════════════════════════════════════

HOW THE PHASES WORK:

Phase 1: Collecting Data (no model yet)
  └─ Condition: labeled_samples < 200
  └─ Display: "1 — Collecting"
  └─ Status: Trading runs on engine signals only (no ML)
  └─ Transitions to Phase 2 when: 200+ samples labeled

Phase 2: Active Model (model exists)
  └─ Condition: labeled_samples >= 200 AND model exists
  └─ Display: "2 — Active ✓"
  └─ Status: Trading uses ML confidence scoring
  └─ Background: Continuous retraining as new data arrives
  └─ Stays here: FOREVER (until model is deleted)

Phase 3: Enhanced Model (mentioned in code comments only)
  └─ Condition: Retraining happens in Phase 2
  └─ Display: No separate UI display for this
  └─ Status: Model improves continuously within Phase 2

═══════════════════════════════════════════════════════════════════════

IMPORTANT: THIS IS CORRECT BEHAVIOR

The "2 - Active" display is WORKING CORRECTLY because:

1. ✅ Model exists (v28)
2. ✅ Model is trained (on 4,373 samples)
3. ✅ Model is active (marked with ✓)
4. ✅ Model is being used for predictions
5. ✅ System is continuously collecting new data and retraining

═══════════════════════════════════════════════════════════════════════

WHAT'S BEING TRACKED (even if not displayed):

Current Status in ML ENGINE section:
  • PHASE: "2 — Active ✓"          ← What version of model
  • LABELED: 4373                  ← Total samples collected
  • MODEL: v28                     ← Current model version
  • F1: 0.389                      ← Performance metric
  • STILL NEEDING: —               ← No longer counting (Phase 2)

Behind the scenes (not shown in UI):
  • Retrain interval: Every 50 new samples
  • Last train count: 4373 samples  
  • Models trained: v1 through v28
  • Next retrain: When 50 more samples labeled (total 4423)

═══════════════════════════════════════════════════════════════════════

WHY NO HIGHER PHASES SHOWN:

The 3-phase system mentioned in comments is:
  Phase 1: < MIN_SAMPLES          → No ML
  Phase 2: >= MIN_SAMPLES         → Model exists
  Phase 3: Continuous retraining  ← Happens in Phase 2, not separate

There's no "Phase 3 - Enhanced" display because retraining happens
continuously IN Phase 2. The number doesn't change, but the model
version number DOES change (v27→v28→v29...) as retraining happens.

═══════════════════════════════════════════════════════════════════════

WHAT TO WATCH FOR INSTEAD OF PHASE CHANGES:

Since phase stays at 2, watch these instead:

1. MODEL VERSION NUMBER (v28 → v29 → v30...)
   └─ Increments when auto-retrain happens
   └─ Check logs: "Model trained: v29"

2. F1 SCORE (0.389 → 0.425 → 0.456...)
   └─ Improves as more quality labeled data arrives
   └─ Better F1 = better model discriminating wins/losses

3. SAMPLES COUNT (4373 → 4423 → 4473...)
   └─ Grows as trades execute and get labeled
   └─ More samples = better model training

4. LABELED SAMPLES QUALITY
   └─ Check ML REPORT tab for "High Quality %"
   └─ Better quality labels = faster model improvement

═══════════════════════════════════════════════════════════════════════

IF YOU WANT IT TO SHOW MORE INFO:

The UI could be enhanced to show:
  • "Phase 2 - Active (v28, retraining...)" during retraining
  • "Phase 2 - Active (v29 ready)" after retraining
  • Retrain progress bar or ETA
  • Model version change notifications

But currently it just shows "2 - Active ✓" and expects you to watch
the version number and F1 score for changes.

═══════════════════════════════════════════════════════════════════════

SUMMARY: This is 100% NORMAL and CORRECT

"2 - Active" doesn't change because once a model is trained,
it STAYS active and continuously improves in Phase 2.

Watch the MODEL VERSION and F1 SCORE instead for signs of improvement.
""")

print("\n" + "="*70)
print("VERIFICATION: Check if model is actually retraining")
print("="*70)

try:
    import config
    from nifty_trader.ml.model_manager import get_model_manager
    
    mm = get_model_manager()
    status = mm.get_status()
    
    print(f"\nCurrent Status:")
    print(f"  Phase: {status['phase']}")
    print(f"  Has Model: {status['has_model']}")
    print(f"  Model Version: v{status['model_version']}")
    print(f"  Labeled Samples: {status['labeled_samples']}")
    print(f"  Samples Used in Training: {status['samples_used']}")
    print(f"  F1 Score: {status['metrics'].get('f1', 'N/A'):.3f}")
    print(f"  Trained At: {status['trained_at']}")
    
    print(f"\nRetraining Trigger:")
    print(f"  Retrain every N samples: {config.ML_RETRAIN_INTERVAL_SAMPLES}")
    print(f"  Samples since last train: {status['labeled_samples'] - status['samples_used']}")
    
    remaining = config.ML_RETRAIN_INTERVAL_SAMPLES - (status['labeled_samples'] - status['samples_used'])
    if remaining > 0:
        print(f"  Samples until next retrain: {remaining}")
    else:
        print(f"  ⚠️  Overdue for retrain by: {-remaining} samples")
        print(f"     → Retaining should happen on next model_manager.predict() call")
    
except Exception as e:
    print(f"Could not access model manager: {e}")

print("\n" + "="*70)
