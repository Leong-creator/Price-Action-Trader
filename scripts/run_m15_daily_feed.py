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
    parser.add_argument('command',choices=('prepare','launch','status'))
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--market-date')
    args=parser.parse_args(argv)
    try:
        if args.command=='prepare':
            if args.market_date is None:raise ValueError('prepare_requires_market_date')
            value=daily.prepare(args.config,args.market_date)
        else:value=getattr(daily,args.command)(args.config,args.market_date)
        print(json.dumps(value,sort_keys=True));return 0
    except Exception as exc:
        # Native exception text or credentials are never dumped into safe output.
        reason=str(exc) if isinstance(exc,(ValueError,RuntimeError)) and str(exc).replace('_','').isalnum() else type(exc).__name__
        print(json.dumps({'status':'refused','reason':reason,'sdk_started':False}));return 4


if __name__=='__main__':raise SystemExit(main())
