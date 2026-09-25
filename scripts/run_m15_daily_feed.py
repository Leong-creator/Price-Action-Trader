#!/usr/bin/env python3
"""Read-only daily-feed preparation, native-task dispatch and truthful status."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.m15_feed_runtime import daily


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','prepare-intraday','launch','status'))
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--market-date')
    parser.add_argument('--window-start-utc')
    parser.add_argument('--window-end-utc')
    parser.add_argument('--session-key')
    parser.add_argument('--diagnostic-capture-after-quality-fault',action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.command!='prepare-intraday' and (args.window_start_utc or args.window_end_utc or args.diagnostic_capture_after_quality_fault):
            raise ValueError('intraday_options_require_prepare_intraday')
        if args.command not in ('launch','status') and args.session_key:
            raise ValueError('session_key_requires_launch_or_status')
        if args.command=='prepare-intraday':
            if not args.market_date or not args.window_start_utc or not args.window_end_utc:
                raise ValueError('intraday_date_and_window_required')
            value=daily.prepare_intraday(args.config,args.market_date,args.window_start_utc,args.window_end_utc,
                diagnostic_capture_after_quality_fault=args.diagnostic_capture_after_quality_fault)
        elif args.command=='prepare':
            if args.market_date is None:raise ValueError('prepare_requires_market_date')
            value=daily.prepare(args.config,args.market_date)
        elif args.command=='launch':
            value=daily.launch(args.config,args.market_date,session_key=args.session_key)
        else:value=daily.status(args.config,args.market_date,session_key=args.session_key)
        print(json.dumps(value,sort_keys=True));return 0
    except Exception as exc:
        # Native exception text or credentials are never dumped into safe output.
        reason=str(exc) if isinstance(exc,(ValueError,RuntimeError)) and str(exc).replace('_','').isalnum() else type(exc).__name__
        print(json.dumps({'status':'refused','reason':reason,'sdk_started':False}));return 4


if __name__=='__main__':raise SystemExit(main())
