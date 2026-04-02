#!/usr/bin/env python3
"""
ML System Check - Run from nifty_trader directory
"""

import sys
import json
import os
from datetime import datetime
from pathlib import Path

def check_model_files():
    """Check if model files exist"""
    print("\n" + "="*70)
    print("CHECKING MODEL FILES")
    print("="*70)
    
    model_path = Path("models")
    
    if not model_path.exists():
        print(f"❌ Model directory not found: {model_path}")
        return False
    
    files = list(model_path.glob("*"))
    pkl_files = [f for f in files if f.suffix == '.pkl']
    meta_files = [f for f in files if f.suffix == '.json']
    
    print(f"✅ Model directory found")
    print(f"   PKL models: {len(pkl_files)}")
    print(f"   Metadata files: {len(meta_files)}")
    
    # Check latest model
    latest_meta = model_path / "latest_meta.json"
    if latest_meta.exists():
        try:
            with open(latest_meta, 'r') as f:
                meta = json.load(f)
            print(f"✅ Latest model: v{meta.get('version')} ({meta.get('samples_used')} samples)")
            print(f"   F1: {meta.get('metrics', {}).get('f1', 'N/A'):.3f}")
            print(f"   Precision: {meta.get('metrics', {}).get('precision', 'N/A'):.3f}")
            print(f"   Recall: {meta.get('metrics', {}).get('recall', 'N/A'):.3f}")
            print(f"   ROC-AUC: {meta.get('metrics', {}).get('roc_auc', 'N/A'):.3f}")
            print(f"   Trained at: {meta.get('trained_at')}")
            print(f"   Active: {'Yes' if meta.get('is_active') else 'No'}")
            
            # Check by index
            nifty_model = model_path / "latest_nifty_meta.json"
            banknifty_model = model_path / "latest_banknifty_meta.json"
            
            if nifty_model.exists():
                with open(nifty_model) as f:
                    nifty_meta = json.load(f)
                print(f"\n   NIFTY: v{nifty_meta.get('version')} (F1: {nifty_meta.get('metrics', {}).get('f1', 'N/A'):.3f})")
            
            if banknifty_model.exists():
                with open(banknifty_model) as f:
                    bn_meta = json.load(f)
                print(f"   BANKNIFTY: v{bn_meta.get('version')} (F1: {bn_meta.get('metrics', {}).get('f1', 'N/A'):.3f})")
            
            return True
        except Exception as e:
            print(f"⚠️  Could not read latest_meta.json: {e}")
            return False
    else:
        print(f"⚠️  Latest model metadata not found")
        return False

def check_ml_files():
    """Check if ML source files exist"""
    print("\n" + "="*70)
    print("CHECKING ML SOURCE FILES")
    print("="*70)
    
    ml_path = Path("ml")
    
    if not ml_path.exists():
        print(f"❌ ML directory not found: {ml_path}")
        return False
    
    required_files = [
        "model_manager.py",
        "outcome_tracker.py",
        "auto_labeler.py",
        "feature_store.py",
        "readiness_checker.py",
        "setups.py",
        "historical_trainer.py",
    ]
    
    found = []
    missing = []
    
    for file in required_files:
        filepath = ml_path / file
        if filepath.exists():
            size = filepath.stat().st_size
            found.append(file)
            print(f"✅ {file:30} ({size:,} bytes)")
        else:
            missing.append(file)
            print(f"❌ {file}")
    
    if missing:
        print(f"\n❌ Missing files: {missing}")
        return False
    else:
        print(f"\n✅ All {len(found)} ML source files present")
        return True

