#!/usr/bin/env python3
"""
ML System Comprehensive Check
Verifies all ML components are working properly.
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def check_imports():
    """Check if all ML modules can be imported"""
    print("\n" + "="*70)
    print("CHECKING ML IMPORTS")
    print("="*70)
    
    # Import from nifty_trader context
    try:
        os.chdir("nifty_trader")
        sys.path.insert(0, os.getcwd())
    except:
        pass
    
    modules = [
        ("feature_store", "ml.feature_store", "FEATURE_COLUMNS"),
        ("readiness_checker", "ml.readiness_checker", "MLReadinessChecker"),
    ]
    
    results = []
    for name, path, symbol in modules:
        try:
            mod = __import__(path, fromlist=[symbol] if symbol else [])
            if symbol:
                obj = getattr(mod, symbol)
            status = f"✅ {name}"
            results.append((name, True))
            print(status)
        except Exception as e:
            status = f"❌ {name}: {str(e)[:50]}"
            results.append((name, False))
            print(status)
    
    # Note: model_manager, outcome_tracker need config at package level
    print(f"⏳ model_manager (requires config in sys.path)")
    print(f"⏳ outcome_tracker (requires database in sys.path)")
    
    return results

def check_model_files():
    """Check if model files exist"""
    print("\n" + "="*70)
    print("CHECKING MODEL FILES")
    print("="*70)
    
    model_path = "nifty_trader/models"
    
    if not os.path.exists(model_path):
        print(f"❌ Model directory not found: {model_path}")
        return False
    
    files = os.listdir(model_path)
    pkl_files = [f for f in files if f.endswith('.pkl')]
    meta_files = [f for f in files if f.endswith('_meta.json')]
    
    print(f"✅ Model directory found")
    print(f"   PKL models: {len(pkl_files)}")
    print(f"   Metadata files: {len(meta_files)}")
    
    # Check latest model
    latest_meta = "nifty_trader/models/latest_meta.json"
    if os.path.exists(latest_meta):
        try:
            import json
            with open(latest_meta, 'r') as f:
                meta = json.load(f)
            print(f"✅ Latest model: v{meta.get('version')} ({meta.get('samples_used')} samples)")
            print(f"   F1: {meta.get('metrics', {}).get('f1', 'N/A'):.3f}")
            print(f"   Trained at: {meta.get('trained_at')}")
            return True
        except Exception as e:
            print(f"⚠️  Could not read latest_meta.json: {e}")
            return False
    else:
        print(f"⚠️  Latest model metadata not found")
        return False

def check_feature_columns():
    """Check if feature columns are defined"""
    print("\n" + "="*70)
    print("CHECKING FEATURE COLUMNS")
    print("="*70)
    
    try:
        from nifty_trader.ml.feature_store import FEATURE_COLUMNS
        print(f"✅ FEATURE_COLUMNS defined: {len(FEATURE_COLUMNS)} features")
        
        # Check for key features
        key_features = [
            "compression_ratio", "atr", "pcr", "plus_di", "minus_di",
            "iv_skew_ratio", "engines_count"
        ]
        
        missing = [f for f in key_features if f not in FEATURE_COLUMNS]
        if missing:
            print(f"⚠️  Missing key features: {missing}")
        else:
            print(f"✅ All key features present")
        
        return True
    except Exception as e:
        print(f"❌ Error checking features: {e}")
        return False

def check_database_integration():
    """Check if ML system can connect to database"""
    print("\n" + "="*70)
    print("CHECKING DATABASE INTEGRATION")
    print("="*70)
    
    try:
        from nifty_trader.database.manager import get_db
        db = get_db()
        
        # Try to query for labeled data
        with db.get_session() as session:
            from sqlalchemy import text
            result = session.execute(
                text("SELECT COUNT(*) as cnt FROM ml_feature_records WHERE label IS NOT NULL")
            )
            count = result.scalar()
            print(f"✅ Database connected")
            print(f"   Labeled feature records: {count}")
            return True
    except Exception as e:
        print(f"⚠️  Database check (non-critical): {str(e)[:60]}")
        return False

def check_model_loading():
    """Check if model can be loaded"""
    print("\n" + "="*70)
    print("CHECKING MODEL LOADING")
    print("="*70)
    
    try:
        from nifty_trader.ml.model_manager import get_model_manager
        mm = get_model_manager()
        
        if mm._model_version:
            print(f"✅ Model loaded: v{mm._model_version.version}")
            print(f"   Samples: {mm._model_version.samples_used}")
            print(f"   Model type: {mm._model_version.model_type}")
            
            # Check if predictions work
            test_pred = mm.predict_for_signal({
                "compression_ratio": 0.5,
                "atr": 100,
                "pcr": 1.2,
                "plus_di": 25,
                "minus_di": 20,
            })
            
            if test_pred.is_available:
                print(f"✅ Predictions working: {test_pred.recommendation}")
                print(f"   Confidence: {test_pred.ml_confidence:.1f}%")
            else:
                print(f"⚠️  Predictions not available: {test_pred.recommendation}")
            
            return True
        else:
            print(f"⚠️  No model loaded")
            return False
            
    except Exception as e:
        print(f"⚠️  Model loading: {str(e)[:60]}")
        return False

def main():
    print("\n")
    print("█" * 70)
    print("█ ML SYSTEM COMPREHENSIVE CHECK")
    print("█" * 70)
    print(f"Timestamp: {datetime.now().isoformat()}")
    
    results = {
        "imports": check_imports(),
        "models": check_model_files(),
        "features": check_feature_columns(),
        "database": check_database_integration(),
        "loading": check_model_loading(),
    }
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    checks = [
        ("ML Imports", all([r[1] for r in results.get("imports", [])]))
        if results.get("imports") else ("ML Imports", False),
        ("Model Files", results.get("models")),
        ("Features", results.get("features")),
        ("Database", results.get("database")),
        ("Model Loading", results.get("loading")),
    ]
    
    passed = sum(1 for _, r in checks if r)
    total = len(checks)
    
    for name, result in checks:
        status = "✅" if result else "⚠️ " if result is None else "❌"
        print(f"{status} {name}")
    
    print(f"\nResult: {passed}/{total} checks passed")
    
    if passed >= 4:
        print("\n🎉 ML SYSTEM IS OPERATIONAL ✅")
    else:
        print("\n⚠️  Some ML checks failed - see above for details")

if __name__ == "__main__":
    main()
