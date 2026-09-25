#!/usr/bin/env python3
"""Fixed-budget read-only clock evidence. Never resyncs or changes configuration."""
from __future__ import annotations
import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import m15_feed_clock as clock


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows-python',required=True)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--comparison',action='store_true',help='Add exactly three Microsoft samples per preselected host.')
    args=parser.parse_args(argv)
    if not args.comparison:
        result=clock.collect_time_quality(args.windows_python,args.output_dir)
    else:
        output=Path(args.output_dir);output.mkdir(parents=True,exist_ok=False)
        started=datetime.now(UTC).isoformat()
        try:
            comparison=clock._run_windows(args.windows_python,'comparison',35)
        except Exception as error:
            comparison={'error':type(error).__name__,'custom_ntp':{'samples':[],'platform':'win32'}}
        clock._save(output/'windows-fixed-comparison.json',comparison)
        cross=clock.collect_cross_clock(args.windows_python)
        clock._save(output/'windows-wsl-handshake.json',cross)
        result=clock.assess_time_quality(comparison['custom_ntp'],cross)
        result.update(started_at=started,finished_at=datetime.now(UTC).isoformat(),
                      evidence_dir=str(output),comparison_used_for_acceptance=False,
                      workload='idle_pre_session',read_only=True)
        clock._save(output/'assessment.json',result)
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    return 0 if result['quality_passed'] else 2


if __name__=='__main__':raise SystemExit(main())