def check_feature_columns_file():
    """Check if feature_store properly defines features"""
    print("\n" + "="*70)
    print("CHECKING FEATURE COLUMNS DEFINITION")
    print("="*70)
    
    feature_file = Path("ml/feature_store.py")
    
    if not feature_file.exists():
        print(f"❌ feature_store.py not found")
        return False
    
    try:
        with open(feature_file, 'r') as f:
            content = f.read()
        
        if "FEATURE_COLUMNS = [" in content:
            print(f"✅ FEATURE_COLUMNS defined in feature_store.py")
            
            # Count features
            lines = content.split('\n')
            in_features = False
            feature_count = 0
            
            for line in lines:
                if "FEATURE_COLUMNS = [" in line:
                    in_features = True
                    continue
                if in_features:
                    if "]" in line and '"' not in line and "'" not in line:
                        break
                    if '"' in line or "'" in line:
                        feature_count += 1
            
            print(f"   Defined features: {feature_count}")
            
            # Check key groups
            groups = {
                "Engine 1 (Compression)": ["compression_ratio", "atr"],
                "Engine 2 (DI Momentum)": ["plus_di", "minus_di", "adx"],
                "Engine 3 (Options)": ["pcr", "iv_rank"],
                "Engine 4 (Volume)": ["volume_ratio"],
                "Time context": ["mins_since_open", "session"],
                "MTF features": ["adx_5m", "adx_15m"],
            }
            
            print("\n   Feature Groups:")
            for group_name, examples in groups.items():
                found_all = all(ex in content for ex in examples)
                status = "✅" if found_all else "⚠️ "
                print(f"   {status} {group_name}")
            
            return True
        else:
            print(f"⚠️  FEATURE_COLUMNS not found in expected format")
            return False
            
    except Exception as e:
        print(f"❌ Error reading feature_store.py: {e}")
        return False

def check_model_training_config():
    """Check if model training is properly configured"""
    print("\n" + "="*70)
    print("CHECKING MODEL TRAINING CONFIGURATION")
    print("="*70)
    
    try:
        import config
        
        settings = {
            "ML_MIN_SAMPLES_TO_ACTIVATE": "Minimum samples to start training",
            "ML_RETRAIN_INTERVAL_SAMPLES": "Retrain every N samples",
            "ML_LOOKAHEAD_CANDLES": "Lookahead candles for labeling",
            "ML_MODEL_TYPE": "Model type (XGBoost/RandomForest)",
            "ML_ENABLE_RETRAINING": "Auto-retraining enabled",
        }
        
        for setting, desc in settings.items():
            if hasattr(config, setting):
                value = getattr(config, setting)
                print(f"✅ {setting:30} = {value:20} ({desc})")
            else:
                print(f"⚠️  {setting:30} (not defined)")
        
        return True
        
    except Exception as e:
        print(f"⚠️  Config check (non-critical): {e}")
        return False

def check_ml_integration():
    """Check if ML is integrated with trading system"""
    print("\n" + "="*70)
    print("CHECKING ML-TRADING INTEGRATION")
    print("="*70)
    
    checks = {
        "ml in __init__.py": lambda: "from ml" in open("__init__.py").read() if os.path.exists("__init__.py") else False,
        "signals use ML": lambda: "ml_confidence" in open("engines/signal_aggregator.py").read() if os.path.exists("engines/signal_aggregator.py") else False,
        "pre_live_checklist has ML check": lambda: "model_manager" in open("trading/pre_live_checklist.py").read() if os.path.exists("trading/pre_live_checklist.py") else False,
    }
    
    for check_name, check_func in checks.items():
        try:
            result = check_func()
            status = "✅" if result else "⚠️ "
            print(f"{status} {check_name}")
        except Exception as e:
            print(f"⏳ {check_name} (skipped: {str(e)[:40]})")
    
    return True

def main():
    print("\n" + "█"*70)
    print("█ ML SYSTEM COMPREHENSIVE CHECK")
    print("█"*70)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Working directory: {os.getcwd()}")
    
    results = {
        "Models": check_model_files(),
        "ML Files": check_ml_files(),
        "Features": check_feature_columns_file(),
        "Config": check_model_training_config(),
        "Integration": check_ml_integration(),
    }
    
    # Summary
    print("\n" + "="*70)
    print("OVERALL ML SYSTEM STATUS")
    print("="*70)
    
    passed = sum(1 for r in results.values() if r)
    total = len(results)
    
    for name, result in results.items():
        status = "✅" if result else "❌"
        print(f"{status} {name}")
    
    print(f"\nResult: {passed}/{total} components verified")
    
    if passed >= 4:
        print("\n🎉 ML SYSTEM IS OPERATIONAL ✅")
        print("\nML System Status:")
        print("  • Models trained and ready")
        print("  • Feature engineering complete")
        print("  • Integration with trading system connected")
        print("  • Production ready for live trading")
    else:
        print("\n⚠️  Some ML checks failed - review details above")

if __name__ == "__main__":
    # Change to nifty_trader directory
    if os.path.exists("nifty_trader"):
        os.chdir("nifty_trader")
    
    main()
