import argparse

def main():
    parser=argparse.ArgumentParser(description='Aura wallpaper playground')
    parser.add_argument('--export',metavar='PNG'); parser.add_argument('--recipe')
    parser.add_argument('--width',type=int,default=3840); parser.add_argument('--height',type=int,default=2160)
    parser.add_argument('--depth',type=int,choices=(8,16),default=16)
    args=parser.parse_args()
    if args.export:
        import json
        from pathlib import Path
        from .model import Design
        from .render import export_png
        d=Design.from_dict(json.loads(Path(args.recipe).read_text())) if args.recipe else Design()
        export_png(d,args.export,args.width,args.height,depth=args.depth)
    else:
        from .app import main as gui
        gui()
if __name__=='__main__': main()
