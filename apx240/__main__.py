import argparse, json
from .engine import diagnose

parser=argparse.ArgumentParser(description='APX-240 离线诊断 MVP')
parser.add_argument('description',nargs='?')
parser.add_argument('--serve',action='store_true')
args=parser.parse_args()
if args.serve:
    from .server import main
    main()
elif args.description:
    print(json.dumps(diagnose(args.description).to_dict(),ensure_ascii=False,indent=2))
else: parser.print_help()
